"""Offline BirdNET+ recognition for the species in the local leaf warbler guide."""

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from time import perf_counter


AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".flac", ".ogg", ".opus", ".aif", ".aiff"})
MODEL_NAME = "BirdNET+ V3.0.1"
MODEL_FILE = "BirdNET+_V3.0_Global_12K_FP16_pruned.onnx"
LABEL_FILE = "scientific_names.txt"
SAMPLE_RATE = 32_000
WINDOW_SAMPLES = 3 * SAMPLE_RATE
HOP_SAMPLES = WINDOW_SAMPLES // 2
CLASS_COUNT = 11_725


class AudioRecognitionError(RuntimeError):
    """Audio could not be read or the local audio model could not be used."""


@dataclass(frozen=True)
class AudioPolicy:
    minimum_score: float = 0.60
    competitor_ratio: float = 1.00
    uncertain_score: float = 0.20


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Audio identification canceled.")


class AudioRecognizer:
    """Reuse a single CPU session on the identification worker thread."""

    def __init__(self, app_root, *, threads=4, batch_size=2, policy=AudioPolicy()):
        self.root = Path(app_root)
        self.threads = threads
        self.batch_size = batch_size
        self.policy = policy
        self._session = None
        self.load_seconds = 0.0

    def _load(self):
        models = self.root / "models/audio"
        vendor = self.root / "vendor/audio"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.append(str(vendor))
        started = perf_counter()
        try:
            catalog = json.loads((self.root / "assets/species_catalog.json").read_text(encoding="utf-8-sig"))
            scope = {row["scientific_name"]: row for row in catalog["species"] if row.get("is_willow")}
            names = (models / LABEL_FILE).read_text(encoding="utf-8").splitlines()
            if len(names) != CLASS_COUNT or not scope or not scope.keys() <= set(names):
                raise ValueError("The BirdNET labels do not match the model and leaf warbler guide.")
            import numpy as np
            import onnxruntime as ort
            import soundfile
            import soxr

            options = ort.SessionOptions()
            options.intra_op_num_threads = self.threads
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            try:
                session = ort.InferenceSession(str(models / MODEL_FILE), sess_options=options,
                                               providers=["CPUExecutionProvider"])
            except Exception as error:
                # ONNX Runtime exposes its own exception classes from its native extension.
                raise AudioRecognitionError(f"Could not open the BirdNET weights. {error}") from error
            model_input, = session.get_inputs()
            scores = next(output for output in session.get_outputs() if output.shape[-1] == len(names))
            scope_indices = [index for index, name in enumerate(names) if name in scope]
        except AudioRecognitionError:
            raise
        except (OSError, ImportError, KeyError, ValueError, RuntimeError, StopIteration) as error:
            raise AudioRecognitionError(f"Could not load the local BirdNET audio model. {error}") from error
        self._np, self._soundfile, self._soxr = np, soundfile, soxr
        self._names = names
        self._scope_indices = np.asarray(scope_indices, dtype=np.intp)
        self._scope = [scope[names[index]] for index in scope_indices]
        self._input_name, self._score_name = model_input.name, scores.name
        self._session = session
        self.load_seconds = perf_counter() - started

    def _chunks(self, source, cancel):
        np = self._np
        rate = source.samplerate
        resampler = (self._soxr.ResampleStream(rate, SAMPLE_RATE, 1, dtype="float32", quality="HQ")
                     if rate != SAMPLE_RATE else None)
        # Bound the decoded allocation even if the input has a high sample rate.
        frames = min(6 * rate, 262_144)
        while True:
            check_cancel(cancel)
            block = source.read(frames, dtype="float32", always_2d=True)
            last = len(block) < frames
            mono = block[:, 0] if source.channels == 1 else block.mean(axis=1, dtype=np.float32)
            if resampler is not None:
                mono = resampler.resample_chunk(mono, last=last)
            if len(mono):
                np.nan_to_num(mono, copy=False, nan=0, posinf=0, neginf=0)
                np.clip(mono, -1, 1, out=mono)
                yield mono
            if last:
                return

    def _batches(self, chunks):
        np = self._np
        batch = np.zeros((self.batch_size, WINDOW_SAMPLES), dtype=np.float32)
        pending = np.empty(0, dtype=np.float32)
        filled = 0
        previous_end = 0
        next_start = 0
        for chunk in chunks:
            samples = np.concatenate((pending, chunk)) if len(pending) else chunk
            used = 0
            for start in range(0, len(samples) - WINDOW_SAMPLES + 1, HOP_SAMPLES):
                batch[filled] = samples[start:start + WINDOW_SAMPLES]
                filled += 1
                previous_end = next_start + WINDOW_SAMPLES
                next_start += HOP_SAMPLES
                used = start + HOP_SAMPLES
                if filled == len(batch):
                    yield batch
                    filled = 0
            pending = samples[used:]
        if next_start + len(pending) > previous_end:
            batch[filled, :len(pending)] = pending
            batch[filled, len(pending):] = 0
            filled += 1
        if filled:
            yield batch[:filled]

    def _score_batch(self, batch):
        np = self._np
        # Digital silence can be rejected without running the model. Preserve
        # the slot so evidence timestamps still match the original recording.
        audible = np.any(batch, axis=1)
        scores = np.zeros((len(batch), len(self._scope_indices)), dtype=np.float32)
        best_scores = np.zeros(len(batch), dtype=np.float32)
        best_indices = np.full(len(batch), -1, dtype=np.intp)
        if audible.any():
            feed = batch if audible.all() else batch[audible]
            try:
                ranked, = self._session.run([self._score_name], {self._input_name: feed})
            except Exception as error:
                raise AudioRecognitionError(f"BirdNET inference failed. {error}") from error
            np.nan_to_num(ranked, copy=False, nan=0, posinf=0, neginf=0)
            winners = ranked.argmax(axis=1)
            scores[audible] = ranked[:, self._scope_indices]
            best_scores[audible] = ranked[np.arange(len(ranked)), winners]
            best_indices[audible] = winners
        return scores, best_scores, best_indices

    def scan(self, path, *, cancel=None):
        """Score overlapping windows and retain only the quantities used for ranking."""
        check_cancel(cancel)
        path = Path(path)
        if path.suffix.lower() not in AUDIO_SUFFIXES:
            raise AudioRecognitionError("Unsupported audio format.")
        if not path.is_file():
            raise AudioRecognitionError("The audio file is missing.")
        if self._session is None:
            self._load()
        check_cancel(cancel)
        scored = []
        inference_seconds = 0.0
        started = perf_counter()
        try:
            with self._soundfile.SoundFile(str(path)) as source:
                duration = source.frames / source.samplerate
                for batch in self._batches(self._chunks(source, cancel)):
                    check_cancel(cancel)
                    before = perf_counter()
                    scored.append(self._score_batch(batch))
                    inference_seconds += perf_counter() - before
        except (InterruptedError, AudioRecognitionError):
            raise
        except (OSError, RuntimeError, ValueError) as error:
            raise AudioRecognitionError(f"Could not analyze the audio file. {error}") from error
        check_cancel(cancel)
        if not scored:
            raise AudioRecognitionError("The audio file has no samples.")
        seconds = perf_counter() - started
        scores, competitors, winners = (self._np.concatenate(parts, axis=0) for parts in zip(*scored))
        return {"scores": scores, "competitors": competitors, "winners": winners, "duration_seconds": duration,
                "inference_seconds": inference_seconds, "decode_seconds": seconds - inference_seconds}

    def summarize(self, scan, policy=None):
        np = self._np
        policy = policy or self.policy
        scores, competitors = scan["scores"], scan["competitors"]
        peaks = scores.max(axis=1)
        qualifies = (peaks >= policy.minimum_score) & (peaks >= competitors * policy.competitor_ratio)
        eligible = scores[qualifies] if qualifies.any() else scores
        confidence = eligible.max(axis=0)
        ranking = np.argsort(-confidence, kind="stable")[:3]
        status = ("identified" if qualifies.any() else
                  "uncertain" if confidence[ranking[0]] >= policy.uncertain_score else "no_match")
        candidates = []
        for index in ranking:
            if status == "no_match" or confidence[index] < policy.uncertain_score:
                break
            row = self._scope[index]
            evidence = scores[:, index] if status == "uncertain" else np.where(qualifies, scores[:, index], -1)
            candidates.append({"common_name": row["common_name"], "scientific_name": row["scientific_name"],
                               "english_name": row.get("english_name"), "confidence": float(confidence[index]),
                               "evidence_seconds": float(evidence.argmax()) * HOP_SAMPLES / SAMPLE_RATE})
        at = int(competitors.argmax())
        winner = int(scan["winners"][at])
        top_overall = {"scientific_name": self._names[winner], "confidence": float(competitors[at])} if winner >= 0 else None
        return {"status": status, "candidates": candidates, "duration_seconds": scan["duration_seconds"],
                "model": MODEL_NAME, "windows": len(scores), "top_overall": top_overall,
                "decode_seconds": scan["decode_seconds"], "inference_seconds": scan["inference_seconds"]}

    def recognize(self, path, *, cancel=None):
        return self.summarize(self.scan(path, cancel=cancel))
