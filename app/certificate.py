"""Per-bird identification evidence, ranked guide comparisons and local image zoom.

This is a display module. It reads saved model outputs and never changes a
prediction, ranking, threshold, image crop or weight.
"""
from pathlib import Path
import math
import tkinter as tk


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 <= value <= 1 else None
    except (ValueError, TypeError):
        return None


def _percent(value):
    value = _number(value)
    return f"{value * 100:.1f}%" if value is not None else "未提供"


def _ranked(box):
    expert = box.get("specialist") if isinstance(box.get("specialist"), dict) else {}
    specialist = [item for item in expert.get("top3", []) if isinstance(item, dict) and item.get("scientific_name")]
    if specialist:
        candidates = [{"scientific_name": item["scientific_name"],
                       "common_name": item.get("common_name") or item["scientific_name"],
                       "confidence": _number(item.get("confidence"))} for item in specialist[:3]]
        rejected = (expert.get("rejected_as_OTHER") or not expert.get("is_willow", True) or
                    expert.get("decision_kind") == "similar_non_willow" or
                    box.get("gate_status") != "willow")
        title = "融合复核前三" if (expert.get("species_fusion") or {}).get("applied") else "柳莺专项前三"
        return candidates, title + (" · 仅候选，未采纳" if rejected else ""), "specialist"
    original = [item for item in box.get("original_top5", []) if isinstance(item, dict) and item.get("name")]
    return ([{"scientific_name": item["name"], "common_name": item.get("common_name") or item["name"],
              "confidence": _number(item.get("confidence"))} for item in original[:3]],
            "原双BioCLIP前三", "original")


def conclusion(box):
    """Use the recorded decision, and keep abstentions distinct from candidates."""
    expert = box.get("specialist") if isinstance(box.get("specialist"), dict) else {}
    gate = box.get("gate_status")
    if "prediction_source" in box:
        scientific = box.get("scientific_name") or ""
        if not scientific:
            return {"common_name": "鸟种未确认", "scientific_name": "", "confidence": None,
                    "source": box.get("prediction_source") or "未确认", "confirmed": False}
        return {"common_name": box.get("common_name") or scientific, "scientific_name": scientific,
                "confidence": _number(box.get("classification_confidence")),
                "source": box.get("prediction_source") or "已存档分类结果", "confirmed": True}
    valid_expert = (gate == "willow" and expert and not expert.get("rejected_as_OTHER", True) and
                    expert.get("decision_kind") != "similar_non_willow" and expert.get("is_willow", True) and
                    (expert.get("class_index") is not None or expert.get("global_id", -1) != -1) and
                    expert.get("scientific_name"))
    if valid_expert:
        return {"common_name": expert.get("common_name") or expert["scientific_name"],
                "scientific_name": expert["scientific_name"], "confidence": _number(expert.get("confidence")),
                "source": expert.get("display_source", "柳莺专项复核"), "confirmed": True}
    if expert.get("rejected_as_OTHER") or not expert.get("is_willow", True) or expert.get("decision_kind") == "similar_non_willow":
        return {"common_name": "鸟种未确认", "scientific_name": "", "confidence": None,
                "source": "专项拒绝或倾向相似组外鸟", "confirmed": False}
    if box.get("original_accepted") and gate not in ("uncertain", "unknown"):
        scientific = box.get("original_scientific_name") or ""
        if scientific:
            return {"common_name": box.get("original_name") or scientific, "scientific_name": scientific,
                    "confidence": _number(box.get("original_confidence")), "source": "原双BioCLIP结果保留",
                    "confirmed": True}
    return {"common_name": "鸟种未确认", "scientific_name": "", "confidence": None,
            "source": "证据不足或专项未接受", "confirmed": False}


def _guide(scientific, common):
    if not scientific:
        return None, None
    from . import art
    # Match the scientific epithet/declared aliases. Never silently substitute a
    # different plate just because a stale/common-name string looks similar.
    plate = art.find_plate(scientific)
    if plate:
        return plate.get("bird_path") or plate["path"], plate["path"]
    return None, None


def _wrap(view, parent, text, *, size=10, colour=None, bold=False, **kwargs):
    from .library_ui import INK
    label = view._label(parent, str(text), size, colour or INK, bold,
                        anchor="w", justify="left", wraplength=650, **kwargs)
    label.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width - 4)))
    return label


def _picture(view, parent, path, size, title, *, zoom_path=None, empty="本地图片暂不可用"):
    from .library_ui import SOFT
    image = view._image(path, size) if path else None
    if image:
        label = view._label(parent, "", image=image)
        label.pack(pady=(4, 3))
        view._bind_zoom(label, zoom_path or path, title)
        return label
    _wrap(view, parent, empty, size=9, colour=SOFT).pack(fill="x", pady=(12, 15))
    return None


def _step(view, parent, number, title, subtitle=""):
    from .library_ui import CARD, GREEN, LINE, SOFT
    head = tk.Frame(parent, background=CARD)
    head.pack(fill="x", pady=(13, 6))
    badge = tk.Label(head, text=f"{number:02d}", background=GREEN, foreground="white",
                     font=(view.family, 10, "bold"), padx=8, pady=3)
    badge.pack(side="left")
    view._label(head, title, 12, GREEN, True).pack(side="left", padx=9)
    tk.Frame(head, background=LINE, height=1).pack(side="left", fill="x", expand=True, padx=(2, 0))
    if subtitle:
        _wrap(view, parent, subtitle, size=9, colour=SOFT).pack(fill="x", pady=(0, 3))


def _candidate(view, parent, item, rank):
    from .library_ui import CARD, GREEN, LINE, SOFT, STRIPE
    card = tk.Frame(parent, background=STRIPE, highlightthickness=1, highlightbackground=LINE)
    card.grid(row=0, column=rank - 1, sticky="nsew", padx=(0 if rank == 1 else 5, 0 if rank == 3 else 5))
    inner = tk.Frame(card, background=STRIPE)
    inner.pack(fill="both", expand=True, padx=10, pady=10)
    view._label(inner, f"候选 {rank}", 9, SOFT, True).pack(anchor="w")
    if item is None:
        _wrap(view, inner, "该记录未保存此候选", size=10, colour=SOFT).pack(fill="x", pady=16)
        return
    _wrap(view, inner, item["common_name"], size=12, colour=GREEN, bold=True).pack(fill="x", pady=(4, 1))
    view._label(inner, _percent(item["confidence"]), 18, GREEN, True).pack(anchor="w", pady=(0, 5))
    image_path, full_path = _guide(item["scientific_name"], item["common_name"])
    _picture(view, inner, image_path, (180, 105),
             f"候选 {rank} · {item['common_name']} · 参考图", zoom_path=full_path,
             empty="暂无对应的本地参考图")
    _wrap(view, inner, item["scientific_name"], size=8, colour=SOFT).pack(fill="x", pady=(3, 0))
    if image_path:
        from . import art
        reference = art.find_reference_image(item["scientific_name"])
        credit = art.reference_credit(reference) if reference else "图鉴图 · 点击查看完整辨识页"
        _wrap(view, inner, credit, size=8, colour=SOFT).pack(fill="x", pady=(4, 0))


def _bird(view, parent, box, number):
    from .library_ui import CARD, GREEN, INK, LINE, PAPER, SOFT, STRIPE
    result = conclusion(box)
    candidates, ranking_title, rank_source = _ranked(box)
    frame = tk.Frame(parent, background=CARD, highlightthickness=1, highlightbackground=LINE)
    frame.pack(fill="x", pady=(14, 0))
    inner = tk.Frame(frame, background=CARD)
    inner.pack(fill="both", expand=True, padx=18, pady=15)
    _wrap(view, inner, f"第 {number} 只鸟 · {box.get('bird_id') or f'bird_{number:03d}'}", size=16,
          colour=GREEN, bold=True).pack(fill="x")
    _wrap(view, inner, "检测鸟框  →  独立裁图  →  前三图鉴比对  →  当前结果", size=10,
          colour=SOFT).pack(fill="x", pady=(6, 0))
    _step(view, inner, 1, "检出这只鸟", "检测层只负责找到鸟的位置；下一步对这个鸟框单独分类。")
    source = tk.Frame(inner, background=CARD)
    source.pack(fill="x")
    source.columnconfigure(1, weight=1)
    media = tk.Frame(source, background=CARD)
    media.grid(row=0, column=0, sticky="nw", padx=(0, 18))
    crop = view._resolve(box.get("crop_path") or box.get("tight_crop_path"))
    _picture(view, media, crop, (230, 150), f"第 {number} 只鸟 · 模型实际使用的独立裁图", empty="这只鸟的裁图已移走")
    view._label(media, "实际裁图 · 点击放大", 8, SOFT).pack(pady=(0, 2))
    evidence = tk.Frame(source, background=CARD)
    evidence.grid(row=0, column=1, sticky="nsew")
    _wrap(view, evidence, "检测置信度：" + _percent(box.get("detection_confidence", box.get("confidence"))),
          size=13, colour=GREEN, bold=True).pack(fill="x", pady=(4, 8))
    original = box.get("original_name") or box.get("original_scientific_name") or "未保存种名"
    _wrap(view, evidence, f"原双BioCLIP：{original}\n原分类分数：{_percent(box.get('original_confidence'))}", size=10).pack(fill="x", pady=(0, 8))
    expert = box.get("specialist") if isinstance(box.get("specialist"), dict) else {}
    if expert:
        name = expert.get("common_name") or expert.get("scientific_name") or "未确认"
        qualifier = "（未接受）" if expert.get("rejected_as_OTHER") or expert.get("decision_kind") == "similar_non_willow" else ""
        _wrap(view, evidence, f"柳莺专项：{name}{qualifier}\n专项分数：{_percent(expert.get('confidence'))}", size=10).pack(fill="x", pady=(0, 8))
    if box.get("xyxy"):
        try:
            coordinates = ", ".join(f"{float(value):.1f}" for value in box["xyxy"])
            _wrap(view, evidence, "鸟框坐标：" + coordinates, size=8, colour=SOFT).pack(fill="x")
        except (ValueError, TypeError):
            pass
    _step(view, inner, 2, "前三候选与标准图鉴", ranking_title + "；三项沿用保存时的分类器分数，不在界面重新计算。")
    compare = tk.Frame(inner, background=CARD)
    compare.pack(fill="x")
    for index in range(3):
        compare.columnconfigure(index, weight=1, uniform="candidate")
        _candidate(view, compare, candidates[index] if index < len(candidates) else None, index + 1)
    if rank_source == "specialist" and box.get("original_top5"):
        original_top = []
        for index, item in enumerate(box["original_top5"][:3], 1):
            if isinstance(item, dict):
                original_top.append(f"{index}. {item.get('common_name') or item.get('name') or '未保存'} {_percent(item.get('confidence'))}")
        _wrap(view, inner, "原双BioCLIP前三（另存，不与专项混为同一排名）：\n" + "；".join(original_top),
              size=9, colour=SOFT).pack(fill="x", pady=(9, 0))
    _step(view, inner, 3, "这只鸟的当前结果", "只使用这只鸟的结果；不会把其他鸟框的候选合并进来。")
    answer = tk.Frame(inner, background=STRIPE, highlightthickness=1, highlightbackground=LINE)
    answer.pack(fill="x")
    answer.columnconfigure(1, weight=1)
    guide_path, full_path = _guide(result["scientific_name"], result["common_name"])
    if guide_path:
        final_media = tk.Frame(answer, background=STRIPE)
        final_media.grid(row=0, column=0, padx=12, pady=12)
        _picture(view, final_media, guide_path, (175, 105), "当前结果 · " + result["common_name"], zoom_path=full_path)
        from . import art
        reference = art.find_reference_image(result["scientific_name"])
        if reference:
            _wrap(view, final_media, art.reference_credit(reference), size=8, colour=SOFT).pack(fill="x")
    content = tk.Frame(answer, background=STRIPE)
    content.grid(row=0, column=1 if guide_path else 0, sticky="nsew", padx=15, pady=13)
    _wrap(view, content, result["common_name"], size=20, colour=GREEN, bold=True).pack(fill="x")
    if result["scientific_name"]:
        _wrap(view, content, result["scientific_name"], size=10, colour=SOFT).pack(fill="x", pady=(3, 5))
    _wrap(view, content, "鸟种分类分数：" + _percent(result["confidence"]), size=13,
          colour=GREEN, bold=True).pack(fill="x", pady=(3, 5))
    _wrap(view, content, "结果来源：" + result["source"], size=9, colour=SOFT).pack(fill="x")
    if not result["confirmed"]:
        _wrap(view, content, "前三是候选，不代表已经确认该鸟种。", size=10, colour="#9a6d26").pack(fill="x", pady=(6, 0))
    if view.library.has_species(result["scientific_name"]):
        view._button(content, "查看鸟种卡", lambda: view._go_species(result["scientific_name"])).pack(anchor="w", pady=(9, 0))
    _wrap(view, inner, "参考图包括用户提供的《两岸三地50种柳莺类辨识》及附来源的本地补充图片。模型分数不是识别正确率；参考图未参与分类分数计算。",
          size=8, colour=SOFT).pack(fill="x", pady=(10, 0))


def cancel_pending_render(view):
    """Cancel a partial certificate; reopening it must build the missing birds.

    Incrementing the generation also invalidates a callback already dequeued by
    Tk. Closing/withdrawing the archive may call this without destroying widgets.
    """
    view._certificate_render_generation = getattr(view, "_certificate_render_generation", 0) + 1
    pending = bool(getattr(view, "_certificate_render_pending", False))
    timer = getattr(view, "_certificate_after_id", None)
    view._certificate_after_id = None
    view._certificate_render_pending = False
    if timer is not None:
        try:
            view.window.after_cancel(timer)
        except tk.TclError:
            pass
    if pending:
        view._certificate_rendered = False
        view._certificate_render_incomplete = True
    return pending


def render_certificate(view, result):
    """Render a saved result using the current local library's view helpers."""
    from .library_ui import CARD, GREEN, INK, LINE, SOFT, _date, _photo_name
    cancel_pending_render(view)
    generation = view._certificate_render_generation
    view._certificate_rendered = True
    view._certificate_render_incomplete = False
    view._certificate_result = result
    view._certificate_images = []
    body = view.certificate_scroll.body
    view._clear(body)
    view.certificate_scroll.canvas.yview_moveto(0)
    if not result:
        view._label(body, "还没有这份鉴定证书", 22, GREEN, True).pack(pady=(60, 12))
        view._label(body, "先识别一张照片，或从「翻翻档案」里选择一条记录。", 11, SOFT).pack()
        return
    paper = tk.Frame(body, background=CARD, highlightthickness=1, highlightbackground=LINE)
    paper.pack(fill="x", padx=10, pady=12)
    inner = tk.Frame(paper, background=CARD)
    inner.pack(fill="both", expand=True, padx=20, pady=19)
    _wrap(view, inner, "某种柳莺 · 鉴定过程", size=24, colour=GREEN, bold=True).pack(fill="x")
    _wrap(view, inner, "看见鸟 → 每只鸟独立裁切 → 前三候选对照图鉴 → 保存当前结果", size=10,
          colour=SOFT).pack(fill="x", pady=(7, 12))
    source = _photo_name(result)
    original = result.get("source_name") or Path(str(result.get("source") or "")).name or "未记录"
    _wrap(view, inner, "照片：" + source, size=12, colour=GREEN, bold=True).pack(fill="x")
    _wrap(view, inner, f"拍摄时间：{result.get('captured_at') or '未填写'}    拍摄地点：{result.get('capture_place') or '未填写'}",
          size=10).pack(fill="x", pady=(5, 0))
    _wrap(view, inner, "识别记录时间：" + _date(result.get("created_at") or result.get("timestamp")), size=8,
          colour=SOFT).pack(fill="x", pady=(4, 0))
    if result.get("notes"):
        _wrap(view, inner, "备注：" + str(result["notes"]), size=10).pack(fill="x", pady=(6, 0))
    photos = tk.Frame(inner, background=CARD)
    photos.pack(fill="x", pady=(12, 2))
    for index, (title, reference) in enumerate((("原图", result.get("snapshot_path") or result.get("source")),
                                                ("全部鸟框", result.get("annotated_path")))):
        photos.columnconfigure(index, weight=1, uniform="original")
        block = tk.Frame(photos, background=CARD)
        block.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 8 if index == 0 else 0))
        view._label(block, title + " · 点击放大", 9, SOFT).pack(anchor="w")
        path = view._resolve(reference)
        _picture(view, block, path, (330, 165), title + " · " + source)
    boxes = list(result.get("boxes") or [])
    _wrap(view, inner, f"逐鸟鉴定 · {len(boxes)} 个检测框", size=16, colour=GREEN,
          bold=True).pack(fill="x", pady=(13, 0))
    if not boxes:
        _wrap(view, inner, "本张未检出可判断的鸟；未检出不代表照片中一定没有鸟。", size=11,
              colour=SOFT).pack(fill="x", pady=15)
    def finish():
        _wrap(view, inner, "来源文件：" + original, size=8, colour="#8a8f74").pack(fill="x", pady=(15, 4))
        _wrap(view, inner, "这是一份自动识别记录，尚未经人工核验。外观相似、遮挡、模糊与换羽会影响判断；必要时结合现场叫声、地点和多角度照片。",
              size=9, colour=SOFT).pack(fill="x", pady=(4, 0))
        view._certificate_render_pending = False
        view._certificate_render_incomplete = False

    def alive():
        if generation != view._certificate_render_generation or getattr(view, "_disposed", False):
            return False
        try:
            return bool(inner.winfo_exists())
        except tk.TclError:
            return False

    next_index = 1

    def append_next():
        nonlocal next_index
        if not alive():
            return
        view._certificate_after_id = None
        try:
            _bird(view, inner, boxes[next_index], next_index + 1)
            next_index += 1
            if next_index < len(boxes):
                # One bird per event-loop turn: images and Tk widgets remain on
                # the main thread while input/painting gets a chance to run.
                view._certificate_after_id = view.window.after(1, append_next)
            else:
                finish()
        except Exception:
            cancel_pending_render(view)
            raise

    def inner_destroyed(event):
        if event.widget is inner and generation == view._certificate_render_generation:
            cancel_pending_render(view)

    inner.bind("<Destroy>", inner_destroyed, add="+")
    if boxes:
        _bird(view, inner, boxes[0], 1)
    if len(boxes) > 1:
        view._certificate_render_pending = True
        view._certificate_after_id = view.window.after(1, append_next)
    else:
        finish()
