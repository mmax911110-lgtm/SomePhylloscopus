"""Small, portable local bird catalogue and per-bird recognition archive.

Records describe model predictions, never verified sightings or unique wild birds.
The original result JSON and model outputs are only read, not rewritten.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import uuid


SCHEMA_VERSION = 4
COUNT_LABEL = "识别记录（逐鸟框计次，不代表独立个体或人工确认）"
_PATH_KEYS = {"source", "event_dir", "annotated_path", "snapshot_path", "report_path",
              "result_json", "original_result_path", "original_annotated_path",
              "crop_path", "tight_crop_path"}
# List views do not consume the potentially large classifier payload. Fetch it
# only in event_detail (certificates) and deletion/undo snapshots.
_EVENT_SUMMARY_COLUMNS = (
    "event_id", "source_sha256", "source_name", "source_ref", "result_ref",
    "snapshot_ref", "annotated_ref", "report_ref", "status", "message",
    "detection_mode", "device", "created_at", "imported_at", "updated_at",
    "payload_sha256", "capture_place", "captured_at", "display_name", "notes",
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _score(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 <= number <= 1 else None
    except (ValueError, TypeError):
        return None


def _name(value):
    return str(value or "").strip()


class Library:
    """One reusable instance is safe for GUI and worker threads."""

    def __init__(self, app_root, db_path=None):
        self.app_root = Path(app_root).resolve()
        self.db_path = Path(db_path).resolve() if db_path else self.app_root / "data/bird_library.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.db_path), timeout=15, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS library_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL,
                source_sha256 TEXT, source_name TEXT, source_ref TEXT,
                result_ref TEXT, snapshot_ref TEXT, annotated_ref TEXT, report_ref TEXT,
                status TEXT, message TEXT, detection_mode TEXT, device TEXT,
                created_at TEXT, imported_at TEXT, updated_at TEXT,
                payload_sha256 TEXT, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
                bird_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                scientific_name TEXT, common_name TEXT, prediction_source TEXT,
                classification_confidence REAL, detection_confidence REAL,
                gate_status TEXT, original_scientific_name TEXT, original_name TEXT,
                original_confidence REAL, original_accepted INTEGER,
                specialist_scientific_name TEXT, specialist_common_name TEXT,
                specialist_confidence REAL, specialist_rejected INTEGER,
                crop_ref TEXT, tight_crop_ref TEXT, row_json TEXT NOT NULL,
                PRIMARY KEY(event_id,bird_id)
            );
            CREATE INDEX IF NOT EXISTS observation_species ON observations(scientific_name);
            CREATE INDEX IF NOT EXISTS event_time ON events(created_at);
        """)
        version = self._db.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()
        if version and int(version[0]) not in (1, 2, 3, SCHEMA_VERSION):
            self._db.close()
            raise ValueError("不支持的本地鸟种库版本")
        if version and int(version[0]) < SCHEMA_VERSION:
            # Keep the original schema1 recovery point, plus the state immediately
            # before display names are added. Never replace an earlier backup.
            targets = tuple(range(int(version[0]) + 1, SCHEMA_VERSION + 1))
            for target in targets:
                backup = self.db_path.with_name(self.db_path.stem + f".before_schema{target}.sqlite3")
                if backup.exists():
                    continue
                pending = backup.with_name(backup.name + "." + uuid.uuid4().hex + ".pending")
                destination = sqlite3.connect(str(pending))
                try:
                    self._db.backup(destination)
                    destination.close()
                    if not backup.exists():
                        pending.replace(backup)
                finally:
                    destination.close()
                    pending.unlink(missing_ok=True)
        # ALTERs and the version marker commit together. Photo annotations are
        # stored beside events, independently of the immutable model evidence.
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(events)")}
            for column in ("capture_place", "captured_at", "display_name", "notes"):
                if column not in columns:
                    self._db.execute(f"ALTER TABLE events ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            self._db.execute("""CREATE TABLE IF NOT EXISTS deleted_events (
                event_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL,
                source_name TEXT, source_sha256 TEXT)""")
            deleted_columns = {row[1] for row in self._db.execute("PRAGMA table_info(deleted_events)")}
            if "undo_token" not in deleted_columns:
                self._db.execute("ALTER TABLE deleted_events ADD COLUMN undo_token TEXT NOT NULL DEFAULT ''")
            self._db.execute("""CREATE TABLE IF NOT EXISTS delete_undo_batches (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, undone_at TEXT,
                event_count INTEGER NOT NULL, bird_count INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL)""")
            self._db.execute("INSERT OR REPLACE INTO library_meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        self.catalog = {}
        self.catalog_error = None
        self.reload_catalog()

    def reload_catalog(self):
        """Metadata may be installed after the database was first created."""
        path = self.app_root / "assets/species_catalog.json"
        catalog = {}
        try:
            if path.is_file():
                document = json.loads(path.read_text(encoding="utf-8-sig"))
                entries = document.get("species", []) if isinstance(document, dict) else document
                if not isinstance(entries, list):
                    raise ValueError("species必须是列表")
                for entry in entries:
                    if isinstance(entry, dict) and _name(entry.get("scientific_name")):
                        catalog[_name(entry["scientific_name"])] = entry
            self.catalog_error = None
        except (OSError, ValueError, TypeError) as exc:
            self.catalog_error = str(exc)
        self.catalog = catalog
        return len(catalog)

    def resolve_path(self, reference):
        """Resolve a stored app-relative path; refuse paths escaping the app."""
        if not reference:
            return None
        path = Path(str(reference))
        if path.is_absolute():
            # Public APIs should use relative refs, but accept an in-app Path
            # from a caller without making outside files part of the database.
            target = path.resolve()
        else:
            target = (self.app_root / path).resolve()
        return target if target.is_relative_to(self.app_root) else None

    def _reference(self, value, result_dir=None):
        if not value or not isinstance(value, (str, Path)):
            return None
        path = Path(value)
        target = path.resolve() if path.is_absolute() else (self.app_root / path).resolve()
        if target.is_relative_to(self.app_root):
            return target.relative_to(self.app_root).as_posix()
        # Results copied from another computer retain their old absolute paths.
        # Rebind only known result assets that actually exist beside this JSON.
        if result_dir and result_dir.is_relative_to(self.app_root):
            local = (result_dir / path.name).resolve()
            if local.is_file():
                return local.relative_to(self.app_root).as_posix()
            if path.name == result_dir.name:
                return result_dir.relative_to(self.app_root).as_posix()
        return None

    def _portable_payload(self, value, result_dir):
        if isinstance(value, list):
            return [self._portable_payload(item, result_dir) for item in value]
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                if key == "model_package":
                    continue
                if key in _PATH_KEYS:
                    output[key] = self._reference(item, result_dir)
                else:
                    output[key] = self._portable_payload(item, result_dir)
            return output
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    @staticmethod
    def _validate_row(row):
        warnings = []
        coords = row.get("xyxy")
        valid = isinstance(coords, (list, tuple)) and len(coords) == 4
        if valid:
            try:
                coords = [float(value) for value in coords]
                valid = all(math.isfinite(value) for value in coords) and coords[2] > coords[0] and coords[3] > coords[1]
            except (TypeError, ValueError, OverflowError):
                valid = False
        if not valid:
            warnings.append("鸟框坐标无效，保留记录但不计入具体鸟种")
        if _score(row.get("detection_confidence")) is None:
            warnings.append("检测分数无效或缺失")
        expert = row.get("specialist") or {}
        if isinstance(expert, dict) and expert and _score(expert.get("confidence")) is None:
            warnings.append("专项分类分数无效或缺失")
        if _score(row.get("original_confidence")) is None:
            warnings.append("原分类分数无效或缺失")
        row["valid_box"] = valid
        row["record_warnings"] = warnings
        return row

    @staticmethod
    def _prediction(row):
        """Count clear predictions only, without promoting uncertain candidates."""
        expert = row.get("specialist") if isinstance(row.get("specialist"), dict) else {}
        unknown = ("", "未确认", "保留候选，鸟种未确认", None)
        if (not row.get("valid_box", True) or row.get("gate_status") == "uncertain" or
                expert.get("rejected_as_OTHER") or expert.get("decision_kind") == "similar_non_willow"):
            return unknown
        is_willow = expert.get("is_willow", not expert.get("rejected_as_OTHER", True))
        if (row.get("gate_status") == "willow" and expert and is_willow and
                (expert.get("class_index") is not None or expert.get("global_id", -1) != -1) and
                _name(expert.get("scientific_name")) and expert.get("common_name") and
                _score(expert.get("confidence")) is not None):
            return (_name(expert.get("scientific_name")), _name(expert.get("common_name")),
                    expert.get("display_source", "专项复核预测"), _score(expert.get("confidence")))
        if (row.get("gate_status") in {"willow", "willow_outside_coverage", "not_willow"} and
                row.get("original_accepted") and _score(row.get("original_confidence")) is not None):
            return (_name(row.get("original_scientific_name")), _name(row.get("original_name")),
                    "原判保留" if expert else "原模型预测", _score(row.get("original_confidence")))
        return unknown

    @staticmethod
    def _created_at(payload, result_dir, source_file):
        for key in ("created_at", "recognized_at", "timestamp", "completed_at"):
            if payload.get(key):
                return str(payload[key])
        token = result_dir.name if result_dir else Path(str(payload.get("event_dir") or "")).name
        try:
            return datetime.strptime(token[:15], "%Y%m%d_%H%M%S").isoformat(timespec="seconds")
        except ValueError:
            return datetime.fromtimestamp(source_file.stat().st_mtime).isoformat(timespec="seconds") if source_file else datetime.now().isoformat(timespec="seconds")

    def ingest_result(self, result):
        """Atomically insert/update one completed recognition, once per event.

        ``result`` is either a result dict returned by the existing engine or a
        willow_result.json path. Re-importing or moving the app does not add
        records. Separate recognition runs remain separate events.
        """
        source_file = None
        if isinstance(result, (str, Path)):
            source_file = Path(result).resolve()
            payload = json.loads(source_file.read_text(encoding="utf-8-sig"))
        elif isinstance(result, dict):
            payload = deepcopy(result)
            candidate = payload.get("result_json")
            if candidate:
                candidate = self.resolve_path(candidate)
                if candidate and candidate.is_file():
                    source_file = candidate
        else:
            raise TypeError("需要识别结果字典或willow_result.json路径")
        if not isinstance(payload, dict) or not isinstance(payload.get("boxes"), list):
            raise ValueError("识别结果缺少逐鸟boxes列表")
        if payload.get("schema") not in (None, "willow-only-image-v1"):
            raise ValueError("不是本应用的逐鸟识别结果")
        payload.setdefault("schema", "willow-only-image-v1")
        if any(not isinstance(row, dict) for row in payload["boxes"]):
            raise ValueError("逐鸟记录格式错误")
        result_dir = source_file.parent if source_file else None
        if result_dir is None and payload.get("event_dir"):
            result_dir = self.resolve_path(payload["event_dir"])
        token = Path(str(payload.get("event_dir") or "")).name
        if not token and result_dir:
            token = result_dir.name
        portable = self._portable_payload(payload, result_dir)
        portable["source_name"] = Path(str(payload.get("source") or "")).name
        body = _json(portable)
        payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if token:
            identity = _json([payload.get("schema"), payload.get("source_sha256"), token])
        else:
            identity = body
        event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        with self._lock:
            if self._db.execute("SELECT 1 FROM deleted_events WHERE event_id=?", (event_id,)).fetchone():
                return {"event_id": event_id, "deleted": True, "created": False, "updated": False, "birds": 0}
        created_at = self._created_at(payload, result_dir, source_file)
        now = datetime.now().isoformat(timespec="seconds")
        observations = []
        identifiers = set()
        for index, row in enumerate(portable["boxes"]):
            row = self._validate_row(row)
            bird_id = _name(row.get("bird_id")) or f"bird_{index + 1:03d}"
            if bird_id in identifiers:
                raise ValueError("同一次识别出现重复bird_id，已拒绝写入")
            identifiers.add(bird_id)
            sci, common, provenance, confidence = self._prediction(row)
            expert = row.get("specialist") if isinstance(row.get("specialist"), dict) else {}
            observations.append((event_id, bird_id, index, sci, common, provenance, confidence,
                _score(row.get("detection_confidence")), row.get("gate_status"),
                row.get("original_scientific_name"), row.get("original_name"),
                _score(row.get("original_confidence")), int(bool(row.get("original_accepted"))),
                expert.get("scientific_name"), expert.get("common_name"), _score(expert.get("confidence")),
                int(bool(expert.get("rejected_as_OTHER"))) if expert else None,
                row.get("crop_path"), row.get("tight_crop_path"), _json(row)))
        with self._lock, self._db:
            # A GUI delete can run after the initial check but before this write.
            if self._db.execute("SELECT 1 FROM deleted_events WHERE event_id=?", (event_id,)).fetchone():
                return {"event_id": event_id, "deleted": True, "created": False, "updated": False, "birds": 0}
            existing = self._db.execute("SELECT payload_sha256 FROM events WHERE event_id=?", (event_id,)).fetchone()
            if existing and existing[0] == payload_hash:
                return {"event_id": event_id, "created": False, "updated": False, "birds": len(observations)}
            self._db.execute("""
                INSERT INTO events(event_id,event_key,source_sha256,source_name,source_ref,
                    result_ref,snapshot_ref,annotated_ref,report_ref,status,message,detection_mode,
                    device,created_at,imported_at,updated_at,payload_sha256,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET
                source_sha256=excluded.source_sha256,source_name=excluded.source_name,source_ref=excluded.source_ref,
                result_ref=excluded.result_ref,snapshot_ref=excluded.snapshot_ref,annotated_ref=excluded.annotated_ref,
                report_ref=excluded.report_ref,status=excluded.status,message=excluded.message,
                detection_mode=excluded.detection_mode,device=excluded.device,created_at=excluded.created_at,
                updated_at=excluded.updated_at,payload_sha256=excluded.payload_sha256,payload_json=excluded.payload_json
            """, (event_id, identity, payload.get("source_sha256"), portable["source_name"], portable.get("source"),
                self._reference(source_file, result_dir) if source_file else portable.get("result_json"),
                portable.get("snapshot_path"), portable.get("annotated_path"), portable.get("report_path"),
                payload.get("status"), payload.get("message"), payload.get("detection_mode"), payload.get("device"),
                created_at, now, now, payload_hash, body))
            source_hash = payload.get("source_sha256")
            if not existing and isinstance(source_hash, str) and source_hash.strip():
                # A new recognition of the same photo inherits its saved notes.
                # The INSERT has already acquired SQLite's write lock, so this
                # read/update commits atomically with the new event.
                photo_notes = self._db.execute("""SELECT capture_place,captured_at,display_name,notes FROM events
                    WHERE source_sha256=? AND event_id<>?
                    ORDER BY updated_at DESC,created_at DESC,event_id LIMIT 1""", (source_hash, event_id)).fetchone()
                if photo_notes is not None:
                    self._db.execute("UPDATE events SET capture_place=?,captured_at=?,display_name=?,notes=? WHERE event_id=?",
                                     (photo_notes["capture_place"], photo_notes["captured_at"], photo_notes["display_name"], photo_notes["notes"], event_id))
            self._db.execute("DELETE FROM observations WHERE event_id=?", (event_id,))
            self._db.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", observations)
        return {"event_id": event_id, "created": not bool(existing), "updated": bool(existing), "birds": len(observations)}

    def import_results(self, result_root=None):
        root = Path(result_root).resolve() if result_root else self.app_root / "results"
        report = {"files": 0, "created": 0, "updated": 0, "unchanged": 0, "deleted": 0, "errors": []}
        if not root.exists():
            return report
        paths = [root] if root.is_file() else sorted(root.rglob("willow_result.json"))
        for path in paths:
            report["files"] += 1
            try:
                result = self.ingest_result(path)
                key = "deleted" if result.get("deleted") else "created" if result["created"] else "updated" if result["updated"] else "unchanged"
                report[key] += 1
            except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
                report["errors"].append({"file": self._reference(path) or path.name, "error": str(exc)})
        return report

    def _observation(self, row):
        item = json.loads(row["row_json"])
        item.update({key: row[key] for key in ("event_id", "bird_id", "scientific_name", "common_name",
            "prediction_source", "classification_confidence", "detection_confidence", "gate_status")})
        item["crop_path"], item["tight_crop_path"] = row["crop_ref"], row["tight_crop_ref"]
        item["created_at"] = row["created_at"] if "created_at" in row.keys() else None
        if "source_name" in row.keys():
            item["source_name"] = row["source_name"]
        if "snapshot_ref" in row.keys():
            item["snapshot_path"] = row["snapshot_ref"]
        for key in ("capture_place", "captured_at", "display_name", "notes"):
            item[key] = row[key] if key in row.keys() else ""
        item["count_label"] = COUNT_LABEL
        return item

    def species_cards(self, query=""):
        return self._species_cards(query=query)

    def card_counts(self):
        """The banner counts identified observations, including species outside the catalog."""
        with self._lock:
            rows = self._db.execute("SELECT scientific_name, COUNT(*) FROM observations "
                                    "WHERE scientific_name<>'' GROUP BY scientific_name")
            total, extra = 0, 0
            for name, count in rows:
                total += count
                extra += name not in self.catalog
            return len(self.catalog) + extra, total

    def _species_cards(self, query="", scientific_name=None):
        """Build detached cards; a detail lookup touches only its target species.

        No persistent cache is needed: edits, delete/undo and writes from a
        second connection remain immediately visible through the normal SQL.
        """
        needle = str(query).strip().casefold() if query else ""
        where = "o.scientific_name<>''"
        params = ()
        if scientific_name is not None:
            where += " AND o.scientific_name=?"
            params = (scientific_name,)
        with self._lock:
            rows = self._db.execute("""SELECT o.scientific_name,MAX(o.common_name) AS common_name,
                COUNT(*) AS observation_count,COUNT(DISTINCT o.event_id) AS recognition_count,
                COUNT(DISTINCT CASE WHEN e.source_sha256 IS NOT NULL AND e.source_sha256<>''
                    THEN e.source_sha256 ELSE e.event_id END) AS image_count,
                MAX(e.created_at) AS latest_seen FROM observations o JOIN events e USING(event_id)
                WHERE """ + where + " GROUP BY o.scientific_name", params).fetchall()
            counts = {row["scientific_name"]: dict(row) for row in rows}
            catalog_names = set(self.catalog) if scientific_name is None else (
                {scientific_name} if scientific_name in self.catalog else set())
            keys = catalog_names | set(counts)
            cards = []
            for name in keys:
                card = deepcopy(self.catalog.get(name) or {"scientific_name": name})
                aggregate = counts.get(name, {})
                card.setdefault("common_name", aggregate.get("common_name") or name)
                card.update(observation_count=aggregate.get("observation_count", 0),
                    image_count=aggregate.get("image_count", 0), latest_seen=aggregate.get("latest_seen"),
                    recognition_count=aggregate.get("recognition_count", 0),
                    count_label=COUNT_LABEL)
                latest = self._db.execute("""SELECT o.crop_ref,e.snapshot_ref FROM observations o
                    JOIN events e USING(event_id) WHERE o.scientific_name=?
                    ORDER BY e.created_at DESC,o.ordinal LIMIT 1""", (name,)).fetchone() if aggregate else None
                card["representative_image"] = (latest["crop_ref"] or latest["snapshot_ref"]) if latest else card.get("image_path")
                annotations = self._db.execute("""SELECT DISTINCT e.capture_place,e.captured_at
                    FROM observations o JOIN events e USING(event_id) WHERE o.scientific_name=?""", (name,)).fetchall() if aggregate else ()
                card["capture_places"] = sorted({item["capture_place"] for item in annotations if item["capture_place"]})
                card["latest_captured_at"] = max((item["captured_at"] for item in annotations if item["captured_at"]), default="")
                # Empty searches are the normal open/refresh path. Serializing
                # every source/recording/reference field here was wasted work.
                if not needle or needle in _json(card).casefold():
                    cards.append(card)
        return sorted(cards, key=lambda card: (-card["observation_count"], str(card.get("common_name") or ""), card["scientific_name"]))

    def has_species(self, scientific_name):
        name = _name(scientific_name)
        if not name:
            return False
        with self._lock:
            return name in self.catalog or self._db.execute(
                "SELECT 1 FROM observations WHERE scientific_name=? LIMIT 1", (name,)
            ).fetchone() is not None

    def species_detail(self, scientific_name):
        name = _name(scientific_name)
        with self._lock:
            cards = self._species_cards(scientific_name=name)
            if not cards:
                return None
            card = cards[0]
            rows = self._db.execute("""SELECT o.*,e.created_at,e.source_name,e.snapshot_ref,e.capture_place,e.captured_at,e.display_name,e.notes
                FROM observations o JOIN events e USING(event_id) WHERE o.scientific_name=?
                ORDER BY e.created_at DESC,o.ordinal""", (name,)).fetchall()
        card["observations"] = [self._observation(row) for row in rows]
        return card

    def events(self, query="", species=None):
        where, params = [], []
        if species:
            where.append("EXISTS(SELECT 1 FROM observations o WHERE o.event_id=e.event_id AND o.scientific_name=?)")
            params.append(str(species))
        if query:
            where.append("(e.source_name LIKE ? OR e.display_name LIKE ? OR e.message LIKE ? OR e.capture_place LIKE ? OR e.captured_at LIKE ? OR e.notes LIKE ? OR EXISTS(SELECT 1 FROM observations o WHERE o.event_id=e.event_id AND (o.scientific_name LIKE ? OR o.common_name LIKE ?)))")
            needle = "%" + str(query) + "%"
            params.extend([needle] * 8)
        columns = ",".join("e." + column for column in _EVENT_SUMMARY_COLUMNS)
        sql = "SELECT " + columns + ", (SELECT COUNT(*) FROM observations o WHERE o.event_id=e.event_id) AS bird_count FROM events e"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY e.created_at DESC,e.event_id", params).fetchall()
        return [self._event_summary(row) for row in rows]

    @staticmethod
    def _event_summary(row):
        item = dict(row)
        item.pop("payload_json", None)
        item.pop("event_key", None)
        item.update(id=row["event_id"], source=row["source_ref"], snapshot_path=row["snapshot_ref"],
            annotated_path=row["annotated_ref"], report_path=row["report_ref"], result_json=row["result_ref"],
            count_label=COUNT_LABEL)
        return item

    def event_detail(self, event_id):
        with self._lock:
            row = self._db.execute("SELECT e.*, (SELECT COUNT(*) FROM observations o WHERE o.event_id=e.event_id) AS bird_count FROM events e WHERE e.event_id=?", (str(event_id),)).fetchone()
            if row is None:
                return None
            rows = self._db.execute("SELECT o.*,e.created_at,e.source_name,e.snapshot_ref,e.capture_place,e.captured_at,e.display_name,e.notes FROM observations o JOIN events e USING(event_id) WHERE o.event_id=? ORDER BY o.ordinal", (str(event_id),)).fetchall()
        item = self._event_summary(row)
        item["boxes"] = [self._observation(bird) for bird in rows]
        item["raw_result"] = json.loads(row["payload_json"])
        return item

    @staticmethod
    def _capture_time(value):
        text = str(value or "").strip()
        if not text:
            return ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?", text):
            raise ValueError("拍摄时间请填写 YYYY-MM-DD 或 YYYY-MM-DD HH:MM[:SS]；不确定可以留空。")
        text = text.replace("T", " ")
        fmt = {10: "%Y-%m-%d", 16: "%Y-%m-%d %H:%M", 19: "%Y-%m-%d %H:%M:%S"}[len(text)]
        try:
            datetime.strptime(text, fmt)
        except ValueError as exc:
            raise ValueError("拍摄日期或时间无效，请检查年月日和时分秒。") from exc
        return text

    @staticmethod
    def _photo_name(value):
        text = str(value or "")
        if any(character in text for character in ("\x00", "\n", "\r")) or len(text.strip()) > 120:
            raise ValueError("照片名称请使用120字以内的单行文字。")
        return text.strip()

    @staticmethod
    def _photo_notes(value):
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        if "\x00" in text or len(text) > 10000:
            raise ValueError("备注请限制在10000字以内，且不要包含空字符。")
        return text

    def _update_photo_fields(self, event_id, fields):
        """Commit validated, user-owned fields without touching model evidence."""
        if not fields or set(fields) - {"capture_place", "captured_at", "display_name", "notes"}:
            raise ValueError("未知照片信息字段。")
        key = str(event_id)
        with self._lock, self._db:
            event = self._db.execute("SELECT source_sha256 FROM events WHERE event_id=?", (key,)).fetchone()
            if event is None:
                raise KeyError("这条档案不存在或已经删除。")
            source_hash = event["source_sha256"]
            match = "source_sha256" if isinstance(source_hash, str) and source_hash.strip() else "event_id"
            value = source_hash if match == "source_sha256" else key
            assignments = ",".join(column + "=?" for column in fields)
            self._db.execute(f"UPDATE events SET {assignments},updated_at=? WHERE {match}=?",
                (*fields.values(), datetime.now().isoformat(timespec="seconds"), value))
        return self.event_detail(key)

    def update_photo_name(self, event_id, display_name=""):
        """Set a shared display label; source filenames and files stay immutable."""
        return self._update_photo_fields(event_id, {"display_name": self._photo_name(display_name)})

    def update_event_metadata(self, event_id, capture_place="", captured_at="", display_name=None, notes=None):
        """Store user-entered photo metadata, separately from model evidence.

        All active recognition runs sharing a nonempty photo SHA share these
        fields, including a cleared annotation. New runs inherit them. Missing
        or empty hashes remain event-specific. Re-import never overwrites them.
        A None display_name preserves the current label for older callers; an
        explicit empty string clears it. All supplied fields are validated
        before the single database transaction, so invalid edits never partly save.
        Notes are multiline, independent of the date; None preserves them and
        an explicit empty string clears them for this photo's active runs.
        """
        place = str(capture_place or "").strip()
        if len(place) > 500 or "\x00" in place:
            raise ValueError("拍摄地点请限制在500字以内。")
        captured = self._capture_time(captured_at)
        fields = {"capture_place": place, "captured_at": captured}
        if display_name is not None:
            fields["display_name"] = self._photo_name(display_name)
        if notes is not None:
            fields["notes"] = self._photo_notes(notes)
        return self._update_photo_fields(event_id, fields)

    def delete_events(self, event_ids):
        """Atomically archive a deletion snapshot, then remove selected records.

        Only database records are removed. Source photos/results stay intact,
        and tombstones suppress automatic imports until this deletion is undone.
        Unknown/duplicate IDs are harmless; unrelated old deletions stay deleted.
        """
        if event_ids is None or isinstance(event_ids, (str, bytes)):
            raise TypeError("批量删除需要档案编号列表。")
        keys = list(dict.fromkeys(_name(value) for value in event_ids if _name(value)))
        empty = {"deleted": False, "event_ids": [], "birds_removed": 0, "undo_token": None}
        if not keys:
            return empty
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            snapshot = []
            for key in keys:
                event = self._db.execute("SELECT * FROM events WHERE event_id=?", (key,)).fetchone()
                if event is None:
                    continue
                if self._db.execute("SELECT 1 FROM deleted_events WHERE event_id=?", (key,)).fetchone():
                    raise ValueError("档案与删除状态发生冲突，未删除任何记录。")
                rows = self._db.execute("SELECT * FROM observations WHERE event_id=? ORDER BY ordinal", (key,)).fetchall()
                snapshot.append({"event": dict(event), "observations": [dict(row) for row in rows]})
            if not snapshot:
                return empty
            token = uuid.uuid4().hex
            now = datetime.now().isoformat(timespec="seconds")
            birds = sum(len(item["observations"]) for item in snapshot)
            self._db.execute("""INSERT INTO delete_undo_batches
                (token,created_at,event_count,bird_count,snapshot_json) VALUES(?,?,?,?,?)""",
                (token, now, len(snapshot), birds, _json(snapshot)))
            for item in snapshot:
                event = item["event"]
                self._db.execute("""INSERT INTO deleted_events
                    (event_id,deleted_at,source_name,source_sha256,undo_token) VALUES(?,?,?,?,?)""",
                    (event["event_id"], now, event["source_name"], event["source_sha256"], token))
                self._db.execute("DELETE FROM events WHERE event_id=?", (event["event_id"],))
        return {"deleted": True, "event_ids": [item["event"]["event_id"] for item in snapshot],
                "birds_removed": birds, "undo_token": token}

    def delete_event(self, event_id):
        """Compatibility wrapper for one selected archive record."""
        result = self.delete_events([event_id])
        return {**result, "event_id": str(event_id)}

    def undo_delete(self, token=None):
        """Restore the latest pending batch without overwriting active records.

        Snapshots and ordering survive restart. A stale/colliding batch fails as
        a whole. Current annotations of an active sibling photo take precedence
        over an older snapshot, so undo cannot erase a newer user edit.
        """
        empty = {"restored": False, "event_ids": [], "birds_restored": 0, "undo_token": token}
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if token is None:
                batch = self._db.execute("SELECT * FROM delete_undo_batches WHERE undone_at IS NULL ORDER BY sequence DESC LIMIT 1").fetchone()
            else:
                batch = self._db.execute("SELECT * FROM delete_undo_batches WHERE token=? AND undone_at IS NULL", (str(token),)).fetchone()
            if batch is None:
                return empty
            snapshot = json.loads(batch["snapshot_json"])
            if not isinstance(snapshot, list) or not snapshot:
                raise ValueError("撤回快照不完整，未修改档案。")
            event_columns = [row[1] for row in self._db.execute("PRAGMA table_info(events)")]
            bird_columns = [row[1] for row in self._db.execute("PRAGMA table_info(observations)")]
            siblings = {}
            for item in snapshot:
                event = item["event"]
                key = event["event_id"]
                tombstone = self._db.execute("SELECT undo_token FROM deleted_events WHERE event_id=?", (key,)).fetchone()
                collision = self._db.execute("SELECT 1 FROM events WHERE event_id=? OR event_key=?", (key, event["event_key"])).fetchone()
                if collision or tombstone is None or tombstone["undo_token"] != batch["token"]:
                    raise ValueError("部分记录在删除后已发生变化，无法安全撤回；现有记录未被覆盖。")
                if set(event) != set(event_columns) or any(set(row) != set(bird_columns) or row["event_id"] != key for row in item["observations"]):
                    raise ValueError("撤回快照格式不兼容，未修改档案。")
                source_hash = event.get("source_sha256")
                if isinstance(source_hash, str) and source_hash.strip() and source_hash not in siblings:
                    row = self._db.execute("""SELECT capture_place,captured_at,display_name,notes FROM events
                        WHERE source_sha256=? ORDER BY updated_at DESC,created_at DESC,event_id LIMIT 1""", (source_hash,)).fetchone()
                    siblings[source_hash] = dict(row) if row else None
            event_sql = "INSERT INTO events(" + ",".join(event_columns) + ") VALUES(" + ",".join("?" for _ in event_columns) + ")"
            bird_sql = "INSERT INTO observations(" + ",".join(bird_columns) + ") VALUES(" + ",".join("?" for _ in bird_columns) + ")"
            reconciled = 0
            for item in snapshot:
                event = dict(item["event"])
                current_photo = siblings.get(event.get("source_sha256"))
                if current_photo is not None:
                    if any(event.get(key) != value for key, value in current_photo.items()):
                        event.update(current_photo)
                        event["updated_at"] = datetime.now().isoformat(timespec="seconds")
                        reconciled += 1
                self._db.execute(event_sql, [event[column] for column in event_columns])
                self._db.executemany(bird_sql, [[row[column] for column in bird_columns] for row in item["observations"]])
                self._db.execute("DELETE FROM deleted_events WHERE event_id=? AND undo_token=?", (event["event_id"], batch["token"]))
            self._db.execute("UPDATE delete_undo_batches SET undone_at=? WHERE token=?", (datetime.now().isoformat(timespec="seconds"), batch["token"]))
        return {"restored": True, "event_ids": [item["event"]["event_id"] for item in snapshot],
                "birds_restored": sum(len(item["observations"]) for item in snapshot),
                "undo_token": batch["token"], "photo_annotations_reconciled": reconciled}

    def stats(self):
        with self._lock:
            events = self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            birds = self._db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            species = self._db.execute("SELECT COUNT(DISTINCT scientific_name) FROM observations WHERE scientific_name<>''").fetchone()[0]
            identified = self._db.execute("SELECT COUNT(*) FROM observations WHERE scientific_name<>''").fetchone()[0]
            images = self._db.execute("SELECT COUNT(DISTINCT CASE WHEN source_sha256<>'' THEN source_sha256 ELSE event_id END) FROM events").fetchone()[0]
        return {"event_count": events, "observation_count": birds, "species_count": species,
                "identified_observation_count": identified, "unidentified_observation_count": birds - identified,
                "catalogue_species_count": len(self.catalog), "distinct_image_count": images,
                "count_label": COUNT_LABEL, "catalog_error": self.catalog_error}

    def close(self):
        with self._lock:
            if self._db is not None:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._db.close()
                self._db = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
