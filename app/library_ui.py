"""Local field-guide cards, recognition archive and per-bird certificates.

This module only reads the local Library and pictures. It never imports a
recognition model and never changes a prediction. Audio is delegated to the
application via ``on_play(scientific_name)``.
"""
from .i18n import is_english, result_message, species_name, tr
from pathlib import Path
from collections import OrderedDict
import math
import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox
import webbrowser


PAPER = "#f6f3e2"
CARD = "#fffdf4"
INK = "#2f361e"
SOFT = "#687052"
GREEN = "#466d2d"
LINE = "#d9dfbd"
SELECT = "#e5edce"
MUTED = "#edeedc"
DEEP = "#24301a"
ACCENT = "#7ea24a"
OUTGROUP = "#a39a7c"
STRIPE = "#faf8ec"
NON_WILLOW_NOTE = "本软件为柳莺特化，非柳莺可能识别不准，大图鉴鸟类识别正在开发中..."


def _species_group(card):
    """Catalogue membership first; archived extra species use the same genus as the detector gate."""
    willow = card.get("is_willow")
    if willow is None:
        willow = str(card.get("scientific_name") or "").split(" ", 1)[0] == "Phylloscopus"
    return "willow" if willow else "other"


def _rounded(image, radius, background=CARD):
    """Bake rounded corners into an opaque image (Tk photo alpha is slow)."""
    from PIL import Image, ImageDraw
    k = 3
    mask = Image.new("L", (image.width * k, image.height * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius * k, fill=255)
    mask = mask.resize(image.size, Image.LANCZOS)
    base = Image.new("RGB", image.size, background)
    base.paste(image.convert("RGB"), (0, 0), mask)
    return base


def _cover(image, size):
    """Centre-crop an image to fill ``size`` exactly."""
    from PIL import Image
    w, h = size
    ratio = max(w / image.width, h / image.height)
    scaled = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.LANCZOS)
    x, y = (scaled.width - w) // 2, (scaled.height - h) // 2
    return scaled.crop((x, y, x + w, y + h))


def _text(value, missing=tr("资料待补充")):
    if value is None or value == "" or value == []:
        return missing
    if isinstance(value, (list, tuple)):
        return "；".join(_text(item, "") for item in value)
    if isinstance(value, dict):
        return "；".join(f"{key}：{_text(item, '')}" for key, item in value.items())
    return str(value)


def _score(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return tr("未提供")


def _date(value):
    return str(value or tr("未记录时间")).replace("T", " ")[:19]


def _photo_name(record):
    """User-facing title is independent of the immutable input filename."""
    return str((record or {}).get("display_name") or "").strip() or tr("未命名照片")


def _bird_name(box):
    expert = box.get("specialist") or {}
    use_expert = (box.get("gate_status") == "willow" and expert and
                  expert.get("is_willow", not expert.get("rejected_as_OTHER", True)) and
                  (expert.get("class_index") is not None or expert.get("global_id", -1) != -1) and
                  expert.get("common_name"))
    if "prediction_source" in box:
        return (box.get("common_name") or box.get("scientific_name") or tr("鸟种未确认"), box.get("scientific_name") or "",
                box.get("classification_confidence"), box.get("prediction_source", tr("模型预测")))
    if use_expert:
        return (expert["common_name"], expert.get("scientific_name", ""),
                expert.get("confidence"), tr("柳莺专项复核"))
    return (box.get("original_name") or tr("鸟种未确认"), box.get("original_scientific_name", ""),
            box.get("original_confidence"), tr("原双路分类结果"))


class _ScrollFrame(tk.Frame):
    def __init__(self, parent, background=PAPER):
        super().__init__(parent, background=background)
        self.canvas = tk.Canvas(self, background=background, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.body = tk.Frame(self.canvas, background=background)
        self.item = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.item, width=e.width))

    def contains_pointer(self, x, y):
        return (self.canvas.winfo_rootx() <= x < self.canvas.winfo_rootx() + self.canvas.winfo_width() and
                self.canvas.winfo_rooty() <= y < self.canvas.winfo_rooty() + self.canvas.winfo_height())


class _ImageViewer(tk.Toplevel):
    """Local full-resolution image viewer with fit, zoom and drag-to-pan."""

    def __init__(self, parent, path, title, family):
        from PIL import Image, ImageOps
        with Image.open(path) as source:
            decoded = ImageOps.exif_transpose(source).convert("RGB")
        super().__init__(parent)
        self.title(title or tr("查看图片"))
        self.configure(background="#20271b")
        self.source = decoded
        self.zoom = 1.
        self.photo = None
        self._resize_id = None
        self._fit_mode = True
        self._closed = False
        width = min(1120, max(720, self.winfo_screenwidth() - 100))
        height = min(820, max(560, self.winfo_screenheight() - 100))
        self.geometry(f"{width}x{height}")
        self.minsize(550, 400)
        toolbar = tk.Frame(self, background=PAPER)
        toolbar.pack(fill="x")
        self.scale_text = tk.StringVar(self, "")
        for label, command in ((tr("适应窗口"), self.fit), (tr("原始大小"), lambda: self.set_zoom(1.)),
                               ("－", lambda: self.set_zoom(self.zoom / 1.25)),
                               ("＋", lambda: self.set_zoom(self.zoom * 1.25))):
            tk.Button(toolbar, text=label, command=command, relief="flat", background=CARD,
                      foreground=GREEN, font=(family, 10), padx=13, pady=8).pack(side="left", padx=3, pady=6)
        tk.Label(toolbar, textvariable=self.scale_text, background=PAPER, foreground=SOFT,
                 font=(family, 10)).pack(side="left", padx=12)
        tk.Label(toolbar, text=tr("滚轮缩放 · 拖动平移 · Esc关闭"), background=PAPER, foreground=SOFT,
                 font=(family, 10)).pack(side="right", padx=15)
        frame = tk.Frame(self, background="#20271b")
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(frame, background="#20271b", highlightthickness=0, cursor="fleur")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self._wheel(e, -1))
        self.canvas.bind("<Configure>", self._resize)
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self.fit()

    def _max_zoom(self):
        width, height = self.source.size
        return max(.02, min(8., 16000 / max(width, height), math.sqrt(32_000_000 / (width * height))))

    def set_zoom(self, value, point=None):
        self._fit_mode = False
        self._draw(min(self._max_zoom(), max(.02, value)), point)

    def _draw(self, scale, point=None):
        from PIL import Image, ImageTk
        previous = self.zoom
        if point is None:
            point = (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
        old_x, old_y = self.canvas.coords(self.image_item)
        source_x = (self.canvas.canvasx(point[0]) - old_x) / previous
        source_y = (self.canvas.canvasy(point[1]) - old_y) / previous
        self.zoom = scale
        width = max(1, round(self.source.width * scale))
        height = max(1, round(self.source.height * scale))
        image = self.source.resize((width, height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image, master=self)
        extent_w, extent_h = max(width, self.canvas.winfo_width()), max(height, self.canvas.winfo_height())
        left, top = max(0, (extent_w - width) // 2), max(0, (extent_h - height) // 2)
        self.canvas.itemconfigure(self.image_item, image=self.photo)
        self.canvas.coords(self.image_item, left, top)
        self.canvas.configure(scrollregion=(0, 0, extent_w, extent_h))
        self.canvas.xview_moveto(max(0, (left + source_x * scale - point[0]) / extent_w))
        self.canvas.yview_moveto(max(0, (top + source_y * scale - point[1]) / extent_h))
        self.scale_text.set(f"{scale * 100:.0f}%  ·  {self.source.width} × {self.source.height}")

    def fit(self):
        if self._closed:
            return
        self._fit_mode = True
        scale = min((max(1, self.canvas.winfo_width() - 24)) / self.source.width,
                    (max(1, self.canvas.winfo_height() - 24)) / self.source.height, 1.)
        self._draw(max(.02, min(scale, self._max_zoom())))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _wheel(self, event, direction=None):
        direction = direction if direction is not None else (1 if event.delta > 0 else -1)
        self.set_zoom(self.zoom * (1.2 if direction > 0 else 1 / 1.2), (event.x, event.y))
        return "break"

    def _resize(self, event):
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(90, self._after_resize)

    def _after_resize(self):
        self._resize_id = None
        if self._fit_mode:
            self.fit()

    def destroy(self):
        if self._closed:
            return
        self._closed = True
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self.photo = None
        self.source.close()
        super().destroy()


class LibraryWindow:
    """An independent Toplevel; ``refresh`` can display newly saved results."""

    def __init__(self, parent, library, app_root, on_play=None, initial_tab="species", result=None,
                 on_use_hero=None, family=None):
        self.library, self.app_root = library, Path(app_root).resolve()
        self.on_play = on_play
        self.on_use_hero = on_use_hero
        self.window = tk.Toplevel(parent)
        self.window.title(tr("某种柳莺 · 本地图鉴与档案"))
        self.window.configure(background=PAPER)
        width = min(1180, max(900, self.window.winfo_screenwidth() - 100))
        height = min(820, max(640, self.window.winfo_screenheight() - 110))
        self.window.geometry(f"{width}x{height}")
        self._initial_width = width
        self.window.minsize(860, 610)
        if not family:
            families = set(tkfont.families(self.window))
            family = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC")
                           if f in families), "TkDefaultFont")
        self.family = family
        self._images = OrderedDict()
        self._built_tabs = set()
        self._dirty_tabs = {"species", "records", "certificate"}
        self._active_tab = initial_tab if initial_tab in self._dirty_tabs else "species"
        self._search_dirty = set()
        self._shown_species_data = None
        self._species_panels = OrderedDict()
        self._current_panel = None
        self._default_detail = None
        self._default_name = None
        self._records_signature = None
        self._rendered_certificate = None
        self._certificate_rendered = False
        self._disposed = False
        self._cards = []
        self._scrolls = []
        self._selected_species = None
        self._query_after = None
        self._photo_metadata = None
        self._plate_metadata = None
        self._viewers = []
        self._calendar = None
        self._comparison = None
        self._certificate_images = []
        self._capture_event_id = None
        self._metadata_loading = False
        self._metadata_dirty = False
        self._configure_style()
        self._build()
        self.window.bind("<MouseWheel>", self._mousewheel, add="+")
        # The notebook is stretched with the window. Binding here avoids
        # receiving the geometry event of every descendant via toplevel bindtags.
        self.notebook.bind("<Configure>", self._fit_compact_header, add="+")
        self.window.bind("<Control-z>", self._undo_shortcut, add="+")
        self.window.bind("<Control-Z>", self._undo_shortcut, add="+")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh(result=result)
        self.select_tab(initial_tab)

    @property
    def has_unsaved_edits(self):
        return self._metadata_dirty

    def _configure_style(self):
        self.style = ttk.Style(self.window)
        self.prefix = f"BirdLibrary{id(self)}"
        for suffix in ("TFrame", "TNotebook", "TNotebook.Tab"):
            self.style.configure(f"{self.prefix}.{suffix}", background=PAPER)
        # the notebook keeps doing the page switching; its dated tabs are replaced by a pill bar
        self.style.configure(f"{self.prefix}.TNotebook", borderwidth=0, tabmargins=0, padding=0,
                             bordercolor=PAPER, lightcolor=PAPER, darkcolor=PAPER)
        self.style.layout(f"{self.prefix}.TNotebook.Tab", [])
        self.style.layout(f"{self.prefix}.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        self.style.configure(f"{self.prefix}.TEntry", fieldbackground="#ffffff", bordercolor=LINE,
                             lightcolor=LINE, darkcolor=LINE, padding=(8, 4))
        self.style.map(f"{self.prefix}.TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
        self.style.configure(f"{self.prefix}.Vertical.TScrollbar", background="#dfe5c6", troughcolor=PAPER,
                             bordercolor=PAPER, arrowcolor=GREEN, lightcolor="#dfe5c6", darkcolor="#dfe5c6",
                             gripcount=0, relief="flat")
        self.style.configure(f"{self.prefix}.Horizontal.TScrollbar", background="#dfe5c6", troughcolor=PAPER,
                             bordercolor=PAPER, arrowcolor=GREEN, lightcolor="#dfe5c6", darkcolor="#dfe5c6",
                             gripcount=0, relief="flat")
        self.style.configure(f"{self.prefix}.TNotebook.Tab", padding=(20, 10),
                             font=(self.family, 11, "bold"), foreground=SOFT)
        self.style.map(f"{self.prefix}.TNotebook.Tab", background=[("selected", CARD)],
                       foreground=[("selected", GREEN)])
        self.style.configure(f"{self.prefix}.Treeview", background=CARD, fieldbackground=CARD,
                             foreground=INK, rowheight=36, font=(self.family, 10), borderwidth=0,
                             bordercolor=LINE, lightcolor=CARD, darkcolor=CARD)
        self.style.configure(f"{self.prefix}.Treeview.Heading", background=MUTED, relief="flat",
                             foreground=GREEN, font=(self.family, 10, "bold"), padding=(8, 7),
                             bordercolor=MUTED, lightcolor=MUTED, darkcolor=MUTED)
        self.style.map(f"{self.prefix}.Treeview.Heading", background=[("active", "#e3e8cf")])
        self.style.map(f"{self.prefix}.Treeview", background=[("selected", SELECT)],
                       foreground=[("selected", INK)])

    def _label(self, parent, text, size=10, color=INK, bold=False, **kwargs):
        kwargs.setdefault("font", (self.family, size, "bold" if bold else "normal"))
        label = tk.Label(parent, text=text, background=parent.cget("background"), foreground=color, **kwargs)
        # Visible widgets retain their images even when the bounded cache evicts.
        if kwargs.get("image") is not None:
            label._image_ref = kwargs["image"]
        return label

    def _button(self, parent, text, command, primary=False):
        button = tk.Button(parent, text=text, command=command,
                           background=GREEN if primary else "#ffffff", foreground="white" if primary else GREEN,
                           activebackground="#3a5c25" if primary else SELECT,
                           activeforeground="white" if primary else INK, disabledforeground="#a9ad98",
                           font=(self.family, 10, "bold"), cursor="hand2", relief="flat", bd=0,
                           highlightthickness=1, highlightbackground=GREEN if primary else LINE, padx=16, pady=7)
        normal = button.cget("background")
        button.bind("<Enter>", lambda e: button.configure(background="#557f37" if primary else STRIPE)
                    if str(button.cget("state")) != "disabled" else None)
        button.bind("<Leave>", lambda e: button.configure(background=normal))
        return button

    def _build(self):
        self.summary = tk.StringVar(self.window, "")
        self.banner = tk.Canvas(self.window, height=124, highlightthickness=0, bd=0, background=DEEP)
        self.banner.pack(fill="x")
        self._banner_size = None
        self._banner_after = None
        self.banner.bind("<Configure>", lambda e: self._schedule_banner())
        self.summary.trace_add("write", lambda *a: self._schedule_banner(force=True))
        bar = tk.Frame(self.window, background=PAPER)
        bar.pack(fill="x", padx=24, pady=(14, 10))
        self._tab_buttons = {}
        for key, text in (("species", tr("鸟种卡")), ("records", tr("翻翻档案")), ("certificate", tr("鉴定证书"))):
            pill = tk.Label(bar, text=text, font=(self.family, 11, "bold"), padx=20, pady=7, cursor="hand2",
                            background=PAPER, foreground=SOFT, highlightthickness=1, highlightbackground=LINE)
            pill.pack(side="left", padx=(0, 8))
            pill.bind("<Button-1>", lambda e, name=key: self.select_tab(name))
            self._tab_buttons[key] = pill
        self.notebook = ttk.Notebook(self.window, style=f"{self.prefix}.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.species_tab = tk.Frame(self.notebook, background=PAPER)
        self.records_tab = tk.Frame(self.notebook, background=PAPER)
        self.certificate_tab = tk.Frame(self.notebook, background=PAPER)
        self.tabs = {"species": self.species_tab, "records": self.records_tab,
                     "certificate": self.certificate_tab}
        self.notebook.add(self.species_tab, text=tr("鸟种卡"))
        self.notebook.add(self.records_tab, text=tr("翻翻档案"))
        self.notebook.add(self.certificate_tab, text=tr("鉴定证书"))
        footer = self._label(self.window, tr("逐鸟计次不等于独立个体或人工确认；分数不等于正确率。鸟种分布资料不代表照片拍摄地。"),
                             8, "#8a8f74", wraplength=1050)
        footer.pack(side="bottom", before=self.notebook, fill="x", padx=24, pady=(0, 12))
        footer.bind("<Configure>", lambda event: footer.configure(wraplength=max(500, event.width - 8)))

    def _fit_compact_header(self, event):
        height = 84 if self.window.winfo_height() < 700 else 124
        if int(self.banner.cget("height")) != height:
            self.banner.configure(height=height)

    def _schedule_banner(self, force=False):
        if force:
            self._banner_size = None
        if self._banner_after is None:
            self._banner_after = self.window.after(60, self._draw_banner)

    def _draw_banner(self):
        """Blurred real warbler photo, the app's lettering and the archive totals."""
        self._banner_after = None
        width, height = self.banner.winfo_width(), self.banner.winfo_height()
        if width < 50 or (width, height, self.summary.get()) == self._banner_size:
            return
        self._banner_size = (width, height, self.summary.get())
        try:
            from PIL import Image, ImageDraw, ImageTk
            from . import art
            # Preserve the title and portrait at their original sizes; stretch only the empty middle.
            base_height = 84 if height < 100 else 124
            if getattr(self, "_banner_base_height", None) != base_height:
                with Image.open(art.ASSETS / "branding" / f"archive-header-{base_height}.png") as src:
                    self._banner_base = src.convert("RGBA")
                self._banner_base_height = base_height
            base = self._banner_base
            left, right = min(330, width // 3), min(340, width // 3)
            image = Image.new("RGBA", (width, base.height))
            image.paste(base.crop((0, 0, left, base.height)), (0, 0))
            mid = base.crop((left, 0, base.width-right, base.height))
            image.paste(mid.resize((width-left-right, base.height), Image.Resampling.BILINEAR), (left, 0))
            image.paste(base.crop((base.width-right, 0, base.width, base.height)), (width-right, 0))
            if base.height != height:
                image = image.resize((width, height), Image.Resampling.BILINEAR)
            if is_english():
                # Reuse the banner's plain field behind the English wordmark.
                image.paste(mid.crop((0, 0, 1, mid.height)).resize((left, height)), (0, 0))
                wordmark = art.green_title("Some Phylloscopus", 24, art.serif_italic(24))
                image.alpha_composite(wordmark, (24, (height - wordmark.height) // 2))
            d = ImageDraw.Draw(image)
            # stat chips on the right
            parts = [p.strip() for p in self.summary.get().split("·") if p.strip()]
            chip_font, x = art.font(13), int(width * (.71 if is_english() else .65))
            for text in reversed(parts):
                box = d.textbbox((0, 0), text, font=chip_font)
                cw, ch = box[2] - box[0] + 30, 34
                x -= cw
                chip = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                ImageDraw.Draw(chip).rounded_rectangle((0, 0, cw - 1, ch - 1), 17, fill=(255, 255, 255, 40),
                                                        outline=(236, 244, 214, 120), width=1)
                image.alpha_composite(chip, (x, (height - ch) // 2))
                d.text((x + 15 - box[0], (height - ch) // 2 + (ch - (box[3] - box[1])) // 2 - box[1]), text,
                       font=chip_font, fill=(246, 250, 232))
                x -= 10
            self._banner_photo = ImageTk.PhotoImage(image.convert("RGB"), master=self.window)
            self.banner.delete("all")
            self.banner.create_image(0, 0, anchor="nw", image=self._banner_photo)
        except Exception:
            self.banner.delete("all")
            self.banner.create_text(26, height // 2, anchor="w", text=tr("柳莺的本地档案"), fill="#e8f0d0",
                                    font=(self.family, 22, "bold"))

    def _sync_tabs(self):
        try:
            current = self.notebook.select()
        except tk.TclError:
            return
        if getattr(self, "_painted_tab", None) == current:
            return
        self._painted_tab = current
        for key, pill in self._tab_buttons.items():
            active = str(self.tabs[key]) == str(current)
            pill.configure(background=GREEN if active else "#ffffff", foreground="white" if active else SOFT,
                           highlightbackground=GREEN if active else LINE)

    def _ensure_tab(self, name):
        if name in self._built_tabs:
            return
        self._built_tabs.add(name)
        if name == "species":
            self._build_species()
        elif name == "records":
            self._build_records()
        else:
            self.certificate_scroll = _ScrollFrame(self.certificate_tab)
            self.certificate_scroll.pack(fill="both", expand=True)
            self._scrolls.append(self.certificate_scroll)

    def _tab_changed(self, event=None):
        current = self.notebook.select()
        name = next((key for key, frame in self.tabs.items() if str(frame) == current), self._active_tab)
        if name != "certificate":
            self._pause_certificate()
        self._active_tab = name
        self._ensure_tab(name)
        self._refresh_tab(name)
        self._sync_tabs()

    def _pause_certificate(self):
        if getattr(self, "_certificate_render_pending", False):
            from .certificate import cancel_pending_render
            cancel_pending_render(self)
            self._dirty_tabs.add("certificate")

    def _refresh_tab(self, name):
        if name not in self._dirty_tabs:
            return
        self._dirty_tabs.discard(name)
        if name == "species":
            self._refresh_species()
        elif name == "records":
            self._refresh_records()
        else:
            current = getattr(self, "_certificate_result", None)
            if current and current.get("event_id"):
                current = self.library.event_detail(current["event_id"])
            self._show_certificate(current)

    def _build_species(self):
        self.species_group = tk.StringVar(self.window, "willow")
        groups = tk.Frame(self.species_tab, background=PAPER)
        groups.pack(fill="x", pady=(10, 0))
        self._species_group_buttons = {}
        for key, title in (("willow", tr("柳莺")), ("other", tr("非柳莺"))):
            pill = tk.Label(groups, text=title, font=(self.family, 11, "bold"),
                            padx=18, pady=6, cursor="hand2", takefocus=True,
                            background=CARD, foreground=GREEN, highlightthickness=1,
                            highlightbackground=LINE)
            pill.pack(side="left", padx=(0, 8))
            for event in ("<Button-1>", "<Return>", "<space>"):
                pill.bind(event, lambda e, group=key: self._select_species_group(group))
            self._species_group_buttons[key] = pill
        self._species_group_notice = self._label(self.species_tab, tr(NON_WILLOW_NOTE), 10, SOFT,
                                                 anchor="w", justify="left", wraplength=1000)
        self._species_group_notice.bind("<Configure>", lambda event:
            self._species_group_notice.configure(wraplength=max(240, event.width - 10)))
        toolbar = tk.Frame(self.species_tab, background=PAPER)
        self._species_toolbar = toolbar
        toolbar.pack(fill="x", pady=(12, 10))
        self._label(toolbar, tr("找一种鸟"), 10, SOFT).pack(side="left", padx=(2, 10))
        self.query = tk.StringVar(self.window, "")
        entry = ttk.Entry(toolbar, textvariable=self.query, width=35, font=(self.family, 11),
                          style=f"{self.prefix}.TEntry")
        entry.pack(side="left", ipady=5)
        self.query.trace_add("write", lambda *args: self._schedule_search("species"))
        self.only_seen = tk.BooleanVar(self.window, False)
        tk.Checkbutton(toolbar, text=tr("只看有记录的鸟种"), variable=self.only_seen,
                       command=self._refresh_species, background=PAPER, foreground=SOFT,
                       activebackground=PAPER, selectcolor="#ffffff", highlightthickness=0, bd=0,
                       font=(self.family, 10), cursor="hand2").pack(side="left", padx=15)
        body = tk.Frame(self.species_tab, background=PAPER)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=4, minsize=300)
        body.columnconfigure(1, weight=6, minsize=400)
        body.rowconfigure(0, weight=1)
        from .species_cards import SpeciesCardList, prepare_card_tile
        self.cards_scroll = SpeciesCardList(body, self, on_drawn=self._list_drawn, thumbnail_loader=prepare_card_tile)
        self.cards_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.detail_scroll = _ScrollFrame(body)
        self.detail_scroll.grid(row=0, column=1, sticky="nsew")
        self._scrolls += [self.cards_scroll, self.detail_scroll]

    def _build_records(self):
        self.records_tab.columnconfigure(0, weight=1)
        self.records_tab.rowconfigure(1, weight=1, minsize=55)
        toolbar = tk.Frame(self.records_tab, background=PAPER)
        toolbar.grid(row=0, column=0, sticky="ew", pady=12)
        toolbar.columnconfigure(1, weight=1)
        self._label(toolbar, tr("搜索照片或鸟种"), 10, SOFT).grid(row=0, column=0, padx=(0, 10))
        self.record_query = tk.StringVar(self.window, "")
        ttk.Entry(toolbar, textvariable=self.record_query, width=35, style=f"{self.prefix}.TEntry",
                  font=(self.family, 11)).grid(row=0, column=1, sticky="ew", ipady=5)
        self.record_query.trace_add("write", lambda *args: self._schedule_search("records"))
        self.use_hero_button = self._button(toolbar, tr("用作首页观鸟图"), self.use_selected_hero)
        self.use_hero_button.grid(row=0, column=2, padx=(10, 6))
        self.undo_delete_button = self._button(toolbar, tr("撤回删除"), self.undo_last_delete)
        self.undo_delete_button.grid(row=0, column=3, padx=(0, 6))
        self._button(toolbar, tr("刷新"), self.refresh).grid(row=0, column=4)
        tree_frame = tk.Frame(self.records_tab, background=PAPER)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        columns = ("date", "photo", "birds", "place", "captured", "summary")
        self.record_tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                       style=f"{self.prefix}.Treeview", selectmode="extended", height=5)
        for key, title, width in (("date", tr("识别时间"), 145), ("photo", tr("照片名称"), 200),
                                  ("birds", tr("鸟框数"), 65), ("place", tr("拍摄地点"), 135),
                                  ("captured", tr("拍摄时间"), 145), ("summary", tr("识别摘要"), 280)):
            self.record_tree.heading(key, text=title)
            self.record_tree.column(key, width=width, minwidth=55, stretch=key in ("photo", "summary"))
        bar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.record_tree.yview)
        horizontal = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.record_tree.xview)
        self.record_tree.configure(yscrollcommand=bar.set, xscrollcommand=horizontal.set)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.record_tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.record_tree.tag_configure("odd", background=STRIPE)
        self.record_tree.bind("<Double-1>", self._open_selected_event)
        self.record_tree.bind("<Return>", self._open_selected_event)
        self.record_tree.bind("<<TreeviewSelect>>", self._select_record)
        self.record_tree.bind("<Delete>", self.delete_selected_record)
        self._build_capture_editor()
        bottom = tk.Frame(self.records_tab, background=PAPER)
        bottom.grid(row=3, column=0, sticky="ew", pady=12)
        bottom.columnconfigure(0, weight=1)
        self.record_hint = tk.StringVar(self.window, tr("Ctrl / Shift 可多选；Delete 删除，Ctrl+Z 撤回。"))
        hint = self._label(bottom, "", 10, SOFT, textvariable=self.record_hint,
                           anchor="w", wraplength=550, justify="left")
        hint.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.open_certificate_button = self._button(bottom, tr("查看这份鉴定证书"), self._open_selected_event, True)
        self.open_certificate_button.grid(row=0, column=2, sticky="e")
        self.delete_record_button = self._button(bottom, tr("删除所选记录"), self.delete_selected_record)
        self.delete_record_button.configure(foreground="#9c4535")
        self.delete_record_button.grid(row=0, column=1, sticky="e", padx=(0, 10))
        self.record_compare_button = self._button(bottom, tr("识别对比"), self._compare_record)
        self.record_compare_button.grid(row=0, column=3, sticky="e", padx=(10, 0))
        hint.bind("<Configure>", lambda event: hint.configure(wraplength=max(80, event.width)))
        self.source_filename = tk.StringVar(self.window, tr("来源文件：先选择一条档案"))
        self.source_filename_label = self._label(self.records_tab, "", 8, "#8a8f74",
            textvariable=self.source_filename, anchor="w", wraplength=1080, justify="left")
        self.source_filename_label.grid(row=4, column=0, sticky="ew", padx=2, pady=(0, 4))
        self.source_filename_label.bind("<Configure>", lambda event:
            self.source_filename_label.configure(wraplength=max(220, event.width - 5)))

    def _build_capture_editor(self):
        panel = tk.Frame(self.records_tab, background=CARD, highlightthickness=1, highlightbackground=LINE)
        panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        tk.Frame(panel, background=ACCENT, height=3).grid(row=0, column=0, columnspan=5, sticky="new")
        self.capture_selection = tk.StringVar(self.window, tr("照片信息 · 先选一条档案"))
        title = self._label(panel, "", 10, GREEN, True, textvariable=self.capture_selection,
                            anchor="w", wraplength=900)
        title.grid(row=0, column=0, columnspan=5, sticky="ew", padx=14, pady=(10, 7))
        title.bind("<Configure>", lambda e: title.configure(wraplength=max(300, e.width - 5)))
        self.capture_place = tk.StringVar(self.window, "")
        self.captured_at = tk.StringVar(self.window, "")
        self.photo_name = tk.StringVar(self.window, "")
        self.photo_name.trace_add("write", self._metadata_changed)
        self.capture_place.trace_add("write", self._metadata_changed)
        self.captured_at.trace_add("write", self._metadata_changed)
        self._label(panel, tr("照片名称"), 10, SOFT).grid(row=1, column=0, padx=(14, 8), sticky="w")
        self.photo_name_entry = ttk.Entry(panel, textvariable=self.photo_name, font=(self.family, 10),
                                          style=f"{self.prefix}.TEntry")
        self.photo_name_entry.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(0, 8))
        self._label(panel, tr("拍摄地点"), 10, SOFT).grid(row=2, column=0, padx=(14, 8), sticky="w")
        self.place_entry = ttk.Entry(panel, textvariable=self.capture_place, font=(self.family, 10),
                                     style=f"{self.prefix}.TEntry")
        self.place_entry.grid(row=2, column=1, sticky="ew")
        self._label(panel, tr("拍摄时间"), 10, SOFT).grid(row=2, column=2, padx=(16, 8), sticky="w")
        date_frame = tk.Frame(panel, background=CARD)
        date_frame.grid(row=2, column=3, sticky="ew")
        self.capture_time_entry = ttk.Entry(date_frame, textvariable=self.captured_at, width=16, state="readonly",
                                            font=(self.family, 10), style=f"{self.prefix}.TEntry")
        self.capture_time_entry.pack(side="left", fill="x", expand=True)
        self.capture_time_entry.bind("<Button-1>", self.open_calendar)
        self.capture_calendar_button = self._button(date_frame, tr("日历"), self.open_calendar)
        self.capture_calendar_button.pack(side="left", padx=(5, 0))
        self.save_capture_button = self._button(panel, tr("保存照片信息"), self.save_capture_metadata, True)
        self.save_capture_button.grid(row=1, column=4, rowspan=2, padx=14)
        self._label(panel, tr("备注"), 10, SOFT).grid(row=3, column=0, padx=(14, 8), sticky="nw", pady=(7, 0))
        self.notes_text = tk.Text(panel, height=2, font=(self.family, 10), background="white", foreground=INK,
                                  relief="flat", highlightthickness=1, highlightbackground=LINE,
                                  wrap="word", undo=True)
        self.notes_text.grid(row=3, column=1, columnspan=3, sticky="ew", pady=(7, 8))
        self.notes_text.bind("<<Modified>>", self._notes_changed)
        self.clear_capture_button = self._button(panel, tr("清空输入"), self.clear_capture_inputs)
        self.clear_capture_button.grid(row=3, column=4, padx=14, pady=(2, 8), sticky="e")
        panel.columnconfigure(1, weight=1)
        panel.columnconfigure(3, weight=1)
        for entry in (self.photo_name_entry, self.place_entry, self.capture_time_entry):
            entry.bind("<Return>", self.save_capture_metadata)

    def open_calendar(self, event=None):
        if not self._selected_event_id() or len(self.record_tree.selection()) != 1:
            return "break"
        if self._calendar is not None and self._calendar.winfo_exists():
            self._calendar.lift()
            return "break"
        from .calendar_picker import CalendarPicker
        self._calendar = CalendarPicker(self.window, self.captured_at.get(), self.captured_at.set, self.family)
        return "break"

    def _notes_changed(self, event=None):
        if self.notes_text.edit_modified():
            self.notes_text.edit_modified(False)
            self._metadata_changed()

    def _metadata_changed(self, *args):
        if not self._metadata_loading:
            self._metadata_dirty = True

    def _selected_event_id(self):
        selected = self.record_tree.selection()
        focused = self.record_tree.focus()
        key = focused if focused in selected else selected[0] if selected else None
        return self._events.get(key) if key else None

    def _selected_event_ids(self):
        return [self._events[key] for key in self.record_tree.selection() if key in self._events]

    def _select_record(self, event=None):
        event_id = self._selected_event_id()
        if event_id == self._capture_event_id and self._metadata_dirty and len(self.record_tree.selection()) == 1:
            return
        detail = self._record_summaries.get(event_id) if event_id else None
        multiple = len(self.record_tree.selection()) > 1
        self._capture_event_id = event_id if detail else None
        self._metadata_loading = True
        self.photo_name.set((detail or {}).get("display_name") or "")
        self.capture_place.set((detail or {}).get("capture_place") or "")
        self.captured_at.set((detail or {}).get("captured_at") or "")
        self.notes_text.configure(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", (detail or {}).get("notes") or "")
        self.notes_text.edit_reset()
        self.notes_text.edit_modified(False)
        self._metadata_loading = False
        self._metadata_dirty = False
        self.capture_selection.set(tr("照片信息 · ") + _photo_name(detail) if detail else
                                   tr("照片信息 · 先选一条档案"))
        if multiple:
            self.capture_selection.set(tr("已选 {0} 条档案 · 可批量删除；编辑请单选").format(len(self.record_tree.selection())))
        self.source_filename.set(tr("来源文件：") + str(detail.get("source_name") or tr("未记录")) if detail else
                                 tr("来源文件：先选择一条档案"))
        if multiple:
            self.source_filename.set(tr("已选 {0} 条档案；单选可查看各自来源文件。").format(len(self.record_tree.selection())))
        state = "normal" if detail and not multiple else "disabled"
        for widget in (self.photo_name_entry, self.place_entry, self.capture_calendar_button, self.notes_text,
                       self.save_capture_button, self.clear_capture_button):
            widget.configure(state=state)
        self.capture_time_entry.configure(state="readonly" if detail and not multiple else "disabled")
        self.delete_record_button.configure(state="normal" if detail else "disabled")
        self.open_certificate_button.configure(state=state)
        self.record_compare_button.configure(state=state if detail and detail.get("bird_count") else "disabled")
        self.use_hero_button.configure(state="normal" if detail and not multiple and self.on_use_hero else "disabled")

    def clear_capture_inputs(self):
        self.photo_name.set("")
        self.capture_place.set("")
        self.captured_at.set("")
        self.notes_text.delete("1.0", "end")
        self.record_hint.set(tr("输入已清空；点击保存后才会更新档案。"))

    def save_capture_metadata(self, event=None):
        event_id = self._selected_event_id()
        if not event_id or len(self.record_tree.selection()) != 1:
            self.record_hint.set(tr("先选择一条照片记录，再填写名称、拍摄地点与时间。"))
            return
        try:
            self.library.update_event_metadata(event_id, capture_place=self.capture_place.get(),
                                               captured_at=self.captured_at.get(), display_name=self.photo_name.get(),
                                               notes=self.notes_text.get("1.0", "end-1c"))
        except Exception as exc:
            messagebox.showerror(tr("照片信息未保存"), str(exc), parent=self.window)
            return
        self._metadata_dirty = False
        self.refresh()
        self.focus_archive(event_id)
        self.record_hint.set(tr("已保存，同一照片共用名称与拍摄信息；来源文件名保持不变。"))

    def delete_selected_record(self, event=None):
        ids = self._selected_event_ids()
        details = [self.library.event_detail(key) for key in ids]
        details = [item for item in details if item]
        if not details:
            self.record_hint.set(tr("先在档案中选择要删除的记录。"))
            return
        count = sum(item.get("bird_count", len(item.get("boxes") or [])) for item in details)
        names = "、".join(_photo_name(item) for item in details[:3]) + (tr("等") if len(details) > 3 else "")
        answer = messagebox.askyesno(tr("删除所选档案？"),
            tr("已选 {0} 条记录：{1}\n共 {2} 个鸟框。\n\n原照片和结果文件保留；删除后可按 Ctrl+Z 撤回。").format(len(details), names, count),
            parent=self.window, icon="warning", default="no")
        if not answer:
            return
        try:
            result = self.library.delete_events(ids)
        except Exception as exc:
            messagebox.showerror(tr("记录未删除"), str(exc), parent=self.window)
            return
        if (getattr(self, "_certificate_result", None) or {}).get("event_id") in ids:
            self._certificate_result = None
        self._capture_event_id = None
        self._metadata_dirty = False
        self.refresh()
        self.record_hint.set(tr("已删除 {0} 条档案；Ctrl+Z 可撤回，原照片未删除。").format(len(result.get('event_ids') or [])))
        return "break"

    def _undo_shortcut(self, event=None):
        widget = getattr(event, "widget", None) or self.window.focus_get()
        if isinstance(widget, (tk.Text, tk.Entry, ttk.Entry, ttk.Combobox)):
            return None
        self.undo_last_delete()
        return "break"

    def undo_last_delete(self):
        try:
            result = self.library.undo_delete()
        except Exception as exc:
            messagebox.showerror(tr("暂时无法撤回"), str(exc), parent=self.window)
            return
        if not result.get("restored"):
            self._ensure_tab("records")
            self.record_hint.set(tr("没有可以撤回的删除操作。"))
            return
        self.select_tab("records")
        self.refresh()
        ids = set(result.get("event_ids") or [])
        items = [item for item, key in self._events.items() if key in ids]
        self.record_tree.selection_set(items)
        self._select_record()
        self.select_tab("records")
        self.record_hint.set(tr("已撤回删除，恢复 {0} 条档案。").format(len(ids)))

    def use_selected_hero(self):
        if len(self.record_tree.selection()) != 1:
            self.record_hint.set(tr("请单选一张照片，再选择其中的鸟用作首页观鸟图。"))
            return
        detail = self.library.event_detail(self._selected_event_id())
        if detail and self.on_use_hero:
            self.on_use_hero(detail)

    def _schedule_search(self, page="species", *args):
        self._search_dirty.add(page)
        if self._query_after:
            self.window.after_cancel(self._query_after)
        self._query_after = self.window.after(160, self._run_search)

    def _run_search(self):
        self._query_after = None
        self._dirty_tabs.update(self._search_dirty)
        self._search_dirty.clear()
        self._refresh_tab(self._active_tab)

    def _clear(self, frame):
        for child in frame.winfo_children():
            child.destroy()

    def _select_species_group(self, group):
        if group not in self._species_group_buttons:
            return
        self.species_group.set(group)
        self.cards_scroll.canvas.yview_moveto(0)
        self._refresh_species()

    def _sync_species_groups(self, cards):
        current = self.species_group.get()
        for key, pill in self._species_group_buttons.items():
            count = sum(_species_group(card) == key for card in cards)
            title = tr("柳莺") if key == "willow" else tr("非柳莺")
            active = key == current
            pill.configure(text=f"{title} · {count}", background=GREEN if active else CARD,
                           foreground="white" if active else GREEN,
                           highlightbackground=GREEN if active else LINE)
        if current == "other":
            self._species_group_notice.pack(fill="x", before=self._species_toolbar,
                                            padx=2, pady=(10, 0))
        else:
            self._species_group_notice.pack_forget()

    def _refresh_species(self):
        self._ensure_tab("species")
        cards = self.library.species_cards(self.query.get().strip())
        if self.only_seen.get():
            cards = [card for card in cards if int(card.get("observation_count") or 0)]
        self._sync_species_groups(cards)
        self._cards = [card for card in cards if _species_group(card) == self.species_group.get()]
        self.cards_scroll.set_cards(self._cards, self._selected_species)
        if not self._cards:
            self._cancel_default_detail()
            self._species_panels.clear()
            self._current_panel = None
            self._selected_species = None
            self._shown_species_data = None
            self._clear(self.detail_scroll.body)
            self._label(self.detail_scroll.body, tr("换个鸟名或关键词试试。"), 12, SOFT).pack(pady=40)
        elif self._selected_species not in {item["scientific_name"] for item in self._cards}:
            self._cancel_default_detail()
            name = self._cards[0]["scientific_name"]
            if self._current_panel is not None:
                self._current_panel.pack_forget()
                self._current_panel = None
                self._shown_species_data = None
            self._selected_species = name
            self.cards_scroll.set_selected(name)
            self._default_name = name
            self.cards_scroll._schedule_draw()
        else:
            self.show_species(self._selected_species)

    def _list_drawn(self):
        if self._default_name is not None and self._default_detail is None:
            self._default_detail = self.window.after(1, self._finish_default_detail)

    def choose_species(self, name):
        # Let the highlight paint and coalesce quick mouse/keyboard changes.
        self._cancel_default_detail()
        self._selected_species = name
        self.cards_scroll.set_selected(name)
        self._default_name = name
        self._default_detail = self.window.after_idle(self._finish_default_detail)

    def _finish_default_detail(self):
        name, self._default_name = self._default_name, None
        self._default_detail = None
        if name and self._selected_species == name and not self._disposed:
            if self._active_tab == "species":
                self.show_species(name)
            else:
                self._dirty_tabs.add("species")

    def _cancel_default_detail(self):
        self._default_name = None
        if self._default_detail is not None:
            self.window.after_cancel(self._default_detail)
            self._default_detail = None

    def _resolve(self, reference):
        if not reference:
            return None
        try:
            resolver = getattr(self.library, "resolve_path", None)
            path = resolver(reference) if resolver else Path(reference)
            if path is None:
                return None
            path = Path(path)
            if not path.is_absolute():
                path = self.app_root / path
            return path if path.is_file() else None
        except (OSError, ValueError, TypeError):
            return None

    def _reference_image(self, species):
        # Reference portraits must be curated; a model-labelled observation may be
        # wrong and should never silently become the visual definition of a species.
        try:
            from . import art
            reference = art.find_reference_image(species.get("scientific_name"), species.get("common_name"))
            if reference:
                return reference["path"], art.reference_credit(reference)
            if self._photo_metadata is None:
                self._photo_metadata = art.load_photos()
            for photo in self._photo_metadata:
                if not photo.get("user") and photo.get("species_cn") == species.get("common_name"):
                    return photo["path"], tr("图鉴照片 · {0} · {1}").format(photo.get('author', ''), photo.get('license', ''))
            path = self._resolve(species.get("image_path"))
            if path:
                return path, tr("图鉴插图 · 《两岸三地50种柳莺类辨识》")
            plate = art.find_plate(species.get("scientific_name"), species.get("common_name"))
            if plate:
                return plate.get("bird_path") or plate["path"], tr("图鉴插图 · 《两岸三地50种柳莺类辨识》")
        except (OSError, ValueError, ImportError):
            pass
        path = self._resolve(species.get("representative_image"))
        if path:
            return path, tr("本地识别裁图 · 鸟种待人工核实")
        return None, tr("尚无本地图鉴图片")

    def _image(self, path, size, cover=False, radius=0, background=CARD):
        try:
            stat = Path(path).stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size, tuple(size), cover, radius, background)
            if key in self._images:
                self._images.move_to_end(key)
                return self._images[key]
            from PIL import ImageTk
            from .display_images import load_thumbnail
            image = load_thumbnail(path, size, cover=cover)
            if radius:
                image = _rounded(image, radius, background)
            photo = ImageTk.PhotoImage(image, master=self.window)
            self._images[key] = photo
            while len(self._images) > 64:
                self._images.popitem(last=False)
            return photo
        except (OSError, ValueError):
            return None

    def _section(self, parent, title, text):
        self._label(parent, title, 10, GREEN, True, anchor="w").pack(fill="x", pady=(18, 6))
        label = self._label(parent, _text(text), 10, INK, anchor="w", justify="left", wraplength=540)
        label.pack(fill="x")
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(220, event.width - 6)))

    def _field_notes(self, parent, sections):
        # A single native window holds the read-only guide paragraphs. Buttons,
        # editable records and source links remain individual focusable widgets.
        notes = tk.Canvas(parent, background=CARD, width=1, height=1, highlightthickness=0, bd=0)
        notes.pack(fill="x")
        pairs = [(notes.create_text(0, 0, text=title, anchor="nw", fill=GREEN,
                                    font=(self.family, 10, "bold")),
                  notes.create_text(0, 0, text=_text(value), anchor="nw", fill=INK,
                                    font=(self.family, 10))) for title, value in sections]
        drawn_width = None
        def layout(event):
            nonlocal drawn_width
            if drawn_width == event.width or event.width < 8:
                return
            drawn_width = event.width
            y = 0
            for title, body in pairs:
                notes.coords(title, 2, y + 18)
                notes.coords(body, 2, notes.bbox(title)[3] + 5)
                notes.itemconfigure(body, width=event.width - 6)
                y = notes.bbox(body)[3] + 2
            notes.configure(height=max(y, 1))
        notes.bind("<Configure>", layout)

    def show_species(self, scientific_name):
        self._cancel_default_detail()
        self._ensure_tab("species")
        species = self.library.species_detail(scientific_name)
        # Certificate/home-page links can target an archived species outside the
        # current group or search. Reveal it without leaving a mismatched list.
        if species and (_species_group(species) != self.species_group.get() or
                        scientific_name not in {card["scientific_name"] for card in self._cards}):
            self.species_group.set(_species_group(species))
            self.query.set("")
            self.only_seen.set(False)
            self._selected_species = scientific_name
            self.cards_scroll.canvas.yview_moveto(0)
            self._refresh_species()
        self._selected_species = scientific_name
        self.cards_scroll.set_selected(scientific_name)
        body = self.detail_scroll.body
        if not species:
            self._species_panels.clear()
            self._current_panel = self._shown_species_data = None
            self._clear(body)
            self._label(body, tr("这条鸟种资料尚未建立。"), 12, SOFT).pack(pady=30)
            return
        path, credit = self._reference_image(species)
        width = self.detail_scroll.canvas.winfo_width()
        if width < 200:
            width = int((self._initial_width - 60) * .6) - 30
        width = max(360, width - 10)
        try:
            stat = Path(path).stat() if path else None
        except OSError:
            stat = None
        stamp = (width, path, stat.st_mtime_ns if stat else None, stat.st_size if stat else None)
        previous = self._species_panels.get(scientific_name)
        valid = previous and previous[:2] == (species, stamp)
        if valid and previous[2] is self._current_panel:
            return
        if self._current_panel is not None:
            self._current_panel.pack_forget()
        elif not self._species_panels:
            self._clear(body)
        self.detail_scroll.canvas.yview_moveto(0)
        self._shown_species_data = species
        if valid:
            self._current_panel = previous[2]
            self._species_panels.move_to_end(scientific_name)
            self._current_panel.pack(fill="x", padx=(1, 6), pady=(0, 12))
            return
        if previous:
            previous[2].destroy()
        card = self._current_panel = tk.Frame(body, background=CARD, highlightthickness=1, highlightbackground=LINE)
        self._species_panels[scientific_name] = (species, stamp, card)
        self._species_panels.move_to_end(scientific_name)
        if len(self._species_panels) > 3:
            self._species_panels.popitem(last=False)[1][2].destroy()
        card.pack(fill="x", padx=(1, 6), pady=(0, 12))
        photo = self._image(path, (width, 230), cover=not bool(species.get("reference_image"))) if path else None
        if photo:
            hero = self._label(card, "", image=photo, cursor="hand2")
            hero.pack(fill="x")
            hero.bind("<Button-1>", lambda e, p=path: self._open_image(p, species.get("common_name") or scientific_name))
        inner = tk.Frame(card, background=CARD)
        inner.pack(fill="x", padx=24, pady=(16, 22))
        if photo:
            self._label(inner, credit, 8, "#8a8f74", anchor="e", wraplength=500).pack(fill="x", pady=(0, 6))
        title_row = tk.Frame(inner, background=CARD)
        title_row.pack(fill="x")
        title_row.columnconfigure(0, weight=1)
        names = tk.Frame(title_row, background=CARD)
        names.grid(row=0, column=0, sticky="ew")
        compare_button = self._button(title_row, tr("识别对比"), lambda: self._compare_birds([species]))
        compare_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        name_label = self._label(names, species_name(species.get("common_name"), scientific_name), 26, GREEN, True, anchor="w")
        name_label.grid(row=0, column=0, sticky="w")
        willow = _species_group(species) == "willow"
        badge = tk.Label(names, text=tr("柳莺专项") if willow else tr("非柳莺 · 识别仅供参考"), padx=10, pady=2,
                 background=SELECT if willow else MUTED, foreground=GREEN if willow else SOFT,
                 font=(self.family, 9, "bold"))
        badge.grid(row=0, column=1, sticky="w", padx=(12, 0))
        title_width = name_label.winfo_reqwidth()
        def fit_names(event):
            compact = title_width + badge.winfo_reqwidth() + 12 > event.width
            badge.grid_configure(row=1 if compact else 0, column=0 if compact else 1,
                                 padx=0 if compact else (12, 0))
            name_label.configure(wraplength=max(1, event.width) if title_width > event.width else 0)
        names.bind("<Configure>", fit_names)
        self._label(inner, scientific_name, 12, SOFT, anchor="w",
                    font=(self.family, 12, "italic")).pack(fill="x", pady=(2, 0))
        self._label(inner, species.get("english_name") or tr("英文名待补充"), 10, "#8a8f74", anchor="w").pack(fill="x")
        # Let the image, title, and comparison button map before long field notes.
        pending = None
        def render():
            nonlocal pending
            pending = None
            if card.winfo_viewable() and self._current_panel is card:
                card.unbind("<Map>", mapping)
                self._species_notes(inner, species, credit, bool(photo))
        def mapped(event):
            nonlocal pending
            if pending is None:
                pending = card.after(1, render)
        def cancel(event):
            nonlocal pending
            if pending is not None:
                card.after_cancel(pending)
                pending = None
        mapping = card.bind("<Map>", mapped)
        card.bind("<Unmap>", cancel)
        card.bind("<Destroy>", cancel)

    def _species_notes(self, inner, species, credit, has_photo):
        scientific_name = species["scientific_name"]
        stats = tk.Frame(inner, background=CARD)
        stats.pack(fill="x", pady=(14, 4))
        for number, unit in ((int(species.get("observation_count") or 0), tr("次本地识别")),
                             (int(species.get("image_count") or 0), tr("张照片")),
                             (len(species.get("audio") or []), tr("段本地录音"))):
            box = tk.Frame(stats, background=STRIPE, highlightthickness=1, highlightbackground=LINE)
            box.pack(side="left", padx=(0, 10))
            tk.Label(box, text=str(number), background=STRIPE, foreground=GREEN,
                     font=(self.family, 16, "bold")).pack(side="left", padx=(12, 4), pady=6)
            tk.Label(box, text=unit, background=STRIPE, foreground=SOFT,
                     font=(self.family, 9)).pack(side="left", padx=(0, 12))
        if not has_photo:
            self._label(inner, credit, 8, SOFT, wraplength=500).pack(fill="x")
        audio_row = tk.Frame(inner, background=CARD)
        audio_row.pack(fill="x", pady=(15, 0))
        audio = species.get("audio") or []
        button = self._button(audio_row, tr("播放 / 停止鸟叫"), lambda: self._play(scientific_name), True)
        button.pack(side="left")
        if not audio or not self.on_play:
            button.configure(state="disabled", cursor="")
        self._label(audio_row, tr("本地录音") if audio else tr("该鸟种暂无本地录音"), 9, SOFT).pack(side="left", padx=12)
        if audio:
            first = audio[0] if isinstance(audio, list) else audio
            if isinstance(first, dict):
                self._label(inner, " · ".join(str(first.get(key) or "") for key in ("title", "author", "license") if first.get(key)),
                            8, SOFT, anchor="w", wraplength=500, justify="left").pack(fill="x", pady=(6, 0))
        sections = []
        for title, keys in (("中国分布与迁徙", ("distribution", "china_distribution", "range")),
                             ("栖息环境", ("habitat",)), ("辨识要点", ("identification", "description")),
                             ("声音", ("voice", "calls", "call_description")),
                             ("录音说明", ("voice_recording_note",)),
                             ("观察要点", ("observation_tips",)),
                             ("取食", ("diet", "feeding")), ("行为", ("behavior",)),
                             ("易混淆种", ("similar_species",)),
                             ("保护信息", ("conservation",)), ("季节信息", ("seasonality",)),
                             ("分类与名称说明", ("taxonomic_note", "taxonomy_note", "notes"))):
            value = next((species.get(key) for key in keys if species.get(key)), None)
            if title in {"分类与名称说明", "取食", "行为", "易混淆种", "保护信息", "季节信息", "录音说明", "观察要点"} and not value:
                continue
            sections.append((title, value))
        self._field_notes(inner, [(tr(title), value) for title, value in sections])
        observations = species.get("observations") or []
        places = list(dict.fromkeys(str(item.get("capture_place") or "").strip()
                                    for item in observations if str(item.get("capture_place") or "").strip()))
        captured = {item.get("event_id") or str(index): item.get("captured_at") for index, item in enumerate(observations)
                    if item.get("captured_at")}
        summary = []
        if places:
            summary.append(tr("已记录拍摄地点：") + "、".join(places))
        if captured:
            times = sorted(captured.values())
            summary.append(tr("{0} 份档案填写了拍摄时间：").format(len(captured)) +
                           (_date(times[0]) if times[0] == times[-1] else tr("{0} 至 {1}").format(_date(times[0]), _date(times[-1]))))
        self._section(inner, tr("本地拍摄信息"), "\n".join(summary) if summary else
                      tr("还没有填写拍摄地点或时间；可在「翻翻档案」选中照片后补充。"))
        self._section(inner, tr("最近的识别记录"), tr("暂无本地记录") if not observations else
                      tr("点击下面的记录，可查看当时的照片与逐鸟预测。"))
        recent = {}
        for index, observation in enumerate(observations):
            key = observation.get("event_id") or f"observation_{index}"
            if key not in recent:
                recent[key] = {**observation, "_species_boxes": 0}
            recent[key]["_species_boxes"] += 1
        for observation in list(recent.values())[:8]:
            event_id = observation.get("event_id")
            capture = _date(observation.get("captured_at")) if observation.get("captured_at") else tr("拍摄时间未填")
            place = observation.get("capture_place") or tr("拍摄地点未填")
            text = _photo_name(observation) + f"\n{capture} · {place}"
            if observation.get("notes"):
                text += tr("\n备注：") + str(observation["notes"])
            if observation["_species_boxes"] > 1:
                text += tr(" · {0} 个该鸟种记录").format(observation['_species_boxes'])
            link = self._label(inner, text, 10, GREEN, anchor="w", cursor="hand2", justify="left", wraplength=500)
            link.pack(fill="x", pady=4)
            link.bind("<Configure>", lambda event, widget=link: widget.configure(wraplength=max(220, event.width - 5)))
            link.bind("<Button-1>", lambda event, value=event_id: self.focus_archive(value))
        self._sources(inner, species)

    def _sources(self, parent, species):
        sources = species.get("source_urls") or species.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        sources = list(sources)
        reference = species.get("reference_image") or {}
        if reference.get("source"):
            sources.append({"url": reference["source"], "title": tr("参考图片来源 · ") + str(reference.get("author") or "")})
        if reference.get("license_url"):
            sources.append({"url": reference["license_url"], "title": tr("参考图片许可 · ") + str(reference.get("license") or "")})
        for clip in species.get("audio") or []:
            if isinstance(clip, dict) and clip.get("source_url"):
                sources.append({"url": clip["source_url"],
                                "title": tr("录音来源 · ") + str(clip.get("author") or clip.get("title") or tr("野外录音"))})
        self._section(parent, tr("资料来源"), tr("图鉴文字为资料摘要；分类名称沿用当前模型标签。"))
        for source in sources:
            if isinstance(source, dict):
                url = source.get("url") or source.get("source_url")
                title = source.get("title") or source.get("name") or url
            else:
                url, title = str(source), str(source)
            if not url or not str(url).startswith(("https://", "http://")):
                continue
            label = self._label(parent, title, 9, GREEN, cursor="hand2", anchor="w",
                                wraplength=510, justify="left")
            label.pack(fill="x", pady=4)
            label.bind("<Configure>", lambda event, widget=label: widget.configure(wraplength=max(220, event.width - 6)))
            label.bind("<Button-1>", lambda event, target=url: webbrowser.open(target))

    def _play(self, scientific_name):
        if self.on_play:
            try:
                self.on_play(scientific_name)
            except Exception as error:
                messagebox.showerror(tr("鸟叫暂时无法播放"), str(error), parent=self.window)

    def _refresh_records(self):
        self._ensure_tab("records")
        records = self.library.events(query=self.record_query.get().strip())
        if records == self._records_signature:
            return
        self._records_signature = records
        self._record_summaries = {str(record["event_id"]): record for record in records}
        previous = set(self._selected_event_ids()) if hasattr(self, "_events") else set()
        self.record_tree.delete(*self.record_tree.get_children())
        self._events = {}
        selected = []
        for index, record in enumerate(records):
            event_id = str(record.get("event_id") or record.get("id") or index)
            item = f"event_{index}"
            self._events[item] = event_id
            self.record_tree.insert("", "end", iid=item, values=(
                _date(record.get("created_at")), _photo_name(record),
                record.get("bird_count", len(record.get("boxes") or [])), record.get("capture_place") or tr("未填写"),
                record.get("captured_at") or tr("未填写"), result_message(record.get("message")) or record.get("status", "")),
                tags=("odd",) if index % 2 else ())
            if event_id in previous:
                selected.append(item)
        if not selected and records:
            selected = ["event_0"]
        if selected:
            self.record_tree.selection_set(selected)
        self._select_record()
        self.record_hint.set(tr("共 {0} 条记录；Ctrl / Shift 多选，Delete 删除，Ctrl+Z 撤回。").format(len(records)) if records else
                             tr("还没有匹配的记录；新识别的结果会自动保存到这里。"))

    def _compare_birds(self, birds):
        if not birds:
            return
        from .plate_compare import PlateComparison
        self._close_comparison()
        self._comparison = PlateComparison(self, birds)

    def _close_comparison(self):
        if self._comparison is not None and self._comparison.winfo_exists():
            self._comparison.destroy()
        self._comparison = None

    def _compare_record(self):
        if len(self.record_tree.selection()) == 1:
            record = self.library.event_detail(self._selected_event_id())
            self._compare_birds((record or {}).get("boxes") or [])

    def _open_selected_event(self, event=None):
        selection = self.record_tree.selection()
        if selection:
            self.show_event(self._events.get(selection[0]))
        elif self.record_tree.get_children():
            first = self.record_tree.get_children()[0]
            self.record_tree.selection_set(first)
            self.show_event(self._events.get(first))

    def focus_archive(self, event_id):
        """A species-card history link opens the archive editor for that photo."""
        self._ensure_tab("records")
        detail = self.library.event_detail(event_id) if event_id is not None else None
        if not detail:
            self.record_hint.set(tr("这条档案已删除或暂不可用。"))
            self.select_tab("records")
            return
        self.record_query.set("")
        if self._query_after is not None:
            self.window.after_cancel(self._query_after)
            self._query_after = None
        self._dirty_tabs.update(self._search_dirty)
        self._search_dirty.clear()
        self._refresh_records()
        self.select_tab("records")
        for item, key in self._events.items():
            if key == event_id:
                self.record_tree.selection_set(item)
                self.record_tree.focus(item)
                self.record_tree.see(item)
                self._select_record()
                self.record_hint.set(tr("已定位这张照片，可在下方修改名称、拍摄地点与时间。"))
                break

    def show_event(self, event_id):
        result = self.library.event_detail(event_id) if event_id is not None else None
        if result:
            self._certificate_result = result
            self._dirty_tabs.discard("certificate")
            self._show_certificate(result)
            self.select_tab("certificate")

    def _show_certificate(self, result):
        self._ensure_tab("certificate")
        if self._certificate_rendered and result == self._rendered_certificate:
            return
        self._rendered_certificate = result
        self._certificate_rendered = True
        from .certificate import render_certificate
        return render_certificate(self, result)



    def _go_species(self, scientific_name):
        self.show_species(scientific_name)
        self.select_tab("species")

    def _bind_zoom(self, label, path, title):
        label.configure(cursor="hand2", takefocus=True)
        label._zoom_path, label._zoom_title = str(path), title
        callback = lambda event: self._open_image(path, title)
        label.bind("<Button-1>", callback)
        label.bind("<Return>", callback)
        label.bind("<space>", callback)
        self._certificate_images.append(label)

    def _open_image(self, path, title=tr("查看图片"), parent=None):
        try:
            path = Path(path).resolve()
            if not path.is_file():
                raise FileNotFoundError(tr("这张本地图片已移走。"))
            viewer = _ImageViewer(parent or self.window, path, title, self.family)
            self._viewers = [item for item in self._viewers if item.winfo_exists()]
            self._viewers.append(viewer)
            return viewer
        except (OSError, ValueError, tk.TclError) as exc:
            messagebox.showerror(tr("图片暂时无法打开"), str(exc), parent=self.window)
            return None

    def _mousewheel(self, event):
        for scroll in self._scrolls:
            if scroll.winfo_ismapped() and scroll.contains_pointer(event.x_root, event.y_root):
                scroll.canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
                return "break"

    def select_tab(self, name):
        name = name if name in self.tabs else "species"
        if name != "certificate":
            self._pause_certificate()
        self._active_tab = name
        self._ensure_tab(name)
        self.notebook.select(self.tabs[name])
        self._refresh_tab(name)
        self._sync_tabs()

    def present(self, tab="species", result=None):
        """Reopen the retained window without throwing away views or edits."""
        self._active_tab = tab if tab in self.tabs else "species"
        self.refresh(result=result)
        self.select_tab(self._active_tab)
        self.window.deiconify()
        self.window.lift()
        self.window.focus_set()

    def refresh(self, result=None):
        self._dirty_tabs.update(self.tabs)
        species_count, count = self.library.card_counts()
        summary = tr("{0} 张鸟种卡  ·  {1} 次逐鸟记录").format(species_count, count)
        if self.summary.get() != summary:
            self.summary.set(summary)
        if result is not None:
            self._certificate_result = result
        if self.window.winfo_viewable():
            self._ensure_tab(self._active_tab)
            self._refresh_tab(self._active_tab)

    def close(self):
        """Hide the archive; retain bounded display caches for the next opening."""
        if not self._disposed:
            from .certificate import cancel_pending_render
            cancel_pending_render(self)
            self._dirty_tabs.add("certificate")
            self._close_comparison()
            self.window.withdraw()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._cancel_default_detail()
        self._species_panels.clear()
        self._current_panel = None
        self._close_comparison()
        from .certificate import cancel_pending_render
        cancel_pending_render(self)
        if "species" in self._built_tabs:
            self.cards_scroll.close()
        for timer in (self._query_after, self._banner_after):
            if timer is not None:
                try:
                    self.window.after_cancel(timer)
                except tk.TclError:
                    pass
        self._images.clear()
        if self._calendar is not None and self._calendar.winfo_exists():
            self._calendar.destroy()
        for viewer in self._viewers:
            if viewer.winfo_exists():
                viewer.destroy()
        self._viewers.clear()
        self.window.destroy()


def open_library(parent, library, app_root, **kwargs):
    return LibraryWindow(parent, library, app_root, **kwargs)
