"""Willow-only routing around the unchanged fourth detector and dual BioCLIP.

The group router is an abstaining engineering rule, not a newly trained binary
classifier. The original recognition and the local 58-class review stay separate.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import html
import json
import time

import numpy as np
from PIL import ImageDraw, ImageFont

APP_ROOT = Path(__file__).resolve().parents[1]
NEGATIVE_MESSAGE = "根本没有这种柳莺"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_gate(package_root):
    policy = read(APP_ROOT / "config/gate.json")
    if policy["schema"] != "willow-group-gate-v1":
        raise ValueError("未知柳莺门控配置")
    label_path = Path(package_root) / "configs/china_labels.json"
    if sha(label_path) != policy["labels_sha256"]:
        raise ValueError("模型包鸟种索引与柳莺门控不一致，已停止识别")
    canonical_ids = [i for i, label in enumerate(read(label_path))
                     if label["scientific_name"].split()[0] == "Phylloscopus"]
    if (len(set(policy["broad_willow_global_ids"])) != 50 or
            policy["six_target_global_ids"] != [70, 126, 198, 391, 473, 619] or
            policy["broad_willow_global_ids"] != canonical_ids or
            not set(policy["six_target_global_ids"]).issubset(policy["broad_willow_global_ids"]) or
            policy["positive_group_mass"] != .5 or policy["negative_group_mass"] != .1):
        raise ValueError("冻结的柳莺组/门槛发生变化")
    return policy


def route_group(probability, accepted, policy):
    """Use the full original vocabulary; rejected species != non-willow."""
    p = np.asarray(probability, np.float64)
    if (p.shape != (1343,) or not np.isfinite(p).all() or
            (p < 0).any() or not np.isclose(p.sum(), 1., atol=1e-8, rtol=0)):
        raise ValueError("组门控需要完整的原1343种概率")
    ids = policy["broad_willow_global_ids"]
    broad = set(ids)
    top = np.argsort(-p, kind="stable")[:5]
    mass = float(p[ids].sum())
    details = {"group_probability_mass": mass, "original_top1_global_id": int(top[0]),
               "original_top5_global_ids": top.tolist(), "original_accepted": bool(accepted),
               "group_score_is_not_calibrated_binary_probability": True}
    if int(top[0]) in broad and mass >= policy["positive_group_mass"]:
        outside = int(top[0]) not in policy["six_target_global_ids"]
        return {**details, "gate_status": "willow_outside_coverage" if outside else "willow",
                "gate_message": "柳莺候选，原判不在专项六种内；专项结果仅供参考。" if outside else
                                "柳莺候选：进入六种专项复核。"}
    if (int(top[0]) not in broad and accepted and
            not any(int(i) in broad for i in top) and mass <= policy["negative_group_mass"]):
        return {**details, "gate_status": "not_willow", "gate_message": NEGATIVE_MESSAGE}
    return {**details, "gate_status": "uncertain", "gate_message": "无法确认是不是柳莺，已跳过专项复核。"}


def summarize(boxes):
    if not boxes:
        return "no_bird", "没有检出可判断的鸟，无法确认是否有柳莺。"
    positive = [b for b in boxes if b["gate_status"] in ("willow", "willow_outside_coverage")]
    if positive:
        names = []
        for box in positive:
            expert = box.get("specialist") or {}
            if (box["gate_status"] == "willow" and not expert.get("rejected_as_OTHER", True)
                    and expert.get("common_name")):
                names.append(expert["common_name"])
        text = "、".join(dict.fromkeys(names))
        count = len(positive)
        message = f"发现 {count} 个柳莺候选" + (f"；专项预测：{text}。" if text else "，具体种类未确认。")
        return "willow", message
    if all(b["gate_status"] == "not_willow" for b in boxes):
        return "not_willow", NEGATIVE_MESSAGE
    return "uncertain", "无法确认是否为柳莺；证据不足的鸟已跳过专项复核。"


class WillowOnlyEngine:
    def __init__(self, package_root, device="auto", progress=None, config=None):
        self.package_root = Path(package_root).resolve()
        self.progress = progress or (lambda message: None)
        self.policy = load_gate(self.package_root)
        self.labels = read(self.package_root / "configs/china_labels.json")
        self.head = None
        self.species_fusion = None
        self.species_fusion_loaded = False
        self.head_calls = self.reviewed_rows = 0
        self.closed = False
        # Heavy dependencies/models are not imported by module or GUI startup.
        from engine import BirdRecognizer
        from desktop_review.backend import CaptureMixin
        class CapturedRecognizer(CaptureMixin, BirdRecognizer):
            pass
        self.recognizer = CapturedRecognizer(self.package_root, device=device,
                                             mode="selected", progress=self.progress)

    def _review(self, rows, features):
        selected = [i for i, row in enumerate(rows)
                    if row["gate_status"] in ("willow", "willow_outside_coverage")]
        if not selected:
            return {"status": "skipped", "selected_rows": [], "head_called": False}
        if self.recognizer.device != "cuda" or self.recognizer.numeric_mode != "bf16":
            for i in selected:
                rows[i]["gate_message"] += " 专项仅验证过NVIDIA CUDA BF16；当前设备未运行专项。"
            return {"status": "unsupported_device", "selected_rows": selected, "head_called": False}
        self.progress(f"已找到 {len(selected)} 个柳莺候选，正在运行50种柳莺专项复核…")
        from .specialist import Willow50Head
        if self.head is None:
            self.head = Willow50Head(self.package_root)
        self.head.verify_runtime(self.recognizer)
        eligible = []
        for i in selected:
            rows[i]["specialist_coverage"] = {"willow_species": 50, "other_species": 8}
            if rows[i].get("original_scientific_name") not in self.head.class_keys:
                rows[i].update(gate_status="willow_outside_coverage",
                    gate_message="柳莺候选不在本批50种专项的训练范围，保留原判并跳过复核。")
            else:
                rows[i].update(gate_status="willow", gate_message="柳莺候选：进入50种柳莺＋8种相似组外鸟复核。")
                eligible.append(i)
        selected = eligible
        if not selected:
            return {"status": "outside_coverage", "selected_rows": [], "head_called": False,
                    "binding": self.head.binding}
        self.head_calls += 1
        predict = getattr(self.head, "predict_refined", self.head.predict)
        selected_features = {key: value[selected] for key, value in features.items()}
        prediction = predict(selected_features)
        if not self.species_fusion_loaded:
            from .species_fusion import load_active
            self.species_fusion = load_active(APP_ROOT, self.head)
            self.species_fusion_loaded = True
        if self.species_fusion is not None:
            self.progress("正在合并专项、Tip和GDA的鸟种证据…")
            fusion = self.species_fusion.predict(
                selected_features, prediction["probabilities"], self.head.class_keys)
            prediction = {**prediction, **fusion}
        self.reviewed_rows += len(selected)
        classes = self.head.manifest["classes"]
        willow_columns = [k for k, item in enumerate(classes) if item["is_willow"]]
        for j, i in enumerate(selected):
            probabilities = prediction["probabilities"][j]
            index = int(prediction["predicted_index"][j])
            species = classes[index]
            ranking = np.argsort(-probabilities, kind="stable")[:3]
            expert = {"global_id": species["global_id"], "class_index": index,
                      "common_name": species["common_name"], "scientific_name": species["scientific_name"],
                      "confidence": float(probabilities[index]),
                      "target_probability_mass": float(probabilities[willow_columns].sum()),
                      "rejected_as_OTHER": not species["is_willow"],
                      "is_willow": species["is_willow"],
                      "decision_kind": "willow_species" if species["is_willow"] else "similar_non_willow",
                      "full58_probabilities": probabilities.tolist(), "class_order": self.head.class_keys,
                      "top3": [{**classes[k], "confidence": float(probabilities[k])} for k in ranking],
                      "threshold": 0., "confidence_scope": "58个已训练鸟种的模型分数，不是正确率",
                      "diagnostic_only": True, "applied_to_original": False,
                      **self.head.binding}
            if "base_probabilities" in prediction:
                base_probabilities = prediction["base_probabilities"][j]
                base_index = int(base_probabilities.argmax())
                expert["before_group_review"] = {"scientific_name": classes[base_index]["scientific_name"],
                    "common_name": classes[base_index]["common_name"], "confidence": float(base_probabilities[base_index]),
                    "full58_probabilities": base_probabilities.tolist()}
                expert["group_review"] = {name: {"triggered": bool(value["trigger"][j]),
                    "fallback": bool(value["fallback"][j]), "class_keys": value["class_keys"],
                    "conditional_scores": value["group_probabilities"][j].tolist(),
                    "feature_mode": value["feature_mode"], "neighbors": value["neighbors"]}
                    for name, value in prediction["group_diagnostics"].items()}
                expert["confidence_scope"] = "58种模型分数；触发相似组时为作者去重近邻重分配，分数不是正确率"
            if "fusion_binding" in prediction:
                applied = bool(prediction["fusion_applied"][j])
                previous = prediction["before_fusion_probabilities"][j]
                previous_index = int(previous.argmax())
                expert["species_fusion"] = {**prediction["fusion_binding"], "applied": applied,
                    "status": "applied" if applied else "kept_unmapped_species"}
                expert["before_species_fusion"] = {"scientific_name": classes[previous_index]["scientific_name"],
                    "common_name": classes[previous_index]["common_name"], "confidence": float(previous[previous_index]),
                    "full58_probabilities": previous.tolist()}
                if applied:
                    expert["confidence_scope"] = "57种物种概率融合分数，不是识别正确率"
                    expert["display_source"] = "物种概率融合复核"
            rows[i]["specialist"] = expert
            if not species["is_willow"]:
                rows[i]["gate_message"] += " 复核倾向相似组外鸟：" + species["common_name"] + "；原判保留。"
        return {"status": "reviewed", "selected_rows": selected, "head_called": True,
                "binding": self.head.binding}

    def recognize(self, source_path, output_root, detection_mode="normal"):
        if self.closed:
            raise RuntimeError("识别器已经关闭")
        from engine import read_image, save_result
        from desktop_review.willow6 import rebuild_main
        from desktop_review.backend import image_sha
        source = Path(source_path).resolve()
        source_hash = sha(source)
        started = time.perf_counter()
        image = read_image(source)
        result = self.recognizer.predict(image, detection_mode=detection_mode)
        # save_result uses the unchanged original per-bird crop verification.
        original = save_result(image, result, str(source), output_root)
        original_hash = sha(original["result_json"])
        rows = []
        for box in original["boxes"]:
            info = box["species_info"]
            rows.append({"bird_id": box["bird_id"], "xyxy": deepcopy(box["xyxy"]),
                         "detection_confidence": float(box["confidence"]),
                         "feature_index": int(info["feature_index"]),
                         "crop_path": box["crop_path"], "crop_sha256": box["crop_sha256"],
                         "tight_crop_path": box["tight_crop_path"],
                         "original_name": info["common_name"], "original_scientific_name": info["name"],
                         "original_confidence": info["confidence"], "original_accepted": bool(info["accepted"]),
                         "original_top5": deepcopy(info["top5"]), "specialist": None,
                         "gate_status": "uncertain", "gate_message": "无法确认，专项未运行。"})
        proof, review = {}, {"status": "no_birds", "selected_rows": [], "head_called": False}
        calls_before = self.head_calls
        if rows:
            try:
                probabilities, features, proof = rebuild_main(result, self.recognizer)
                if len(probabilities) != len(rows):
                    raise ValueError("逐鸟概率行数与鸟框不一致")
                for i, row in enumerate(rows):
                    if image_sha(result["_crops"][row["feature_index"]]) != row["crop_sha256"]:
                        raise ValueError("逐鸟裁图与特征索引不一致")
                    row.update(route_group(probabilities[i], row["original_accepted"], self.policy))
                review = self._review(rows, features)
            except Exception as exc:
                # No partially filled expert output or false categorical negative.
                for row in rows:
                    row.update(gate_status="uncertain", gate_message="无法确认：门控或专项不可用，原判和裁图已保留。", specialist=None)
                review = {"status": "unavailable", "error": str(exc), "selected_rows": [],
                          "head_called": self.head_calls > calls_before}
        status, message = summarize(rows)
        folder = Path(original["event_dir"])
        annotated_path = folder / "willow_annotated.png"
        annotate(image, rows).save(annotated_path)
        if sha(source) != source_hash or sha(original["result_json"]) != original_hash:
            raise ValueError("原图或原网络输出发生意外变化")
        public = {"schema": "willow-only-image-v1", "status": status, "message": message,
                  "source": str(source), "source_sha256": source_hash, "event_dir": str(folder),
                  "annotated_path": str(annotated_path), "snapshot_path": original["snapshot"],
                  "report_path": str(folder / "willow_report.html"),
                  "result_json": str(folder / "willow_result.json"), "boxes": rows,
                  "original_result_path": original["result_json"], "original_result_sha256": original_hash,
                  "original_annotated_path": original["annotated_path"],
                  "main_parity": proof, "specialist_review": review,
                  "gate_policy": deepcopy(self.policy), "gate_independent_accuracy_not_measured": True,
                  "original_weights_and_outputs_unchanged": True, "detection_mode": detection_mode,
                  "device": self.recognizer.device, "numeric_mode": self.recognizer.numeric_mode,
                  "total_ms": (time.perf_counter() - started) * 1000,
                  "model_package": str(self.package_root)}
        Path(public["result_json"]).write_text(json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        write_report(public)
        return public

    def close(self):
        if not self.closed:
            self.recognizer.close()
            self.head = None
            self.closed = True


def annotate(image, rows):
    output = image.copy()
    draw = ImageDraw.Draw(output)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    size = max(15, min(30, min(image.size) // 28))
    font = ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default()
    colors = {"willow": "#16866b", "willow_outside_coverage": "#26639b",
              "uncertain": "#bd810c", "not_willow": "#64748b"}
    for row in rows:
        status = row["gate_status"]
        expert = row.get("specialist") or {}
        if status == "willow" and expert.get("common_name") and not expert.get("rejected_as_OTHER"):
            label = ("融合：" if (expert.get("species_fusion") or {}).get("applied") else "专项：") + expert["common_name"]
        elif status in ("willow", "willow_outside_coverage"):
            label = ("复核倾向组外：" + expert["common_name"]) if expert.get("decision_kind") == "similar_non_willow" else "柳莺候选 / 种类未确认"
        elif status == "not_willow":
            label = "非柳莺：" + row["original_name"]
        else:
            label = "无法确认：" + row["original_name"]
        text = row["bird_id"] + " " + label
        x1, y1, x2, y2 = row["xyxy"]
        color = colors.get(status, "#bd810c")
        draw.rectangle((x1, y1, x2, y2), outline=color, width=max(2, min(image.size) // 250))
        bb = draw.textbbox((0, 0), text, font=font)
        width, height = bb[2]-bb[0], bb[3]-bb[1]
        tx, ty = max(0, min(x1, image.width-width-8)), max(0, y1-height-8)
        draw.rectangle((tx, ty, tx+width+8, ty+height+8), fill=color)
        draw.text((tx+4, ty+4-bb[1]), text, font=font, fill="white")
    return output


def write_report(result):
    esc = lambda value: html.escape(str(value))
    rows = []
    for box in result["boxes"]:
        expert = box.get("specialist") or {}
        prediction = expert.get("common_name") or ("组外或无法确认" if expert else "未运行")
        alternatives = "".join("<li>" + esc(p["common_name"]) + "：" + esc(round(p["confidence"], 4)) + "</li>"
                               for p in expert.get("top3", []))
        rows.append("<article><h2>" + esc(box["bird_id"]) + "</h2><img src=\"" + esc(Path(box["crop_path"]).name) +
                    "\"><p>" + esc(box["gate_message"]) + "</p><p>原网络：" + esc(box["original_name"]) +
                    "；专项诊断：" + esc(prediction) + "</p><p>检测置信度：" + esc(round(box["detection_confidence"], 4)) +
                    "；坐标：" + esc(box["xyxy"]) + "</p>" + ("<ol>" + alternatives + "</ol>" if alternatives else "") + "</article>")
    document = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>柳莺识别结果</title>'
                '<style>body{font:16px sans-serif;max-width:1000px;margin:32px auto;line-height:1.6}img{max-width:100%;max-height:500px}article{border-top:1px solid #ddd;padding:18px 0}article img{max-height:220px}</style>'
                '<h1>' + esc(result["message"]) + '</h1><img src="willow_annotated.png"><p>逐鸟判断；当前专项覆盖50种柳莺及8种相似组外鸟，复核单独展示，原网络种名保留。模型分数不是正确率。</p>' +
                ''.join(rows) + '<p>来源：' + esc(result["source"]) + '</p></html>')
    Path(result["report_path"]).write_text(document, encoding="utf-8")
