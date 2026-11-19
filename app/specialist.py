"""Frozen 50-willow + 8-similar-bird head; reuse original H features exactly."""
import hashlib
import json
from pathlib import Path
import numpy as np

APP = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def active_manifest():
    active = read(APP / "config/active_specialist.json")
    require(active["schema"] == "willow-active-specialist-v1", "未知专项模型配置")
    path = (APP / active["manifest"]).resolve()
    require(path.is_relative_to(APP / "models"), "专项模型必须位于本应用models目录")
    require(sha(path) == active["manifest_sha256"], "专项模型清单发生变化")
    manifest = read(path)
    require(manifest["schema"] == "willow50-global-specialist-v1" and
            manifest["feature_mode"] == "global_only" and manifest["species_count"] == 58 and
            manifest["willow_species_count"] == 50 and manifest["automatic_original_override"] is False,
            "当前入口需要冻结的50种柳莺复核头")
    return path, manifest


class Willow50Head:
    def __init__(self, package_root):
        # This module and the GUI can be imported without importing torch.
        import torch
        self.torch = torch
        self.root = Path(package_root).resolve()
        self.manifest_path, self.manifest = active_manifest()
        self.manifest_sha256 = sha(self.manifest_path)
        self.head_path = (self.manifest_path.parent / self.manifest["head"]).resolve()
        require(self.head_path.is_relative_to(APP / "models"), "专项权重路径越界")
        self.verify_files()
        payload = torch.load(self.head_path, map_location="cpu", weights_only=True)
        self.class_keys = [c["scientific_name"] for c in self.manifest["classes"]]
        require(payload["schema"] == "visible-parts-species-head-v1" and
                payload["mode"] == "global_only" and payload["architecture"] == "linear" and
                payload["class_keys"] == self.class_keys == sorted(set(self.class_keys)),
                "专项权重结构或类别顺序不一致")
        require(payload["metadata"]["contract"]["train"]["encoder_contract"] == self.manifest["encoder_contract"],
                "专项训练特征契约不一致")
        self.state = payload["state_dict"]
        expected = {"mean": (2055,), "scale": (2055,), "classifier.weight": (58, 2055), "classifier.bias": (58,)}
        require(set(self.state) == set(expected) and all(tuple(self.state[k].shape) == shape and
                self.state[k].dtype == torch.float32 and torch.isfinite(self.state[k]).all().item()
                for k, shape in expected.items()) and (self.state["scale"] > 0).all().item(), "专项参数非法")
        self.binding = {"version": self.manifest["schema"], "manifest_sha256": self.manifest_sha256,
                        "head_sha256": self.manifest["head_sha256"], "feature_mode": "global_only",
                        "selection_sha256": self.manifest["selection_sha256"], "trained_species": 58,
                        "willow_species": 50, "extra_visual_forwards": 0, "automatic_original_override": False}
        self.group_review = None
        self.group_review_config_path = APP / "config/group_review.json"
        self.group_review_config_sha256 = None
        if self.group_review_config_path.exists():
            config = read(self.group_review_config_path)
            require(config.get("schema") == "willow-independent-group-review-config-v1", "未知相似组复核配置")
            if config.get("enabled"):
                group_manifest = (APP / config["manifest"]).resolve()
                require(group_manifest.is_relative_to(APP / "models") and
                        sha(group_manifest) == config["manifest_sha256"], "相似组模型清单不一致")
                group_info = read(group_manifest)
                module_path = (group_manifest.parent / group_info["module"]).resolve()
                require(module_path.is_relative_to(group_manifest.parent) and
                        sha(module_path) == group_info["module_sha256"], "相似组推理代码不一致")
                import importlib.util
                spec = importlib.util.spec_from_file_location("willow_frozen_group_review", module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.group_review = module.GroupReview(group_manifest, self.class_keys)
                require(self.group_review.required_base_head_sha256 == self.manifest["head_sha256"],
                        "相似组复核与现用基础分类头不匹配")
                self.group_review_config_sha256 = sha(self.group_review_config_path)
                self.binding["independent_group_review"] = self.group_review.binding

    def verify_files(self):
        require(sha(self.manifest_path) == self.manifest_sha256, "专项清单发生变化")
        require(sha(self.head_path) == self.manifest["head_sha256"], "专项权重缺失或被更改")
        require(sha(self.root / "configs/recognizer.json") == self.manifest["original_configuration_sha256"] and
                sha(self.root / "configs/china_labels.json") == self.manifest["original_labels_sha256"] and
                sha(self.root / "app/inference/encoders.py") == self.manifest["original_encoder_source_sha256"],
                "原模型/类别/预处理配置与专项训练时不一致")
        require(read(self.root / "configs/recognizer.json")["asset_hashes"] == self.manifest["original_assets"],
                "原视觉权重声明与冻结配置不一致")
        require(sha(self.root / "models/bioclip25/open_clip_config.json") ==
                self.manifest["encoder_contract"]["preprocessing_sha256"], "BioCLIP2.5预处理不一致")
        if getattr(self, "group_review", None) is not None:
            require(sha(self.group_review_config_path) == self.group_review_config_sha256 and
                    sha(self.group_review.manifest_path) == self.group_review.binding["manifest_sha256"],
                    "相似组复核配置发生变化，请重新启动识别器")

    def verify_runtime(self, recognizer):
        self.verify_files()
        require(recognizer.root.resolve() == self.root and recognizer.mode == "selected" and
                recognizer.device == "cuda" and recognizer.numeric_mode == "bf16" and
                recognizer.p_encoder is not None and recognizer.p_encoder.batch_size == 2,
                "专项仅验证过原NVIDIA CUDA BF16逐鸟特征")

    def predict(self, features):
        torch = self.torch
        g = np.asarray(features["bio25"], np.float64)
        require(g.ndim == 2 and g.shape[1] == 1024 and np.isfinite(g).all() and
                (np.linalg.norm(g, axis=1) > 1e-12).all(), "逐鸟全局特征非法")
        # Exact global_only representation and train-only scaler from model_v1.
        g = g / np.linalg.norm(g, axis=1, keepdims=True)
        x = (np.concatenate((g, np.zeros_like(g), np.zeros((len(g), 7))), axis=1) / np.sqrt(3.)).astype(np.float32)
        with torch.inference_mode():
            x = (torch.from_numpy(x) - self.state["mean"]) / self.state["scale"]
            logits = torch.nn.functional.linear(x, self.state["classifier.weight"], self.state["classifier.bias"])
            probabilities = torch.softmax(logits, dim=1).numpy().astype(np.float64)
        require(probabilities.shape == (len(g), 58) and np.isfinite(probabilities).all(), "专项预测非法")
        return {"probabilities": probabilities, "predicted_index": probabilities.argmax(1)}

    def predict_refined(self, features):
        """Keep the frozen 58-class head intact; review only its two target groups."""
        base = self.predict(features)
        if self.group_review is None:
            return base
        result = self.group_review.predict(features, base["probabilities"])
        return {"probabilities": result["rerouted58"], "predicted_index": result["predicted_index"],
                "base_probabilities": result["base58"], "group_diagnostics": result["group_diagnostics"],
                "group_binding": result["binding"]}
