"""Local record crops and reversible slideshow slots, independent of inference."""
import json
from pathlib import Path
import uuid
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageOps, ImageTk

PAPER, CARD, INK, GREEN = "#f6f3e2", "#fffdf4", "#2f361e", "#466d2d"


def _read(root):
    path = Path(root) / "config/hero_gallery.json"
    if path.is_file():
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        if doc.get("schema") != "bird-hero-gallery-v1":
            raise ValueError("未知轮播设置版本")
        return doc
    return {"schema": "bird-hero-gallery-v1", "overrides": {}, "additions": []}


def _write(root, document):
    path = Path(root) / "config/hero_gallery.json"
    path.parent.mkdir(exist_ok=True)
    pending = path.with_suffix(".json.pending")
    pending.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def base_gallery(photos):
    return [{**photo, "gallery_id": "builtin:" + str(photo.get("file") or photo["path"].name)} for photo in photos]


def _record_photo(root, library, spec, gallery_id):
    root = Path(root).resolve()
    path = (root / spec.get("path", "")).resolve()
    if not path.is_relative_to(root / "assets/user_heroes") or not path.is_file():
        return None
    event = library.event_detail(spec.get("event_id"))
    if not event:
        return None
    box = next((box for box in event.get("boxes", []) if box.get("bird_id") == spec.get("bird_id")), None)
    if box is None:
        return None
    scientific = box.get("scientific_name") or ""
    card = library.species_detail(scientific) if scientific else None
    common = (card or {}).get("common_name") or box.get("common_name") or "鸟种未确认"
    return {"path": path, "file": path.name, "focus": (.5, .5), "fit": "contain", "user": True,
            "user_record": True, "gallery_id": gallery_id, "event_id": event["event_id"],
            "bird_id": box["bird_id"], "species_cn": common, "scientific_name": scientific,
            "display_name": event.get("display_name") or "我的观鸟照片", "author": "我的观鸟记录",
            "local_audio": bool((card or {}).get("audio")), "record_spec": spec}


def load_gallery(root, library, defaults):
    document = _read(root)
    if not document.get("overrides") and not document.get("additions"):
        return list(defaults)
    if callable(library):
        library = library()
    result = []
    for photo in defaults:
        key = photo["gallery_id"]
        override = document.get("overrides", {}).get(key)
        selected = _record_photo(root, library, override, key) if override else None
        result.append(selected or photo)
    for spec in document.get("additions", []):
        photo = _record_photo(root, library, spec, spec["gallery_id"])
        if photo:
            result.append(photo)
    return result


def save_crop(root, event, box, image, crop, replace_id=None):
    root = Path(root).resolve()
    x1, y1, x2, y2 = crop
    x1, x2 = sorted((max(0, min(image.width, round(x1))), max(0, min(image.width, round(x2)))))
    y1, y2 = sorted((max(0, min(image.height, round(y1))), max(0, min(image.height, round(y2)))))
    if x2 - x1 < 16 or y2 - y1 < 16:
        raise ValueError("裁切范围太小，请重新框选。")
    selected = box.get("xyxy")
    if isinstance(selected, (list, tuple)) and len(selected) == 4:
        bx1, by1, bx2, by2 = map(float, selected)
        if bx2 > bx1 and by2 > by1:
            centre = (bx1+bx2)/2, (by1+by2)/2
            overlap = max(0, min(x2, bx2)-max(x1, bx1)) * max(0, min(y2, by2)-max(y1, by1))
            if not (x1 <= centre[0] <= x2 and y1 <= centre[1] <= y2) or overlap < (bx2-bx1)*(by2-by1)*.25:
                raise ValueError("裁切需要包含所选鸟框的中心和主体；若要用旁边的鸟，请先切换鸟只。")
    document = _read(root)
    if replace_id and not (replace_id.startswith("builtin:") or any(x["gallery_id"] == replace_id for x in document.get("additions", []))):
        raise ValueError("先在右侧选择要替换的轮播图片。")
    unique = uuid.uuid4().hex
    folder = root / "assets/user_heroes"
    folder.mkdir(exist_ok=True)
    path = folder / (unique + ".jpg")
    image.crop((x1, y1, x2, y2)).convert("RGB").save(path, quality=94)
    key = replace_id or "record:" + unique
    spec = {"gallery_id": key, "event_id": event["event_id"], "bird_id": box["bird_id"],
            "path": path.relative_to(root).as_posix(), "crop_xyxy": [x1, y1, x2, y2],
            "source_sha256": event.get("source_sha256"), "original_source_name": event.get("source_name")}
    if replace_id and replace_id.startswith("builtin:"):
        document.setdefault("overrides", {})[replace_id] = spec
    elif replace_id:
        document["additions"] = [spec if x["gallery_id"] == replace_id else x for x in document["additions"]]
    else:
        document.setdefault("additions", []).append(spec)
    try:
        _write(root, document)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return key


def restore_builtin(root, gallery_id):
    if not gallery_id.startswith("builtin:"):
        raise ValueError("请先选一张内置轮播图。")
    doc = _read(root)
    doc.setdefault("overrides", {}).pop(gallery_id, None)
    _write(root, doc)


class HeroCropPicker(tk.Toplevel):
    def __init__(self, parent, app_root, library, event, gallery, on_saved):
        super().__init__(parent)
        self.app_root, self.library, self.event = Path(app_root), library, event
        self.gallery, self.on_saved = list(gallery), on_saved
        self.title("我有自己的观鸟记录图！")
        self.configure(background=PAPER)
        self.geometry(f"{min(1060, self.winfo_screenwidth()-80)}x{min(740, self.winfo_screenheight()-100)}")
        self.minsize(780, 540)
        self.transient(parent)
        self.family = "Microsoft YaHei UI"
        self.boxes = event.get("boxes") or []
        if not self.boxes:
            self.destroy()
            raise ValueError("这张照片没有可选鸟框。")
        source = next((library.resolve_path(event.get(key)) for key in ("snapshot_path", "source")
                       if event.get(key) and library.resolve_path(event.get(key)) and library.resolve_path(event.get(key)).is_file()), None)
        if source is None:
            self.destroy()
            raise ValueError("原图快照已移走，请选择另一份有本地原图的记录。")
        with Image.open(source) as original:
            self.image = ImageOps.exif_transpose(original).convert("RGB")
        self.crop = [0, 0, self.image.width, self.image.height]
        self.scale, self.offset = 1., (0, 0)
        self._start_point = None
        self._photos = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, background=PAPER)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=12)
        tk.Label(header, text="选择鸟 → 框选原图 → 新增或替换轮播图", background=PAPER, foreground=GREEN,
                 font=(self.family, 15, "bold")).pack(anchor="w")
        self.bird_choice = ttk.Combobox(header, state="readonly", width=54,
            values=[f"第{i+1}只 · {b.get('common_name') or '鸟种未确认'} · {b.get('scientific_name') or '不关联叫声'}" for i, b in enumerate(self.boxes)])
        self.bird_choice.pack(side="left", pady=(8, 0))
        self.bird_choice.current(0)
        self.bird_choice.bind("<<ComboboxSelected>>", lambda event: self.reset_crop())
        self.canvas = tk.Canvas(self, background="#27301f", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=(16, 10))
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        side = tk.Frame(self, background=CARD)
        side.grid(row=1, column=1, sticky="nsew", padx=(0, 16))
        tk.Label(side, text="已有轮播图（内置图也在这里）", background=CARD, foreground=GREEN,
                 font=(self.family, 10, "bold")).pack(padx=10, pady=10)
        holder = tk.Frame(side, background=CARD)
        holder.pack(fill="both", expand=True, padx=10)
        self.slots = ttk.Treeview(holder, show="tree", selectmode="browse", height=7)
        self.slots.column("#0", width=260, stretch=True)
        scroll = ttk.Scrollbar(holder, command=self.slots.yview)
        self.slots.configure(yscrollcommand=scroll.set)
        self.slots.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for i, photo in enumerate(self.gallery):
            kind = "观鸟记录" if photo.get("user_record") else "内置"
            self.slots.insert("", "end", iid=str(i), text=f"{kind} {i+1} · {photo.get('species_cn') or '未确认'}")
        self.slots.bind("<<TreeviewSelect>>", self.preview_slot)
        self.slot_preview = tk.Label(side, background=CARD)
        self.slot_preview.pack(padx=10, pady=8)
        controls = tk.Frame(self, background=PAPER)
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=12)
        tk.Label(controls, text="左侧拖动框选。替换只改轮播设置，原图和检测结果保留；每10秒自动轮播。",
                 background=PAPER, foreground=INK, font=(self.family, 9)).pack(anchor="w", pady=(0, 8))
        for text, command in (("新增到轮播", lambda: self.commit(False)), ("替换右侧选中项", lambda: self.commit(True)),
                              ("按鸟框重置", self.reset_crop), ("恢复选中的内置图", self.restore), ("取消", self.destroy)):
            tk.Button(controls, text=text, command=command, background=GREEN if text == "新增到轮播" else CARD,
                foreground="white" if text == "新增到轮播" else GREEN, relief="flat", padx=12, pady=8,
                font=(self.family, 10)).pack(side="left", padx=(0, 8))
        self.bind("<Escape>", lambda event: self.destroy())
        self.reset_crop()
        self.grab_set()

    def reset_crop(self):
        box = self.boxes[self.bird_choice.current()].get("xyxy")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            x1, y1, x2, y2 = map(float, box)
            px, py = (x2-x1)*.3, (y2-y1)*.3
            self.crop = [max(0, x1-px), max(0, y1-py), min(self.image.width, x2+px), min(self.image.height, y2+py)]
        else:
            self.crop = [0, 0, self.image.width, self.image.height]
        self.draw()

    def draw(self):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 4 or height < 4:
            return
        self.scale = min((width-20)/self.image.width, (height-20)/self.image.height)
        size = max(1, round(self.image.width*self.scale)), max(1, round(self.image.height*self.scale))
        self.offset = ((width-size[0])/2, (height-size[1])/2)
        self.photo = ImageTk.PhotoImage(self.image.resize(size, Image.Resampling.LANCZOS), master=self)
        self.canvas.delete("all")
        self.canvas.create_image(*self.offset, image=self.photo, anchor="nw")
        self.canvas.create_rectangle(*self._screen_box(), outline="#d5ec93", width=3, tags="crop")

    def _screen_box(self):
        return tuple(self.offset[i%2] + value*self.scale for i, value in enumerate(self.crop))

    def _point(self, event):
        return (max(0, min(self.image.width, (event.x-self.offset[0])/self.scale)),
                max(0, min(self.image.height, (event.y-self.offset[1])/self.scale)))

    def start_drag(self, event):
        self._start_point = self._point(event)

    def drag(self, event):
        if self._start_point:
            x, y = self._point(event)
            a, b = self._start_point
            self.crop = [min(a, x), min(b, y), max(a, x), max(b, y)]
            self.canvas.coords("crop", *self._screen_box())

    def preview_slot(self, event=None):
        selection = self.slots.selection()
        if not selection:
            return
        photo = self.gallery[int(selection[0])]
        with Image.open(photo["path"]) as image:
            preview = ImageOps.contain(image.convert("RGB"), (260, 145))
        self.slot_photo = ImageTk.PhotoImage(preview, master=self)
        self.slot_preview.configure(image=self.slot_photo)

    def commit(self, replace):
        selected = self.slots.selection()
        if replace and not selected:
            messagebox.showinfo("先选替换对象", "在右侧选择一张轮播图，再点替换；也可以直接新增。", parent=self)
            return
        key = self.gallery[int(selected[0])]["gallery_id"] if replace else None
        try:
            key = save_crop(self.app_root, self.event, self.boxes[self.bird_choice.current()], self.image, self.crop, key)
            self.on_saved(key)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("图片未保存", str(exc), parent=self)

    def restore(self):
        selected = self.slots.selection()
        if not selected:
            return
        key = self.gallery[int(selected[0])]["gallery_id"]
        try:
            restore_builtin(self.app_root, key)
            self.on_saved(key)
            self.destroy()
        except Exception as exc:
            messagebox.showinfo("无法恢复", str(exc), parent=self)
