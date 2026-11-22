"""Offline localization for the desktop interface."""

from functools import lru_cache
import json
from pathlib import Path
import re


_messages = {}
_species = {}


@lru_cache(maxsize=1)
def _english_messages():
    return json.loads(Path(__file__).with_name("messages_en.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=2)
def _english_species(path):
    try:
        catalog = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    names = {}
    for entry in catalog.get("species", ()):
        english = entry.get("english_name")
        if english:
            for key in ("common_name", "scientific_name"):
                name = entry.get(key)
                if name:
                    names[name] = english
    return names


def set_language(language, species_catalog):
    """Set the locale before building a window and its related dialogs."""
    global _messages, _species
    if language == "en":
        _messages = _english_messages()
        _species = _english_species(species_catalog)
        return "en"
    _messages = _species = {}
    return "zh-CN"


def tr(message):
    return _messages.get(message, message)


def is_english():
    return bool(_messages)


def species_name(common_name, scientific_name=None):
    if _messages:
        return _species.get(scientific_name) or _species.get(common_name) or scientific_name or common_name
    return common_name or scientific_name


_PROGRESS_TEMPLATES = (
    (re.compile(r"正在校验模型文件 (\d+)/(\d+)：(.+)"), "正在校验模型文件 {0}/{1}：{2}"),
    (re.compile(r"正在分别识别 (\d+) 只鸟…"), "正在分别识别 {0} 只鸟…"),
    (re.compile(r"已找到 (\d+) 个柳莺候选，正在运行50种柳莺专项复核…"),
     "已找到 {0} 个柳莺候选，正在运行50种柳莺专项复核…"),
)


def progress_message(message):
    if not is_english():
        return message
    for pattern, template in _PROGRESS_TEMPLATES:
        match = pattern.fullmatch(message)
        if match:
            return tr(template).format(*match.groups())
    return _messages.get(message, "")


def result_message(message):
    """Translate a known summary at display time, including older saved records."""
    if not _messages or not message:
        return message
    counts = re.fullmatch(r"发现 (\d+) 个柳莺候选(?:；专项预测：(.*)。|，具体种类未确认。)", message)
    if counts:
        count, names = counts.groups()
        if names:
            names = ", ".join(species_name(name) for name in names.split("、"))
            return tr("发现 {0} 个柳莺候选；专项预测：{1}。").format(count, names)
        return tr("发现 {0} 个柳莺候选，具体种类未确认。").format(count)
    if message.endswith(" 专项仅验证过NVIDIA CUDA BF16；当前设备未运行专项。"):
        fallback = " 专项仅验证过NVIDIA CUDA BF16；当前设备未运行专项。"
        return tr(message.removesuffix(fallback)) + tr(fallback)
    main, separator, suggestion = message.partition(" 复核倾向相似组外鸟：")
    if separator and suggestion.endswith("；原判保留。"):
        return tr(main) + tr(" 复核倾向相似组外鸟：{0}；原判保留。").format(
            species_name(suggestion.removesuffix("；原判保留。")))
    return tr(message)
