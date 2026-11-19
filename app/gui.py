"""「某种柳莺」鉴定所 — meme-flavoured Tk front end; model imports stay in the worker.

All recognition logic, routing and wording that carries scientific meaning
(gate messages, OTHER, coverage notes) is passed through unchanged; only the
packaging around it got silly.
"""
from copy import deepcopy
import json
import logging
from pathlib import Path
import queue
import random
import threading
import tkinter as tk
from tkinter import filedialog, ttk, font as tkfont
import time

from . import art
from . import release
from .scene import BirdScene, paint_branches

DETECTION_MODES = {"普通整图": "normal", "分块补检": "tiled"}
DEVICE_MODES = {"auto": "auto", "cuda": "cuda", "CPU（专项未验证）": "cpu"}
GATE_LABELS = {"willow": "柳莺", "confirmed_willow": "柳莺", "not_willow": "非柳莺",
               "negative": "非柳莺", "uncertain": "无法确认", "unknown": "无法确认",
               "no_bird": "未发现鸟", "error": "识别失败",
               "willow_outside_coverage": "柳莺（覆盖外）"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# ------------------------------------------------------------------ meme copy
# Call / song transcriptions, from 《中国鸟类野外手册》 (MacKinnon & Phillipps) species accounts;
# 欧柳莺 is not in that guide, its "hoo-eet" contact call is the standard European field-guide rendering.
SPECIES_CALLS = {
    "黄眉柳莺": "swe-eeet! swe-eeet!",
    "黄腰柳莺": "choo-choo-chee-chee-chee",
    "冕柳莺": "pichi-pichu-seu-sweu",
    "极北柳莺": "dzit.",
    "叽喳柳莺": "chi-vit, chi-vit, chi-vit",
    "欧柳莺": "hoo-eet?",
}
TOOL_TIPS = (
    "鸟在照片里很小的话，左下角「找鸟方式」改成「分块补检」",
    "点右上角喇叭听叫声；点鸟看名字，再点换一只",
    "「翻翻档案」里有本地鸟种卡、识别次数和历史鉴定记录",
    "自己拍的柳莺照片放进 assets/backgrounds，就会出现在上面",
)
LOADING_LINES = (
    "正在数眉纹……", "正在数翼斑：一道……两道……还是三道？", "正在放大到 800% 看腰黄不黄",
    "正在翻《中国鸟类野外手册》……", "正在群里 @ 大佬……大佬已读不回", "正在假装听到了叫声",
    "正在排除「其实是一片叶子」的可能", "柳莺在乱动，正在努力对焦", "正在和 1343 种鸟逐个对暗号",
    "正在怀疑鸟生……", "正在比对头顶有没有顶冠纹", "第一次要加载模型，柳莺不急你也别急",
)
SPINNER = ("(・_・ )", "( ・_・)", "(・_・ )", "(￣～￣;)", "(・ω・)", "(°ー°〃)")
PHOTO_STATES = {"pending": "待鉴定", "queued": "排队中", "running": "盯着看", "done": "鉴定完",
                "failed": "翻车了", "cancelled": "已取消"}
TIPS = {
    "willow": "想确认具体种类，录一段叫声最管用。",
    "not_willow": "这只不在 50 种柳莺里，安心去认别的鸟吧。",
    "uncertain": "照片太小、太糊或者角度不好时常见，换张清楚的再试。",
}

# ------------------------------------------------------------------ colours
def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


CARD = _hex(art.CARD)
INK = _hex(art.INK)
INK_SOFT = _hex(art.INK_SOFT)
OLIVE = _hex(art.OLIVE)
YELLOW = _hex(art.YELLOW)
RED = _hex(art.STAMP_RED)
FIELD = "#fffef9"
HEAD_BG = "#eef2d6"
SELECT_BG = "#e2ecc0"
KIND_COLORS = {"willow": ("#3d7a1f", (61, 122, 31)), "not_willow": ("#5d6672", (93, 102, 114)),
               "uncertain": ("#b8740a", (196, 128, 14)), "no_bird": ("#6b7280", (107, 114, 128)),
               "error": (RED, art.STAMP_RED), "pending": (INK, art.INK)}
STAMPS = {"willow": ("某种柳莺", "鉴定完毕 · 别问哪种"),
          "not_willow": ("根本没有这种柳莺", "不是柳莺，散了散了"),
          "uncertain": ("薛定谔的柳莺", "可能是，也可能不是"),
          "no_bird": ("鸟呢？", "没检出鸟 ≠ 没有柳莺"),
          "error": ("翻车了", "去 logs 里看看日志")}


def _pick_family(root):
    families = set(tkfont.families(root))
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
                 "Source Han Sans SC", "WenQuanYi Micro Hei", "SimHei"):
        if name in families:
            return name
    return tkfont.nametofont("TkDefaultFont", root).actual("family")


def result_kind(result):
    """Classify a photo result for the fun layer only (does not change any data)."""
    if result is None:
        return "pending"
    if result.get("status") == "error":
        return "error"
    boxes = result.get("boxes") or []
    if not boxes:
        return "no_bird"
    gates = [b.get("gate_status") for b in boxes]
    if any(g in ("willow", "willow_outside_coverage") for g in gates):
        return "willow"
    if all(g == "not_willow" for g in gates):
        return "not_willow"
    return "uncertain"


def _specialist_names(result):
    names = []
    for box in (result or {}).get("boxes", []):
        expert = box.get("specialist") or {}
        if (box.get("gate_status") == "willow" and not expert.get("rejected_as_OTHER", True)
                and (expert.get("class_index") is not None or expert.get("global_id", -1) != -1) and expert.get("common_name")):
            names.append(str(expert["common_name"]))
    return list(dict.fromkeys(names))


def _specialist_outgroups(result):
    return list(dict.fromkeys(box["specialist"]["common_name"] for box in (result or {}).get("boxes", [])
        if (box.get("specialist") or {}).get("decision_kind") == "similar_non_willow"))


def bird_label(box):
    status = box.get("gate_status")
    expert = box.get("specialist") or {}
    if status == "willow_outside_coverage":
        return "柳莺（覆盖外）"
    if status == "willow":
        if expert.get("decision_kind") == "similar_non_willow":
            return f"专项倾向组外：{expert['common_name']}"
        if expert and not expert.get("rejected_as_OTHER") and (expert.get("class_index") is not None or expert.get("global_id", -1) != -1) and expert.get("common_name"):
            return f"柳莺！专项猜：{expert['common_name']}"
        return "柳莺！具体哪种：某种"
    if status == "not_willow":
        return "根本没有这种柳莺"
    if status in ("uncertain", "unknown"):
        return "薛定谔的柳莺"
    return box.get("gate_message") or GATE_LABELS.get(status, status or "无法确认")


class RecognitionWorker(threading.Thread):
    def __init__(self, events, factory=None):
        super().__init__(name="willow-recognition", daemon=False)
        self.events, self.factory, self.commands = events, factory, queue.Queue()
        self.engine, self.engine_key = None, None

    def _close_engine(self):
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception as exc:
                self.events.put(("log", f"关闭模型：{exc}"))
            self.engine = self.engine_key = None

    def run(self):
        try:
            while True:
                job = self.commands.get()
                if job is None:
                    return
                key, source, package, device, mode, output, config = job
                self.events.put(("started", key))
                try:
                    engine_key = (str(Path(package).resolve()), device)
                    if self.engine_key != engine_key:
                        self._close_engine()
                        factory = self.factory
                        if factory is None:
                            from .backend import WillowOnlyEngine
                            factory = WillowOnlyEngine
                        self.engine = factory(package, device=device,
                            progress=lambda message: self.events.put(("progress", key, str(message))),
                            config=deepcopy(config))
                        self.engine_key = engine_key
                    result = self.engine.recognize(source, output, detection_mode=mode)
                    self.events.put(("done", key, result))
                except Exception as exc:
                    self.events.put(("failed", key, f"{type(exc).__name__}: {exc}"))
        finally:
            self._close_engine()
            self.events.put(("stopped",))


class WillowApplication:
    def __init__(self, window, app_root, package_root, *, engine_factory=None,
                 initial_images=(), config=None, instance=None):
        self.window, self.app_root = window, Path(app_root).resolve()
        self.instance = instance
        self.exit_dialog = self.tray = None
        self.backgrounded = self._background_pending = False
        self._resident_id = None
        self._hidden_children = []
        self.config = deepcopy(config or {})
        self.output_root = self.app_root / "results"
        self.settings_path = self.app_root / "config/settings.json"
        self.output_root.mkdir(parents=True, exist_ok=True)
        logdir = self.app_root / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(f"willow_gui_{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.handler = logging.FileHandler(logdir / "gui.log", encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(self.handler)
        self.release_info = None
        self._release_result = None
        self._release_pending = False
        self._release_dialog = None
        self._release_timer = None
        try:
            self.release_info = release.ReleaseInfo.load(self.app_root)
        except (OSError, ValueError) as error:
            self.logger.warning("读取发布配置失败：%s", error)
        settings = {}
        if self.settings_path.is_file():
            try:
                settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.logger.warning("无法读取设置，使用默认值")
        self.package = tk.StringVar(window, str(self.config.get("_resolved_package_root") or
                                               settings.get("package_root") or package_root or ""))
        saved_device = settings.get("device", "auto")
        self.device = tk.StringVar(window, "CPU（专项未验证）" if saved_device == "cpu" else saved_device)
        self.detection_mode = tk.StringVar(window, settings.get("detection_mode", "普通整图"))
        if self.device.get() not in DEVICE_MODES:
            self.device.set("auto")
        if self.detection_mode.get() not in DETECTION_MODES:
            self.detection_mode.set("普通整图")
        self.status = tk.StringVar(window, "投喂几张疑似柳莺的照片，再点「开始鉴定！」—— 每只鸟都会单独审问。")
        self.audio_source = tk.StringVar(window, "")
        self.photo_message = tk.StringVar(window, "")
        self.verdict = tk.StringVar(window, "")
        self.details = tk.StringVar(window, "先在左边点一张照片，再在「逐只审问」里点一只鸟。")
        self._detail_lines = None
        self.jobs, self.results, self.active = {}, {}, set()
        self.batch_keys = []
        self.current_result, self.current_bird = None, None
        self.preview_photo = self.crop_photo = None
        self.stamp_photo = self.placeholder_photo = None
        self._flow_photos = []
        self.busy = self.closing = self.closed = False
        self.running_key = None
        self.last_progress = ""
        self._tick = 0
        self._loading_line = random.choice(LOADING_LINES)
        self._anim_id = self._bg_id = self._preview_id = None
        self._bg_size = None
        self._wall_key = self._wall_base = self._wall_bird = None
        self._bg_cursor = ""
        self._images = []  # keep PhotoImage references alive
        self.library = None
        self.library_window = None
        self._startup_library = None
        self._audio_species = None
        self._audio_common_name = None
        self._audio_id = None
        self._audio_is_playing = False
        self.call_box = None
        self._carousel_id = None
        self._hero_picker = None
        from .audio import BirdAudioPlayer
        self.audio = BirdAudioPlayer(self.app_root)
        self.scene = None
        self.events = queue.Queue()
        self.worker = RecognitionWorker(self.events, engine_factory)
        if (self.app_root / "config/hero_gallery.json").is_file():
            # A saved gallery needs the archive. Overlap its import with Tk setup.
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="willow-library") as pool:
                self._startup_library = pool.submit(self._load_library)
                try:
                    self._build_ui()
                finally:
                    try:
                        self.library = self._startup_library.result()
                    except Exception as exc:
                        self.logger.warning("档案预读失败：%s", exc)
                    self._startup_library = None
        else:
            self._build_ui()
        try:
            self.scene = BirdScene(self)
        except Exception as exc:
            self.logger.warning("小鸟动画未启动：%s", exc)
            self.title_img = art.brand_title(self._px(66))
        self.worker.start()
        self.poll_id = self.window.after(40, self._poll)
        self._anim_id = self.window.after(450, self._animate)
        self._audio_id = self.window.after(200, self._poll_audio)
        self._reset_carousel()
        self.window.protocol("WM_DELETE_WINDOW", self.request_close)
        self._resident_id = self.window.after(120, self._resident_poll)
        self.add_paths(initial_images)
        if self.release_info and self.release_info.repository and self.release_info.check_on_startup:
            self._release_timer = self.window.after(2000, self._check_release_on_startup)

    # ================================================================ UI build
    def _px(self, value):
        return int(round(value * self.s))

    def _setup_style(self):
        w = self.window
        style = self.style = ttk.Style(w)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        fam = self.family
        self.f_body = (fam, 10)
        self.f_bold = (fam, 10, "bold")
        self.f_head = (fam, 12, "bold")
        self.f_verdict = (fam, 16, "bold")
        w.option_add("*TCombobox*Listbox.font", self.f_body)
        w.option_add("*TCombobox*Listbox.selectBackground", SELECT_BG)
        w.option_add("*TCombobox*Listbox.selectForeground", INK)
        style.configure(".", font=self.f_body, background=CARD, foreground=INK)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=self.f_body)
        style.configure("Soft.TLabel", background=CARD, foreground=INK_SOFT, font=(self.family, 9))
        style.configure("Head.TLabel", background=CARD, foreground=OLIVE, font=self.f_head)
        rowh = max(self._px(28), tkfont.Font(w, font=self.f_body).metrics("linespace") + self._px(10))
        tree = self.tree_style = f"Willow{id(self)}.Treeview"
        style.configure(tree, background=FIELD, fieldbackground=FIELD, foreground=INK, rowheight=rowh,
                        font=self.f_body, borderwidth=0, relief="flat", bordercolor=CARD,
                        lightcolor=CARD, darkcolor=CARD)
        style.map(tree, background=[("selected", SELECT_BG)], foreground=[("selected", INK)])
        style.configure(tree + ".Heading", background=HEAD_BG, foreground=OLIVE, font=self.f_bold,
                        relief="flat", borderwidth=0, padding=(6, 4), bordercolor=HEAD_BG,
                        lightcolor=HEAD_BG, darkcolor=HEAD_BG)
        style.map(tree + ".Heading", background=[("active", "#e2eac2")])
        style.layout(tree, [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Vertical.TScrollbar", background="#d9e2b4", troughcolor=CARD, bordercolor=CARD,
                        arrowcolor=OLIVE, lightcolor="#d9e2b4", darkcolor="#d9e2b4", gripcount=0, relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", "#c8d59a")])
        style.configure("TCombobox", fieldbackground=FIELD, background=HEAD_BG, foreground=INK,
                        arrowcolor=OLIVE, bordercolor="#c9d39c", lightcolor=FIELD, darkcolor=FIELD, padding=(6, 3))
        style.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", "#f1f1e8")],
                  foreground=[("disabled", "#a0a090")], selectbackground=[("readonly", FIELD)],
                  selectforeground=[("readonly", INK)])
        # rounded pill buttons as 9-slice image elements
        h = self._px(32)
        r = max(4, h // 4)
        variants = {
            "Go": ((72, 118, 36), (86, 136, 46), (60, 100, 28), (56, 96, 26), "#ffffff"),
            "Meme": ((255, 255, 252), (244, 248, 230), (232, 238, 212), (196, 206, 166), INK),
            "Stop": ((253, 241, 237), (255, 247, 244), (244, 222, 214), (228, 176, 164), RED),
        }
        disabled = art.button_image(r * 2 + 8, h, (242, 242, 236), (218, 218, 206), radius=r)
        self._images.append(tk.PhotoImage(master=w, data=self._png(disabled)))
        dis_img = self._images[-1]
        for name, (normal, hover, pressed, border, fg) in variants.items():
            imgs = [tk.PhotoImage(master=w, data=self._png(art.button_image(r * 2 + 8, h, c, border, radius=r)))
                    for c in (normal, hover, pressed)]
            self._images.extend(imgs)
            element = f"W{id(self)}{name}.bg"
            style.element_create(element, "image", imgs[0], ("disabled", dis_img), ("pressed", imgs[2]),
                                 ("active", imgs[1]), border=(r + 2, r + 2, r + 2, r + 5),
                                 padding=(self._px(4), self._px(2), self._px(4), self._px(5)), sticky="nsew")
            sname = f"W{id(self)}{name}.TButton"
            style.layout(sname, [(element, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
            style.configure(sname, padding=(self._px(12), self._px(4), self._px(12), self._px(4)),
                            font=self.f_bold, foreground=fg, background=CARD, anchor="center", width=-4)
            style.map(sname, foreground=[("disabled", "#a8a898")])
        self.btn_style = {k: f"W{id(self)}{k}.TButton" for k in variants}

    @staticmethod
    def _png(image):
        """PNG data with the card colour baked in: opaque images redraw much faster in Tk."""
        import base64
        import io
        if image.mode == "RGBA":
            flat = art.Image.new("RGBA", image.size, art.CARD + (255,))
            flat.alpha_composite(image)
            image = flat.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return base64.b64encode(buffer.getvalue())

    def _photo(self, image):
        """Opaque Tk photo (RGBA is flattened onto the card colour; Tk alpha blending is slow)."""
        from PIL import ImageTk
        if image.mode == "RGBA":
            flat = art.Image.new("RGBA", image.size, art.CARD + (255,))
            flat.alpha_composite(image)
            image = flat.convert("RGB")
        return ImageTk.PhotoImage(image, master=self.window)

    def _card(self):
        frame = tk.Frame(self.window, background=CARD, bd=0, highlightthickness=0)
        return frame

    def _build_ui(self):
        w = self.window
        w.title("某种柳莺 · 柳莺鉴定所")
        w.configure(background="#26301a")
        self.s = max(1.0, float(w.tk.call("tk", "scaling")) * 72 / 96)
        # default window grows with DPI / big screens, never beyond the screen
        sw, sh = max(1, w.winfo_screenwidth()), max(1, w.winfo_screenheight())
        base_w, base_h = (1120, 800) if sw >= 1300 * self.s and sh >= 940 * self.s else (1050, 760)
        gw = max(920, min(int(base_w * self.s), int(sw * .94)))
        gh = max(650, min(int(base_h * self.s), int(sh * .88)))
        w.geometry(f"{gw}x{gh}")
        w.minsize(920, 650)
        self.family = _pick_family(w)
        self._setup_style()
        P = self._px

        from .hero_picker import base_gallery, load_gallery
        self._base_photos = base_gallery(art.load_photos())
        self.photos = list(self._base_photos)
        if (self.app_root / "config/hero_gallery.json").is_file():
            try:
                self.photos = load_gallery(self.app_root, self._get_library, self._base_photos)
            except Exception as exc:
                self.logger.warning("个人轮播设置读取失败：%s", exc)
        self.bg_index = random.randrange(len(self.photos)) if self.photos else None
        self.hero_box = (0, 0, 0, 0)
        self.hero_revealed = False
        try:
            icon_src = next((p for p in self.photos if p.get("file") == "warbler_08.jpg"), None)
            if icon_src is not None:
                icon = self._photo(art.avatar(icon_src, 56))
                self._images.append(icon)
                w.iconphoto(True, icon)
        except Exception:
            pass

        # ------------- background canvas: blurred photo + sharp hero bird + title
        self.bg = tk.Canvas(w, highlightthickness=0, bd=0, background="#26301a")
        self.bg.place(x=0, y=0, relwidth=1, relheight=1)
        self.bg_item = self.bg.create_image(0, 0, anchor="nw")
        self.title_img = art.brand_title(P(66), without_bird=True)
        families = set(tkfont.families(w))
        serif = next((f for f in ("Georgia", "Times New Roman", "Liberation Serif", "DejaVu Serif") if f in families), self.family)
        self.sub_items = self._shadow_text(P(20), 0, "Phylloscopus sp.", (serif, 15, "italic"), "#e9f1d2")
        self.credit_items = self._shadow_text(0, 0, "", (self.family, 8), "#f2f2e6", anchor="se")
        self.bubble_img = self._call_bubble()
        self.bg.bind("<Button-1>", self._bg_click)
        self.bg.bind("<Button-3>", self._hero_context_menu)
        self.bg.bind("<Motion>", self._bg_motion)
        self.bg.bind("<Configure>", self._on_resize)

        # ------------- toolbar card: one row of big buttons + a rotating tip
        self.toolbar = self._card()
        go, meme, stop = self.btn_style["Go"], self.btn_style["Meme"], self.btn_style["Stop"]
        self.add_button = ttk.Button(self.toolbar, text="找到鸟了！", style=meme, command=self.choose_images, takefocus=False)
        self.start_button = ttk.Button(self.toolbar, text="开始鉴定！", style=go, command=self.start_batch, takefocus=False)
        self.cancel_button = ttk.Button(self.toolbar, text="算了不认了", style=stop, command=self.cancel_pending,
                                        state="disabled", takefocus=False)
        self.clear_button = ttk.Button(self.toolbar, text="全部放生", style=meme, command=self.clear_jobs, takefocus=False)
        self.report_button = ttk.Button(self.toolbar, text="鉴定证书", style=meme, command=self.open_report, takefocus=False)
        self.results_button = ttk.Button(self.toolbar, text="翻翻档案", style=meme, command=self.open_results, takefocus=False)
        gaps = (P(10), P(22), P(10), P(22), P(10), 0)   # extra air between button groups
        for i, button in enumerate((self.add_button, self.start_button, self.cancel_button,
                                    self.clear_button, self.report_button, self.results_button)):
            button.grid(row=0, column=i, padx=(0, gaps[i]), sticky="w")
        self.toolbar.columnconfigure(6, weight=1)
        self.toolbar.rowconfigure(0, weight=1)
        self.tip_label = ttk.Label(self.toolbar, text="", style="Soft.TLabel", anchor="e", justify="right")
        self.tip_label.grid(row=0, column=6, sticky="e", padx=(P(16), P(2)))

        # ------------- left card: photo list
        self.left = self._card()
        self.left.columnconfigure(0, weight=1)
        self.left.rowconfigure(1, weight=1)
        ttk.Label(self.left, text="嫌疑鸟名单", style="Head.TLabel").grid(row=0, column=0, sticky="w", pady=(0, P(6)))
        self.count_label = ttk.Label(self.left, text="", style="Soft.TLabel")
        self.count_label.grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, P(6)))
        self.photo_tree = ttk.Treeview(self.left, columns=("photo", "state"), show="headings", selectmode="browse",
                                       height=4, style=self.tree_style)
        self.photo_tree.heading("photo", text="照片")
        self.photo_tree.heading("state", text="状态")
        self.photo_tree.column("photo", width=P(130), minwidth=P(80))
        self.photo_tree.column("state", width=P(70), minwidth=P(55), stretch=False, anchor="center")
        self.photo_tree.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self.left, orient="vertical", command=self.photo_tree.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.photo_tree.configure(yscrollcommand=bar.set)
        self.photo_tree.bind("<<TreeviewSelect>>", self.select_photo)
        for tag, color in (("done", "#3d7a1f"), ("failed", RED), ("cancelled", "#9a9a88"),
                           ("running", "#b8740a"), ("queued", INK_SOFT), ("pending", INK)):
            self.photo_tree.tag_configure(tag, foreground=color)

        # ------------- settings card (left, under the list)
        self.settings_card = self._card()
        self.settings_card.columnconfigure(1, weight=1)
        ttk.Label(self.settings_card, text="鉴定设置", style="Head.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.package_button = ttk.Button(self.settings_card, text="模型包在哪…", style=meme,
                                         command=self.choose_package, takefocus=False)
        self.package_button.grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, P(6)))
        ttk.Label(self.settings_card, text="找鸟方式", style="Card.TLabel").grid(row=1, column=0, sticky="w")
        self.mode_box = ttk.Combobox(self.settings_card, textvariable=self.detection_mode,
            values=list(DETECTION_MODES), state="readonly", width=10, font=self.f_body)
        self.mode_box.grid(row=1, column=1, sticky="ew", padx=(P(10), 0), pady=(0, P(6)))
        ttk.Label(self.settings_card, text="算力来源", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        self.device_box = ttk.Combobox(self.settings_card, textvariable=self.device,
            values=list(DEVICE_MODES), state="readonly", width=10, font=self.f_body)
        self.device_box.grid(row=2, column=1, sticky="ew", padx=(P(10), 0))

        # ------------- preview card
        self.preview_card = self._card()
        self.preview_card.columnconfigure(0, weight=1)
        self.preview_card.rowconfigure(2, weight=1)
        self.verdict_label = tk.Label(self.preview_card, textvariable=self.verdict, font=self.f_verdict,
                                      background=CARD, foreground=INK, anchor="w", justify="left")
        self.verdict_label.grid(row=0, column=0, sticky="ew")
        self.message_row = message_row = tk.Frame(self.preview_card, background=CARD)
        message_row.grid(row=1, column=0, sticky="ew", pady=(P(1), P(6)))
        message_row.columnconfigure(1, weight=1)
        self.message_prefix = ttk.Label(message_row, text="", style="Soft.TLabel")
        self.message_prefix.grid(row=0, column=0, sticky="w")
        self.message_label = ttk.Label(message_row, textvariable=self.photo_message, style="Soft.TLabel",
                                       wraplength=P(640))
        self.message_label.grid(row=0, column=1, sticky="w")
        self.preview = tk.Canvas(self.preview_card, background=CARD, highlightthickness=0, height=P(160), width=P(500))
        self.preview.grid(row=2, column=0, sticky="nsew")
        self.preview.bind("<Configure>", self._schedule_preview)

        # ------------- birds card
        self.birds_card = self._card()
        self.birds_card.columnconfigure(0, weight=1)
        self.birds_card.rowconfigure(1, weight=1)
        ttk.Label(self.birds_card, text="逐只审问", style="Head.TLabel").grid(row=0, column=0, sticky="w", pady=(0, P(6)))
        self.bird_tree = ttk.Treeview(self.birds_card, columns=("bird", "state"), show="headings",
                                      selectmode="browse", height=3, style=self.tree_style)
        self.bird_tree.heading("bird", text="编号")
        self.bird_tree.heading("state", text="审问结果")
        self.bird_tree.column("bird", width=P(60), stretch=False, anchor="center")
        self.bird_tree.column("state", width=P(170), minwidth=P(100))
        self.bird_tree.grid(row=1, column=0, sticky="nsew")
        birdsbar = ttk.Scrollbar(self.birds_card, orient="vertical", command=self.bird_tree.yview)
        birdsbar.grid(row=1, column=1, sticky="ns")
        self.bird_tree.configure(yscrollcommand=birdsbar.set)
        self.bird_tree.bind("<<TreeviewSelect>>", self.select_bird)
        for kind, (color, _) in KIND_COLORS.items():
            self.bird_tree.tag_configure(kind, foreground=color)
        self.bird_tree.tag_configure("outside", foreground="#2b6aa0")

        # ------------- detail card
        self.detail_card = self._card()
        self.detail_card.columnconfigure(1, weight=1)
        self.detail_card.rowconfigure(1, weight=1)
        ttk.Label(self.detail_card, text="鉴定卡", style="Head.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, P(6)))
        self.crop = tk.Canvas(self.detail_card, background=CARD, highlightthickness=0, height=P(100), width=P(112))
        self.crop.grid(row=1, column=0, sticky="n", padx=(0, P(10)))
        self.detail_label = tk.Text(self.detail_card, height=4, width=20, wrap="word", font=self.f_body,
            relief="flat", borderwidth=0, background=CARD, foreground=INK, state="disabled",
            spacing1=P(1), spacing3=P(2), cursor="arrow", highlightthickness=0)
        self.detail_label.grid(row=1, column=1, sticky="nsew")
        detail_bar = ttk.Scrollbar(self.detail_card, orient="vertical", command=self.detail_label.yview)
        detail_bar.grid(row=1, column=2, sticky="ns")
        self.detail_label.configure(yscrollcommand=detail_bar.set)
        self.detail_label.tag_configure("h", font=self.f_head, foreground=OLIVE, spacing3=P(3))
        self.detail_label.tag_configure("verdict", font=self.f_bold, foreground=INK)
        self.detail_label.tag_configure("note", foreground=INK_SOFT, font=(self.family, 9))
        self.detail_label.tag_configure("key", foreground=INK)
        self.detail_label.tag_configure("tip", foreground="#8a6d0b", font=(self.family, 9))
        for kind, (color, _) in KIND_COLORS.items():
            self.detail_label.tag_configure("k_" + kind, foreground=color, font=self.f_bold)
        self.details.trace_add("write", self._render_details)
        self._render_details()

        # ------------- footer status pill
        self.footer = self._card()
        self.footer.columnconfigure(0, weight=1)
        self.footer.rowconfigure(0, weight=1)
        self.status_label = tk.Label(self.footer, textvariable=self.status, background=CARD, foreground=INK,
                                     font=self.f_body, anchor="w", justify="left", wraplength=P(980))
        self.status_label.grid(row=0, column=0, sticky="ew")
        version = "v" + self.release_info.version if self.release_info else "版本"
        self.release_button = ttk.Button(self.footer, text=f"{version} · 更新", command=self._open_release_dialog)
        self.release_button.grid(row=0, column=1, sticky="e", padx=(P(8), 0))
        self.audio_source_label = tk.Label(self.footer, textvariable=self.audio_source, background=CARD,
            foreground=INK_SOFT, font=(self.family, 8), anchor="w", justify="left", cursor="hand2")
        self.audio_source_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.audio_source_label.bind("<Button-1>", self._show_audio_source)

        self._tip_index = random.randrange(len(TOOL_TIPS))
        self.tip_label.configure(text=TOOL_TIPS[self._tip_index])
        self._layout(gw, gh)

    def _shadow_text(self, x, y, text, font_spec, fill, anchor="nw"):
        shadow = self.bg.create_text(x + 1, y + 2, anchor=anchor, fill="#141a08", font=font_spec, text=text)
        main = self.bg.create_text(x, y, anchor=anchor, fill=fill, font=font_spec, text=text)
        return (shadow, main)

    def _move_text(self, items, x, y, text=None):
        self.bg.coords(items[0], x + 1, y + 2)
        self.bg.coords(items[1], x, y)
        if text is not None:
            for item in items:
                self.bg.itemconfigure(item, text=text)

    # ============================================================ layout + bg
    def _rects(self, W, H):
        P = self._px
        M, G = P(16), P(12)
        hero = max(P(140), min(P(260), int(H * .32) - P(60)))
        tb = (M, hero, W - M, hero + P(60))
        top = tb[3] + G
        footer = (M, H - P(64), W - M, H - P(8))
        bottom = footer[1] - G
        left_w = P(262)
        settings_h = P(140)
        rx = M + left_w + G
        prev_h = int((bottom - top) * (.6 if bottom - top > P(420) else .56))
        birds_w = int((W - M - rx - G) * .42)
        lower_top = top + prev_h + G
        return {"toolbar": tb,
                "left": (M, top, M + left_w, bottom - settings_h - G),
                "settings": (M, bottom - settings_h, M + left_w, bottom),
                "preview": (rx, top, W - M, top + prev_h),
                "birds": (rx, lower_top, rx + birds_w, bottom),
                "detail": (rx + birds_w + G, lower_top, W - M, bottom),
                "footer": footer, "_hero": hero}

    def _hero_geometry(self, W, hero):
        sharp_w = int(min(hero * 2.3, W * .58))
        return W - sharp_w, sharp_w

    def _layout(self, W, H):
        if W < 50 or H < 50:
            return
        self.rects = rects = self._rects(W, H)
        P = self._px
        inset = P(12)
        frames = {"toolbar": self.toolbar, "left": self.left, "settings": self.settings_card,
                  "preview": self.preview_card, "birds": self.birds_card, "detail": self.detail_card,
                  "footer": self.footer}
        for name, frame in frames.items():
            x1, y1, x2, y2 = rects[name]
            ix = P(18) if name == "toolbar" else inset
            iy = P(8) if name in ("footer", "toolbar") else inset
            frame.place(x=x1 + ix, y=y1 + iy, width=max(1, x2 - x1 - 2 * ix), height=max(1, y2 - y1 - 2 * iy))
        hero = rects["_hero"]
        sx, sharp_w = self._hero_geometry(W, hero)
        self.hero_box = (sx, 0, W, hero)
        ty = P(12) + self.title_img.height
        self._move_text(self.sub_items, P(22), ty)
        self._move_text(self.credit_items, W - P(10), hero - P(6))
        # the rotating tip only shows when there is room next to the buttons
        room = rects["toolbar"][2] - rects["toolbar"][0] - 2 * P(18)
        used = sum(b.winfo_reqwidth() for b in (self.add_button, self.start_button, self.cancel_button,
                                                 self.clear_button, self.report_button, self.results_button)) + P(80)
        tip_w = room - used - P(60)
        if tip_w > P(150):
            self.tip_label.configure(wraplength=tip_w)
            self.tip_label.grid()
        else:
            self.tip_label.grid_remove()
        footer_width = rects["footer"][2] - rects["footer"][0] - 2 * inset
        self.status_label.configure(wraplength=max(200, footer_width - self.release_button.winfo_reqwidth() - P(8)))
        self.audio_source_label.configure(wraplength=max(200, rects["footer"][2] - rects["footer"][0] - 2 * inset))
        # on short windows the raw model sentence makes room for the picture flow
        if H < P(720):
            self.message_row.grid_remove()
        else:
            self.message_row.grid()
        width = rects["preview"][2] - rects["preview"][0] - 2 * inset
        self.message_label.configure(wraplength=max(200, width - P(80)))
        self.verdict_label.configure(wraplength=max(200, width))

    def _on_resize(self, event):
        self._layout(event.width, event.height)
        if self._bg_size == (event.width, event.height) and self._bg_id is None:
            return
        if self._bg_size is None:
            self._render_bg(event.width, event.height)
        else:
            if self._bg_id is not None:
                self.window.after_cancel(self._bg_id)
            self._bg_id = self.window.after(90, lambda: self._render_bg(event.width, event.height))

    def _current_bg(self):
        return self.photos[self.bg_index] if self.bg_index is not None and self.photos else None

    def _render_bg(self, W, H):
        self._bg_id = None
        if self.closed or W < 50 or H < 50:
            return
        P = self._px
        rects = self._rects(W, H)
        hero = rects["_hero"]
        sx, sharp_w = self._hero_geometry(W, hero)
        photo = self._current_bg()
        try:
            source = None
            if photo is not None:
                source = (art.photo_stamp(photo["path"]), tuple(photo.get("focus", (.5, .5))), photo.get("fit"))
            key = (W, H, self.s, source, id(self.title_img), tuple(rects.items()))
            new_wall = key != self._wall_key
            if new_wall:
                if photo is None:
                    wall = art.Image.new("RGBA", (W, H), (38, 48, 26, 255))
                    bird = (W - P(120), hero // 2)
                else:
                    wall, bird = art.hero_wallpaper(photo, W, H, hero, sx, sharp_w)
                cards = [r for k, r in rects.items() if not k.startswith("_")]
                wall = art.compose(wall, cards, P(18))
                self.branch_args = {"title_right": P(14) + self.title_img.width, "photo_left": sx}
                paint_branches(wall, rects, self.s, **self.branch_args)
                wall.alpha_composite(self.title_img, (P(14), P(12)))
                self._wall_key, self._wall_base, self._wall_bird = key, wall, bird
            bird = self._wall_bird
            # speech bubble from the real bird, placed in the soft zone left of it
            bub = self.bubble_img
            old_box = self.call_box
            self.call_box = None
            if bub is None:
                bub = art.Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            bx2 = max(sx + P(30), min(int(bird[0] - sharp_w * .08), W - P(20)))
            bx = bx2 - bub.width
            min_x = P(14) + self.title_img.width + P(20)
            if bx < min_x:
                bx = min_x
            by = max(P(8), min(int(bird[1] - hero * .28) - bub.height, hero - bub.height - P(26)))
            if self.bubble_img is not None and bx + bub.width <= W - P(8):
                self.call_box = (bx, by, bx + bub.width, by + bub.height)
            if new_wall:
                image = self._wall_base
                if self.call_box:
                    image = image.copy()
                    image.alpha_composite(bub, (bx, by))
                self.bg_photo = self._photo(image.convert("RGB"))
                self.bg.itemconfigure(self.bg_item, image=self.bg_photo)
            elif old_box or self.call_box:
                # Restore both footprints when the new caption is shorter or disappears.
                boxes = [box for box in (old_box, self.call_box) if box]
                dirty = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                         min(W, max(b[2] for b in boxes)), min(H, max(b[3] for b in boxes)))
                patch = self._wall_base.crop(dirty)
                if self.call_box:
                    patch.alpha_composite(bub, (bx - dirty[0], by - dirty[1]))
                tile = self._photo(patch.convert("RGB"))
                self.bg.tk.call(str(self.bg_photo), "copy", str(tile), "-to", dirty[0], dirty[1])
        except Exception as exc:  # never let decoration break the app
            self._wall_key = None
            self.logger.warning("背景绘制失败：%s", exc)
            if photo is not None and len(self.photos) > 1:
                self.photos.pop(self.bg_index)
                self.bg_index = 0
            else:
                self.bg_index = None
            return
        self._bg_size = (W, H)
        self._update_credit()

    def _update_credit(self):
        photo = self._current_bg()
        if photo is None:
            text = ""
        elif photo.get("user_record"):
            text = "我的观鸟记录 · " + str(photo.get("display_name") or "未命名照片") + " · " + str(photo.get("species_cn") or "鸟种未确认")
        elif photo.get("user"):
            text = "你自己的照片 · " + photo["path"].name
        else:
            text = f"摄影 {photo.get('author')} · {photo.get('license')} · Wikimedia Commons"
        for item in self.credit_items:
            self.bg.itemconfigure(item, text=text)

    def _call_bubble(self):
        """Only the call at first; after a click the bird also says what it is."""
        photo = self._current_bg()
        species = (photo or {}).get("species_cn")
        call = SPECIES_CALLS.get(species)
        if call is None and photo and photo.get("user_record"):
            call = "Listen to this bird" if photo.get("local_audio") else "No local recording"
        if call is None:
            return None
        caption = f"我是{species}。" if self.hero_revealed else None
        return art.call_tag(call, caption, self._px(14),
                            playing=self._audio_is_playing and self._audio_common_name == species)

    def _in_call(self, event):
        return self.call_box is not None and (self.call_box[0] <= event.x <= self.call_box[2] and
                                              self.call_box[1] <= event.y <= self.call_box[3])

    def _in_hero(self, event):
        x1, y1, x2, y2 = self.hero_box
        return x1 <= event.x <= x2 and y1 <= event.y <= y2

    def _bg_motion(self, event):
        cursor = "hand2" if self._in_call(event) or self._in_hero(event) else ""
        if self._bg_cursor != cursor:
            self.bg.configure(cursor=cursor)
            self._bg_cursor = cursor

    def _bg_click(self, event):
        if self._in_call(event):
            photo = self._current_bg() or {}
            self.play_bird_audio(photo.get("scientific_name") or photo.get("species") or photo.get("species_cn"))
            return
        if not self._in_hero(event):
            return
        x, y = event.x, event.y
        if self._bg_size and x > self._bg_size[0] - self._px(260) and y > self.hero_box[3] - self._px(22):
            self._open_credit()
            return
        self._poke_hero()

    def _open_credit(self):
        photo = self._current_bg()
        if photo and photo.get("user_record"):
            self._open_library("records")
            if self.library_window:
                self.library_window.focus_archive(photo["event_id"])
            return
        if photo and photo.get("source"):
            import webbrowser
            webbrowser.open(photo["source"])

    def _poke_hero(self, event=None):
        """First click: the bird says which species it is. Second click: next real photo."""
        if not self.photos:
            return
        if not self.hero_revealed and (self._current_bg() or {}).get("species_cn"):
            self.hero_revealed = True
        else:
            self._advance_hero()
            return
        self.bubble_img = self._call_bubble()
        if self._bg_size:
            self._render_bg(*self._bg_size)
        self._reset_carousel()

    def _reset_carousel(self):
        if self._carousel_id is not None:
            try:
                self.window.after_cancel(self._carousel_id)
            except tk.TclError:
                pass
        self._carousel_id = None if self.closing else self.window.after(10000, self._carousel_tick)

    def _carousel_tick(self):
        self._carousel_id = None
        if self.closed or self.closing:
            return
        if self.backgrounded or self.window.state() in ("withdrawn", "iconic"):
            self._reset_carousel()
            return
        library_open = (self.library_window is not None and self.library_window.window.winfo_exists()
                        and self.library_window.window.winfo_viewable())
        picker_open = self._hero_picker is not None and self._hero_picker.winfo_exists()
        if not self.audio.playing and not picker_open and not library_open:
            self._advance_hero()
        else:
            self._reset_carousel()

    def _advance_hero(self):
        self.audio.stop()
        self._audio_is_playing = False
        self.audio_source.set("")
        if (self.app_root / "config/hero_gallery.json").is_file():
            try:
                from .hero_picker import load_gallery
                key = (self._current_bg() or {}).get("gallery_id")
                self.photos = load_gallery(self.app_root, self._get_library(), self._base_photos)
                self.bg_index = next((i for i, photo in enumerate(self.photos) if photo["gallery_id"] == key), 0)
            except Exception as exc:
                self.logger.warning("轮播记录更新失败：%s", exc)
        if self.photos:
            self.bg_index = ((self.bg_index or 0) + 1) % len(self.photos)
            self.hero_revealed = bool((self._current_bg() or {}).get("user_record"))
        self.bubble_img = self._call_bubble()
        if self._bg_size:
            self._render_bg(*self._bg_size)
        self._reset_carousel()

    def _hero_context_menu(self, event):
        if not self._in_hero(event):
            return
        menu = tk.Menu(self.window, tearoff=False)
        menu.add_command(label="我有自己的观鸟记录图！", command=lambda: self._open_library("records"))
        menu.add_command(label="换下一张（每10秒自动轮播）", command=self._advance_hero)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _choose_record_hero(self, event):
        try:
            from .hero_picker import HeroCropPicker, load_gallery
            if self._hero_picker is not None and self._hero_picker.winfo_exists():
                self._hero_picker.lift()
                return
            self.photos = load_gallery(self.app_root, self._get_library(), self._base_photos)
            self._hero_picker = HeroCropPicker(self.window, self.app_root, self.library, event,
                self.photos, self._record_hero_saved)
        except Exception as exc:
            self.logger.exception("打开观鸟图片选择失败")
            self.status.set(f"这份记录暂时不能用作观鸟图：{exc}")

    def _record_hero_saved(self, gallery_id):
        from .hero_picker import load_gallery
        self.photos = load_gallery(self.app_root, self._get_library(), self._base_photos)
        self.bg_index = next((i for i, photo in enumerate(self.photos) if photo["gallery_id"] == gallery_id), 0)
        self.audio.stop()
        self._audio_is_playing = False
        self.audio_source.set("")
        self.hero_revealed = True
        self.bubble_img = self._call_bubble()
        if self._bg_size:
            self._render_bg(*self._bg_size)
        self._reset_carousel()
        self.status.set("轮播图已保存，名字和叫声关联所选鸟的本地资料；每10秒自动切换。")

    # ================================================================ details
    def _set_detail_lines(self, lines):
        self._detail_lines = [(str(t), tag) for t, tag in lines]
        self.details.set("\n".join(t for t, _ in self._detail_lines))

    def _render_details(self, *args):
        text = self.details.get()
        self.detail_label.configure(state="normal")
        self.detail_label.delete("1.0", "end")
        lines = self._detail_lines
        if lines and "\n".join(t for t, _ in lines) == text:
            for i, (line, tag) in enumerate(lines):
                self.detail_label.insert("end", line + ("\n" if i < len(lines) - 1 else ""), tag)
        else:
            self.detail_label.insert("1.0", text, "note")
        self.detail_label.configure(state="disabled")
        self.detail_label.yview_moveto(0.)

    # ================================================================ actions
    def open_path(self, path):
        import os
        if os.name == "nt":
            os.startfile(str(path))
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])

    def open_report(self):
        self._open_library("certificate", self.current_result)

    def open_results(self):
        self._open_library("records")

    def _open_release_dialog(self):
        if self._release_dialog is not None and self._release_dialog.winfo_exists():
            self._release_dialog.deiconify()
            self._release_dialog.lift()
            return
        dialog = self._release_dialog = tk.Toplevel(self.window)
        dialog.title("版本与更新")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        panel = tk.Frame(dialog, background=CARD, padx=self._px(22), pady=self._px(18))
        panel.pack(fill="both", expand=True)
        version = "v" + self.release_info.version if self.release_info else "未知"
        ttk.Label(panel, text=f"当前版本  {version}", style="Head.TLabel").pack(anchor="w")
        self._release_message = tk.StringVar(dialog)
        ttk.Label(panel, textvariable=self._release_message, style="Card.TLabel",
                  wraplength=self._px(310)).pack(anchor="w", pady=(self._px(10), self._px(12)))
        actions = tk.Frame(panel, background=CARD)
        actions.pack(fill="x")
        self._release_retry = ttk.Button(actions, text="立即检查", command=self._start_release_check)
        self._release_retry.pack(side="left")
        self._release_page = ttk.Button(actions, text="打开发布页", command=self._open_release_page)
        self._refresh_release_dialog()

    def _refresh_release_dialog(self):
        if self._release_dialog is None or not self._release_dialog.winfo_exists():
            return
        configured = bool(self.release_info and self.release_info.repository)
        if self._release_pending:
            message = "正在查询 GitHub…"
        elif self._release_result:
            message = self._release_result.message
        elif not self.release_info:
            message = "无法读取本机的发布配置。"
        elif not configured:
            name = self.release_info.repository_name
            message = f"已登记 {name}，待配置 GitHub 所属账号。" if name else "尚未配置 GitHub 发布仓库。"
        else:
            message = "可查询 GitHub 上的最新正式版。"
        self._release_message.set(message)
        self._release_retry.configure(state="normal" if configured and not self._release_pending else "disabled")
        if self._release_result and self._release_result.page:
            self._release_page.pack(side="left", padx=(self._px(8), 0))
        else:
            self._release_page.pack_forget()

    def _open_release_page(self):
        if self._release_result and self._release_result.page:
            import webbrowser
            webbrowser.open(self._release_result.page)

    def _check_release_on_startup(self):
        self._release_timer = None
        self._start_release_check(automatic=True)

    def _start_release_check(self, automatic=False):
        info = self.release_info
        if self.closing or self._release_pending or not info or not info.repository:
            return
        cache = self.app_root / "cache/release_check.json"
        if automatic and not release.automatic_check_due(cache, info):
            return
        self._release_pending = True
        self._refresh_release_dialog()

        def query():
            release.remember_check(cache, info)
            self.events.put(("release_checked", release.check_latest(info)))

        threading.Thread(target=query, name="release-check", daemon=True).start()

    def _load_library(self):
        from .library import Library
        library = Library(self.app_root)
        try:
            receipt = library.import_results(self.output_root)
            self.logger.info("导入本地识别档案：%s", receipt)
            return library
        except Exception:
            library.close()
            raise

    def _get_library(self):
        if self.library is None:
            self.library = (self._startup_library.result() if self._startup_library is not None
                            else self._load_library())
        return self.library

    def _open_library(self, tab, result=None):
        try:
            from .library_ui import LibraryWindow
            library = self._get_library()
            if result and result.get("status") != "error":
                stored = library.ingest_result(result)
                if stored.get("deleted"):
                    self.status.set("这份记录已从档案删除；重新识别可生成一份新记录。")
                    return
                result = library.event_detail(stored["event_id"])
            old = self.library_window
            if old is not None and old.window.winfo_exists():
                old.present(tab, result=result)
                return
            self.library_window = LibraryWindow(self.window, library, self.app_root,
                on_play=self.play_bird_audio, initial_tab=tab, result=result, on_use_hero=self._choose_record_hero,
                family=self.family)
        except Exception as exc:
            self.logger.exception("打开本地鸟种库失败")
            self.status.set(f"本地档案暂时无法打开：{exc}")

    def play_bird_audio(self, species):
        try:
            library = self._get_library()
            detail = library.species_detail(species) if species else None
            if not detail:
                detail = next((row for row in library.species_cards() if row.get("common_name") == species), None)
            clips = (detail or {}).get("audio") or []
            available = [item for item in clips if item.get("path") and
                         (self.app_root / item["path"]).is_file()]
            if not available:
                self.status.set(f"{(detail or {}).get('common_name') or species or '这只鸟'}暂未收录可离线播放的叫声，可在鸟种卡查看资料来源。")
                return
            key = (detail or {}).get("scientific_name") or species
            if self._audio_species == key and self.audio.playing:
                self.audio.stop()
                self.status.set("鸟叫已停止。")
            else:
                clip = available[0]
                self.audio.play(clip["path"])
                self._audio_species = key
                self._audio_common_name = (detail or {}).get("common_name")
                author = clip.get("author") or "来源见鸟种卡"
                from urllib.parse import urlsplit
                host = urlsplit(clip.get("source_url") or "").hostname or "本地资料"
                platform = {"commons.wikimedia.org": "Wikimedia Commons", "www.inaturalist.org": "iNaturalist",
                            "inaturalist.org": "iNaturalist", "xeno-canto.org": "xeno-canto"}.get(host, host)
                self.audio_source.set(f"声音来源：{platform}  ·  录音：{author}  ·  {clip.get('license') or '许可见鸟种卡'}  ·  点击查看来源")
                self.status.set(f"正在播放 {(detail or {}).get('common_name') or species} · {clip.get('title') or '野外录音'} · {author}")
            self._refresh_audio_bubble()
        except Exception as exc:
            self.logger.exception("播放叫声失败")
            self.status.set(f"叫声暂时无法播放：{exc}")

    def _show_audio_source(self, event=None):
        if self._audio_species:
            self._open_library("species")
            if self.library_window is not None and self.library_window.window.winfo_exists():
                self.library_window.show_species(self._audio_species)

    def _refresh_audio_bubble(self):
        previously_playing = self._audio_is_playing
        self._audio_is_playing = self.audio.playing
        if previously_playing and not self._audio_is_playing and self.status.get().startswith("正在播放 "):
            self.status.set("鸟叫播放完毕。")
        self.bubble_img = self._call_bubble()
        if self._bg_size:
            self._render_bg(*self._bg_size)

    def _poll_audio(self):
        self._audio_id = None
        if self.closed or self.closing:
            return
        playing = self.audio.playing
        if playing != self._audio_is_playing:
            self._refresh_audio_bubble()
        self._audio_id = self.window.after(200, self._poll_audio)

    def choose_images(self):
        paths = filedialog.askopenfilenames(parent=self.window, title="投喂疑似柳莺的照片",
            filetypes=[("照片", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"), ("所有文件", "*.*")])
        self.add_paths(paths)

    def choose_package(self):
        folder = filedialog.askdirectory(parent=self.window, title="选择完整NVIDIA模型包",
                                         initialdir=self.package.get() or str(self.app_root))
        if folder:
            self.package.set(folder)
            self.save_settings()
            self.status.set("模型包位置记住了，下次鉴定就用它。")

    def _set_photo_state(self, key, state):
        self.photo_tree.set(key, "state", PHOTO_STATES[state])
        self.photo_tree.item(key, tags=(state,))

    def _update_count(self):
        if not self.jobs:
            self.count_label.configure(text="空空如也")
            return
        done = sum(1 for k in self.jobs if k in self.results)
        self.count_label.configure(text=f"{done}/{len(self.jobs)} 只已审")

    def add_paths(self, paths):
        for source in paths:
            path = Path(source).resolve()
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or str(path) in self.jobs.values():
                continue
            key = f"photo_{len(self.jobs)+1}"
            self.jobs[key] = str(path)
            self.photo_tree.insert("", "end", iid=key, values=(path.name, PHOTO_STATES["pending"]), tags=("pending",))
        if self.jobs and not self.photo_tree.selection():
            self.photo_tree.selection_set(next(iter(self.jobs)))
            self.select_photo()
        self._update_count()
        if not self.jobs:
            self._show_verdict(None)
            self._refresh_preview()

    def clear_jobs(self):
        """Remove UI jobs and displayed results without unloading the cached engine."""
        if self.busy or self.closing:
            return
        self.jobs.clear()
        self.results.clear()
        self.active.clear()
        self.current_result = self.current_bird = None
        for tree in (self.photo_tree, self.bird_tree):
            for iid in tree.get_children():
                tree.delete(iid)
        for canvas in (self.preview, self.crop):
            canvas.delete("all")
        self.preview_photo = self.crop_photo = self.stamp_photo = None
        self.photo_message.set("")
        self._show_verdict(None)
        self._detail_lines = None
        self.details.set("先在左边点一张照片，再在「逐只审问」里点一只鸟。")
        self.status.set("全部放生了 (・ω・)ノ 可以投喂新照片继续。")
        self._update_count()
        self._refresh_preview()

    def save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        value = {"package_root": self.package.get(), "device": DEVICE_MODES.get(self.device.get(), self.device.get()),
                 "detection_mode": self.detection_mode.get()}
        self.settings_path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))

    def _set_busy(self, value):
        self.busy = value
        for widget in (self.add_button, self.start_button, self.package_button, self.clear_button):
            widget.configure(state="disabled" if value else "normal")
        for widget in (self.mode_box, self.device_box):
            widget.configure(state="disabled" if value else "readonly")
        self.cancel_button.configure(state="normal" if value else "disabled")

    def start_batch(self):
        if self.busy or self.closing:
            return
        if not self.jobs:
            self.status.set("还没投喂照片呢 —— 先点「找到鸟了！」。")
            return
        if not self.package.get().strip() or not Path(self.package.get()).is_dir():
            self.status.set("找不到模型包 (°ー°〃) 先点「模型包在哪…」选一下完整的模型包位置。")
            return
        self.save_settings()
        self._set_busy(True)
        mode = DETECTION_MODES[self.detection_mode.get()]
        device = DEVICE_MODES.get(self.device.get(), self.device.get())
        package = self.package.get()
        self.active = set(self.jobs)
        self.batch_keys = list(self.jobs)
        self.last_progress = ""
        for key in self.jobs:
            self._set_photo_state(key, "queued")
        self.status.set(f"{len(self.active)} 张照片排好队了，开始鉴定……")
        self._refresh_selected_headline()
        # paint the queued state now, before the worker starts competing for the CPU
        self.window.update_idletasks()
        for key, source in self.jobs.items():
            self.worker.commands.put((key, source, package, device, mode, self.output_root, deepcopy(self.config)))

    def cancel_pending(self):
        count = 0
        while True:
            try:
                job = self.worker.commands.get_nowait()
            except queue.Empty:
                break
            if job is None:
                self.worker.commands.put(None)
                break
            key = job[0]
            self.active.discard(key)
            self._set_photo_state(key, "cancelled")
            count += 1
        self.status.set(f"行，{count} 张排队的照片不认了；正在认的那张会认完。")
        if not self.active:
            self._set_busy(False)
        self._refresh_selected_headline()

    def _batch_summary(self):
        kinds = [result_kind(self.results.get(k)) for k in self.batch_keys if k in self.results]
        parts = []
        for kind, label in (("willow", "柳莺"), ("not_willow", "非柳莺"), ("uncertain", "薛定谔"),
                            ("no_bird", "没找到鸟"), ("error", "翻车")):
            n = kinds.count(kind)
            if n:
                parts.append(f"{label} ×{n}")
        return "，".join(parts)

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "started":
                    self.running_key = event[1]
                    self.last_progress = ""
                    self._set_photo_state(event[1], "running")
                    self._refresh_selected_headline()
                elif kind == "progress":
                    self.last_progress = event[2]
                    self._compose_busy_status()
                elif kind == "log":
                    self.logger.warning(event[1])
                elif kind == "release_checked":
                    self._release_pending = False
                    self._release_result = event[1]
                    if not self.closing:
                        label = "有更新" if self._release_result.update_available else "更新"
                        self.release_button.configure(text=f"v{self.release_info.version} · {label}")
                        self._refresh_release_dialog()
                elif kind in ("done", "failed"):
                    key = event[1]
                    self.active.discard(key)
                    if self.running_key == key:
                        self.running_key = None
                    if kind == "done":
                        self.results[key] = event[2]
                        try:
                            self._get_library().ingest_result(event[2])
                            if self.library_window is not None and self.library_window.window.winfo_exists():
                                self.library_window.refresh()
                        except Exception:
                            self.logger.exception("本次识别保存到档案库失败；原结果仍保存在 results")
                        self._set_photo_state(key, "done")
                        self.logger.info("完成 %s：%s", self.jobs[key], event[2].get("message", ""))
                    else:
                        self.results[key] = {"status": "error", "message": event[2], "source": self.jobs[key], "boxes": []}
                        self._set_photo_state(key, "failed")
                        self.logger.error("失败 %s：%s", self.jobs[key], event[2])
                    self._update_count()
                    if self.photo_tree.selection() == (key,):
                        self.select_photo()
                    if not self.active:
                        self._set_busy(False)
                        summary = self._batch_summary()
                        self.status.set("本批鉴定完毕！" + (f"（{summary}）" if summary else "") +
                                        " 点击「翻翻档案」查看本地记录。")
        except queue.Empty:
            pass
        if self.closing and not self.worker.is_alive():
            self.closed = True
            for after_id in (self._anim_id, self._bg_id, self._preview_id, self._audio_id,
                             self._carousel_id, self._resident_id, self._release_timer):
                if after_id is not None:
                    try:
                        self.window.after_cancel(after_id)
                    except tk.TclError:
                        pass
            self.handler.close()
            self.logger.removeHandler(self.handler)
            self.audio.close()
            if self.tray is not None:
                self.tray.close()
            if self.scene is not None:
                self.scene.close()
            if self.library is not None:
                if self.library_window is not None:
                    self.library_window.dispose()
                self.library.close()
            self.window.destroy()
            return
        self.poll_id = self.window.after(40, self._poll)

    def _compose_busy_status(self):
        if not self.busy or self.closing:
            return
        face = SPINNER[self._tick % len(SPINNER)]
        text = f"{face}  {self._loading_line}"
        if self.last_progress:
            text += f"   ｜ {self.last_progress}"
        left = len(self.active)
        if left:
            text += f"   ｜ 还剩 {left} 张"
        self.status.set(text)

    def _animate(self):
        self._anim_id = None
        if self.closed:
            return
        self._tick += 1
        if self._tick % 18 == 0:
            self._tip_index = (self._tip_index + 1) % len(TOOL_TIPS)
            self.tip_label.configure(text=TOOL_TIPS[self._tip_index])
        if self.busy and not self.closing:
            if self._tick % 5 == 0:
                self._loading_line = random.choice([l for l in LOADING_LINES if l != self._loading_line])
            self._compose_busy_status()
            key = self.running_key
            if key and key in self.jobs and key in self.active:
                try:
                    self.photo_tree.set(key, "state", PHOTO_STATES["running"] + "." * (1 + self._tick % 3))
                except tk.TclError:
                    pass
        self._anim_id = self.window.after(450, self._animate)

    # ============================================================ selection
    def _show_verdict(self, key):
        result = self.results.get(key) if key else None
        kind = result_kind(result)
        color = KIND_COLORS.get(kind, KIND_COLORS["pending"])[0]
        if key is None:
            text, prefix = "还没有嫌疑鸟 —— 先投喂几张照片吧", ""
        elif result is None:
            name = Path(self.jobs[key]).name
            if key == self.running_key:
                text = "正在盯着看……这到底是哪种柳莺"
            elif key in self.active:
                text = "排队中，前面还有别的柳莺在接受审问"
            else:
                text = "待鉴定：点「开始鉴定！」认一认"
            prefix = "文件："
        else:
            prefix = "鉴定结果："
            if kind == "willow":
                names = _specialist_names(result)
                outgroups = _specialist_outgroups(result)
                text = ("是柳莺！专项小声说可能是：" + "、".join(names)) if names else (
                    "柳莺候选，但专项更像：" + "、".join(outgroups) + "。请看逐鸟结果。" if outgroups else "是柳莺！至于哪种……某种柳莺。")
            elif kind == "not_willow":
                names = list(dict.fromkeys(str(b.get("original_name")) for b in result.get("boxes", [])
                                           if b.get("original_name")))
                text = "根本没有这种柳莺" + (f" —— 这是{'、'.join(names)}" if names else "")
            elif kind == "uncertain":
                text = "薛定谔的柳莺：证据不够，没下结论"
            elif kind == "no_bird":
                text = "鸟呢？这张图里一只鸟都没逮到"
            else:
                text = "翻车了！这张没认成"
        self.verdict.set(text)
        self.verdict_label.configure(foreground=color)
        self.message_prefix.configure(text=prefix)

    def _refresh_selected_headline(self):
        selected = self.photo_tree.selection()
        if selected and selected[0] in self.jobs:
            self._show_verdict(selected[0])

    def select_photo(self, event=None):
        selected = self.photo_tree.selection()
        if not selected:
            return
        key = selected[0]
        self.current_result = self.results.get(key)
        self.current_bird = None
        for iid in self.bird_tree.get_children():
            self.bird_tree.delete(iid)
        self._detail_lines = None
        self.details.set("点「逐只审问」里的一只鸟，看看它的鉴定卡。")
        self.crop.delete("all")
        self.crop_photo = None
        self._show_verdict(key)
        if self.current_result is not None:
            self.photo_message.set(str(self.current_result.get("message", "")))
            for i, box in enumerate(self.current_result.get("boxes", [])):
                status = box.get("gate_status")
                tag = "outside" if status == "willow_outside_coverage" else (
                    "willow" if status == "willow" else "not_willow" if status == "not_willow" else "uncertain")
                bird_id = str(box.get("bird_id", str(i + 1)))
                number = bird_id.split("_")[-1].lstrip("0") or bird_id
                self.bird_tree.insert("", "end", iid=str(i), values=(f"{number} 号", bird_label(box)), tags=(tag,))
            if self.bird_tree.get_children():
                self.bird_tree.selection_set("0")
                self.select_bird()          # also redraws the preview flow for that bird
                return
            self._draw_crop_placeholder("这张没有鸟\n可以审问")
        else:
            self.photo_message.set(Path(self.jobs[key]).name)
            self._draw_crop_placeholder("还没鉴定")
        self._refresh_preview()

    def _draw_crop_placeholder(self, text):
        canvas = self.crop
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 70:
            w, h = self._px(118), self._px(110)
        canvas.create_text(w / 2, h * .36, text="？", fill="#d3d8b4", font=(self.family, 30, "bold"))
        canvas.create_text(w / 2, h * .74, text=text, fill=INK_SOFT, font=(self.family, 9), justify="center")

    def _show_image(self, canvas, path, is_crop=False, overlay=None):
        from PIL import Image, ImageTk
        from .display_images import load_thumbnail
        canvas.delete("all")
        if not path or not Path(path).is_file():
            return
        try:
            frame = self._px(5) if is_crop else self._px(8)
            width = max(50, canvas.winfo_width() - 2 * frame - self._px(8))
            height = max(50, canvas.winfo_height() - 2 * frame - self._px(8))
            image = load_thumbnail(path, (width, height))
            if overlay is not None:
                # the verdict stamp is baked into the photo (bottom-right corner)
                limit_w, limit_h = int(image.width * .62), int(image.height * .5)
                if overlay.width > limit_w or overlay.height > limit_h:
                    overlay = overlay.copy()
                    overlay.thumbnail((max(20, limit_w), max(20, limit_h)), Image.Resampling.LANCZOS)
                image = image.convert("RGBA")
                image.alpha_composite(overlay, (image.width - overlay.width - 2, image.height - overlay.height - 2))
                image = image.convert("RGB")
            photo = ImageTk.PhotoImage(image, master=self.window)
            cx, cy = canvas.winfo_width() / 2, canvas.winfo_height() / 2
            hw, hh = image.width / 2 + frame, image.height / 2 + frame
            # polaroid-ish frame with a soft drop shadow
            canvas.create_rectangle(cx - hw + 4, cy - hh + 5, cx + hw + 4, cy + hh + 5, fill="#dfe3c8", outline="")
            canvas.create_rectangle(cx - hw, cy - hh, cx + hw, cy + hh, fill="#ffffff", outline="#d5dbb5")
            canvas.create_image(cx, cy, image=photo)
            if is_crop:
                self.crop_photo = photo
            else:
                self.preview_photo = photo
        except Exception as exc:
            self.logger.warning("照片预览失败 %s：%s", path, exc)

    def _draw_preview_placeholder(self):
        canvas = self.preview
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 60 or h < 60:
            return
        P = self._px
        named = [p for p in self.photos if p.get("species_cn")]
        photo = next((p for p in named if p.get("file") == "warbler_01.jpg"), named[0] if named else None)
        text_y = h / 2
        if photo is not None and h > P(150):
            ph = int(h - P(64))
            pw = min(int(ph * 1.45), w - P(40))
            try:
                self.placeholder_photo = self._photo(art.polaroid(photo, pw, ph, zoom=1.05, tilt=-2))
                canvas.create_image(w / 2, ph / 2 + P(10), image=self.placeholder_photo)
                text_y = ph + P(40)
            except Exception as exc:
                self.logger.warning("占位图失败：%s", exc)
        canvas.create_text(w / 2, text_y, fill=INK_SOFT, font=(self.family, 11), justify="center",
                           text="这只冕柳莺等你投喂等得都坐地上了 —— 点「找到鸟了！」丢几只疑似柳莺进来")

    def _stamp_image(self, result):
        kind = result_kind(result)
        if kind not in STAMPS:
            return None
        text, sub = STAMPS[kind]
        if kind == "willow":
            names = _specialist_names(result)
            if names:
                sub = "专项猜：" + names[0] + "（仅供参考）"
            elif _specialist_outgroups(result):
                text, sub = "有点像，但存疑", "专项倾向相似组外鸟 · 请看详情"
        color = art.STAMP_RED if kind in ("willow", "not_willow", "error") else KIND_COLORS[kind][1]
        size = max(16, min(self._px(30), self.preview.winfo_height() // 7))
        return art.stamp(text, sub, color=tuple(color), size=size, angle=-11)

    def _schedule_preview(self, event=None):
        if self.closing or self.closed:
            return
        if self._preview_id is not None:
            self.window.after_cancel(self._preview_id)
        self._preview_id = self.window.after(90, self._refresh_preview)

    def _refresh_preview(self):
        if self._preview_id is not None:
            self.window.after_cancel(self._preview_id)
            self._preview_id = None
        if self.closing or self.closed:
            return
        selected = self.photo_tree.selection()
        if not selected or selected[0] not in self.jobs:
            self.preview_photo = None
            self._draw_preview_placeholder()
            return
        result = self.results.get(selected[0])
        if result is not None and self.current_bird is not None and self._draw_flow(result, self.current_bird):
            return
        overlay = self._stamp_image(result) if result is not None else None
        self._show_image(self.preview, (result or {}).get("annotated_path") or self.jobs[selected[0]], overlay=overlay)

    # ------------------------------------------------ recognition flow: photo → crop → {top-2} → answer
    @staticmethod
    def _flow_data(box):
        """Top-2 candidates (50-species head if it ran, else the original model) + the final answer."""
        if box.get("gate_status") not in ("willow", "willow_outside_coverage"):
            return None
        expert = box.get("specialist") if isinstance(box.get("specialist"), dict) else {}
        ranked = [t for t in (expert.get("top3") or []) if isinstance(t, dict) and t.get("scientific_name")]
        if ranked:
            cands = [{"cn": t.get("common_name") or t["scientific_name"], "sci": t["scientific_name"],
                      "conf": float(t.get("confidence") or 0)} for t in ranked[:2]]
        else:
            top = [t for t in (box.get("original_top5") or []) if isinstance(t, dict) and t.get("name")]
            cands = [{"cn": t.get("common_name") or t["name"], "sci": t["name"],
                      "conf": float(t.get("confidence") or 0)} for t in top[:2]]
        if not cands:
            return None
        is_willow = expert.get("is_willow", not expert.get("rejected_as_OTHER", True)) if expert else False
        if (box.get("gate_status") == "willow" and expert and is_willow
                and expert.get("global_id", -1) != -1 and expert.get("common_name")):
            final = {"cn": expert["common_name"], "sci": expert.get("scientific_name"),
                     "conf": expert.get("confidence"), "source": expert.get("display_source", "专项复核")}
        elif box.get("original_name"):
            final = {"cn": box["original_name"], "sci": box.get("original_scientific_name"),
                     "conf": box.get("original_confidence"), "source": "原判保留（专项未确认）"}
        else:
            final = {**cands[0], "source": "原判保留（专项未确认）"}
        fe = str(final.get("sci") or "").split()[-1:] or [""]
        hint = next((c for c in cands if str(c["sci"]).split()[-1:] != fe), None)
        return {"cands": cands, "final": final, "hint": hint}

    @staticmethod
    def _pct(value):
        if value is None:
            return ""
        value = float(value) * 100
        return "<0.1%" if value < .1 else f"{value:.1f}%"

    def _framed(self, canvas, image, cx, cy, tag, zoom_source, title):
        """Paste a PIL image centred at (cx, cy) with a white frame; click opens the big view."""
        P = self._px
        photo = self._photo(image)
        self._flow_photos.append(photo)
        hw, hh = image.width / 2 + P(4), image.height / 2 + P(4)
        canvas.create_rectangle(cx - hw + 3, cy - hh + 4, cx + hw + 3, cy + hh + 4, fill="#dfe3c8", outline="", tags=(tag,))
        canvas.create_rectangle(cx - hw, cy - hh, cx + hw, cy + hh, fill="#ffffff", outline="#d5dbb5", tags=(tag,))
        canvas.create_image(cx, cy, image=photo, tags=(tag,))
        canvas.tag_bind(tag, "<Button-1>", lambda e: self._zoom(zoom_source, title))
        canvas.tag_bind(tag, "<Enter>", lambda e: canvas.configure(cursor="hand2"))
        canvas.tag_bind(tag, "<Leave>", lambda e: canvas.configure(cursor=""))
        return photo, (cx - hw, cy - hh, cx + hw, cy + hh)

    def _plate_or_card(self, cand, box_w, box_h):
        plate = art.find_plate(cand.get("sci"), cand.get("cn"))
        if plate is not None:
            image = art.open_plate(plate["bird_path"]).copy()
            image.thumbnail((max(20, box_w), max(20, box_h)), art.Image.LANCZOS)
            return image, plate
        image = art.Image.new("RGB", (max(20, box_w), max(20, int(box_w * .62))), (240, 242, 230))
        d = art.ImageDraw.Draw(image)
        d.text((8, 8), f"{cand.get('cn')}\n（暂无可用参考图）", font=art.font(self._px(11)), fill=art.INK_SOFT)
        image.thumbnail((max(20, box_w), max(20, box_h)))
        return image, None

    def _draw_flow(self, result, box):
        data = self._flow_data(box)
        canvas = self.preview
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if data is None or W < 300 or H < 90:
            return False
        from PIL import Image, ImageOps
        P = self._px
        canvas.delete("all")
        self._flow_photos = []
        arrow_w, brace_w, gap = P(30), P(14), P(8)
        label_h = P(17)
        top, bottom = P(4), H - P(4)
        fixed = arrow_w * 2 + brace_w * 2 + gap * 7
        free = max(200, W - fixed - P(10))
        frame = P(10)   # white frame + shadow around each picture
        w_photo, w_crop, w_cand, w_final = (int(free * r) for r in (.26, .15, .25, .34))
        cy = (top + bottom) / 2
        x = P(4)
        # 1) the photo the user fed in
        src = result.get("annotated_path") or result.get("source")
        try:
            with Image.open(src) as im:
                photo_img = ImageOps.exif_transpose(im).convert("RGB")
        except Exception:
            return False
        shown = photo_img.copy()
        shown.thumbnail((w_photo - frame, bottom - top - P(12)), Image.LANCZOS)
        self.preview_photo, rect = self._framed(canvas, shown, x + w_photo / 2, cy, "f_photo", src, "原图")
        x += w_photo + gap
        # 2) arrow → cropped bird
        canvas.create_line(x, cy, x + arrow_w, cy, arrow="last", width=P(2), fill=OLIVE,
                           arrowshape=(P(9), P(11), P(4)))
        x += arrow_w + gap
        crop_src = box.get("tight_crop_path") or box.get("crop_path")
        crop_rect = None
        if crop_src and Path(crop_src).is_file():
            with Image.open(crop_src) as im:
                crop_img = im.convert("RGB")
            shown = crop_img.copy()
            shown.thumbnail((w_crop - frame, int((bottom - top) * .62)), Image.LANCZOS)
            _, crop_rect = self._framed(canvas, shown, x + w_crop / 2, cy, "f_crop", crop_src,
                                        f"{box.get('bird_id', '')} 裁切图")
        canvas.create_text(x + w_crop / 2, (crop_rect[3] if crop_rect else cy) + P(12), text="对焦中...",
                           fill=INK_SOFT, font=(self.family, 8))
        x += w_crop + gap
        # 3) { top-2 candidates with confidence }
        cand_h = int((bottom - top - 2 * label_h - P(10)) / 2)
        slots = [top + cand_h / 2, top + cand_h + label_h + P(10) + cand_h / 2]
        y_brace_top, y_brace_bot = top + P(6), bottom - label_h
        self._brace(canvas, x, y_brace_top, y_brace_bot, brace_w, opening="right")
        x += brace_w + gap
        for i, cand in enumerate(data["cands"]):
            image, plate = self._plate_or_card(cand, w_cand - frame, cand_h - frame)
            sy = slots[i] if len(data["cands"]) > 1 else cy - label_h / 2
            zoom_src = plate["path"] if plate else None
            _, r = self._framed(canvas, image, x + w_cand / 2, sy, f"f_cand{i}", zoom_src,
                                f"候选 {i + 1}：{cand['cn']}（{self._pct(cand['conf'])}）")
            canvas.create_text(x + w_cand / 2, r[3] + P(9), fill=INK, font=(self.family, 9, "bold"),
                               text=f"{cand['cn']}  {self._pct(cand['conf'])}")
        x += w_cand + gap
        self._brace(canvas, x, y_brace_top, y_brace_bot, brace_w, opening="left")
        x += brace_w + gap
        # 4) arrow → final answer (field-guide plate, stamped)
        canvas.create_line(x, cy, x + arrow_w, cy, arrow="last", width=P(2), fill=OLIVE,
                           arrowshape=(P(9), P(11), P(4)))
        x += arrow_w + gap
        final = data["final"]
        hint = data["hint"]
        final_h = bottom - top - (P(50) if hint else P(34))
        image, plate = self._plate_or_card(final, w_final - frame, final_h - frame)
        stamp = self._stamp_image(result)
        if stamp is not None:
            stamp = stamp.copy()
            stamp.thumbnail((int(image.width * .5), int(image.height * .45)), Image.LANCZOS)
            image = image.convert("RGBA")
            image.alpha_composite(stamp, (image.width - stamp.width - 2, image.height - stamp.height - 2))
            image = image.convert("RGB")
        fy = top + final_h / 2 + P(2)
        _, r = self._framed(canvas, image, x + w_final / 2, fy, "f_final", plate["path"] if plate else None,
                            f"最终答案：{final['cn']}")
        conf = self._pct(final.get("conf"))
        canvas.create_text(x + w_final / 2, r[3] + P(10), fill="#3d7a1f", font=(self.family, 11, "bold"),
                           text=final["cn"])
        canvas.create_text(x + w_final / 2, r[3] + P(25), fill=INK_SOFT, font=(self.family, 8),
                           text=f"{final['source']} {conf}".strip())
        if hint is not None:
            link = canvas.create_text(x + w_final / 2, r[3] + P(41), fill=INK_SOFT, font=(self.family, 9, "underline"),
                                      text=f"好像是{hint['cn']}？", tags=("f_hint",))
            hint_plate = art.find_plate(hint.get("sci"), hint.get("cn"))
            canvas.tag_bind("f_hint", "<Button-1>", lambda e: self._zoom(
                hint_plate["path"] if hint_plate else None, f"会不会是{hint['cn']}？（{self._pct(hint['conf'])}）"))
            canvas.tag_bind("f_hint", "<Enter>", lambda e: (canvas.configure(cursor="hand2"),
                                                            canvas.itemconfigure(link, fill=OLIVE)))
            canvas.tag_bind("f_hint", "<Leave>", lambda e: (canvas.configure(cursor=""),
                                                            canvas.itemconfigure(link, fill=INK_SOFT)))
        return True

    def _brace(self, canvas, x, y1, y2, w, opening="right"):
        """Curly brace; opening="right" draws "{" (tip on the left), "left" draws "}"."""
        ym = (y1 + y2) / 2
        k = min(w, (y2 - y1) / 6)
        if opening == "right":
            xs = (x + w, x + w * .45, x)
        else:
            xs = (x, x + w * .55, x + w)
        a, b, tip = xs
        points = [a, y1, b, y1 + k, b, ym - k, tip, ym, b, ym + k, b, y2 - k, a, y2]
        canvas.create_line(*points, smooth=True, width=self._px(2), fill=OLIVE, capstyle="round")

    def _zoom(self, source, title=""):
        """Open any flow image big; click or Esc closes it."""
        if not source:
            return
        from PIL import Image, ImageOps
        try:
            with Image.open(source) as im:
                image = ImageOps.exif_transpose(im).convert("RGB")
        except Exception as exc:
            self.logger.warning("放大失败 %s：%s", source, exc)
            return
        top = tk.Toplevel(self.window)
        top.title(title or "放大看看")
        top.configure(background="#1b2210")
        top.transient(self.window)
        sw, sh = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
        image.thumbnail((int(sw * .8), int(sh * .78)), Image.LANCZOS)
        if image.width < 480:
            scale = 480 / image.width
            image = image.resize((480, int(image.height * scale)), Image.LANCZOS)
        photo = self._photo(image)
        label = tk.Label(top, image=photo, background="#1b2210", cursor="hand2")
        label.image = photo
        label.pack(padx=12, pady=(12, 4))
        tk.Label(top, text=(title + "    " if title else "") + "点图片或按 Esc 关闭", background="#1b2210",
                 foreground="#d8e4bc", font=(self.family, 10)).pack(pady=(0, 10))
        top.update_idletasks()
        x = self.window.winfo_rootx() + (self.window.winfo_width() - top.winfo_reqwidth()) // 2
        y = self.window.winfo_rooty() + (self.window.winfo_height() - top.winfo_reqheight()) // 2
        top.geometry(f"+{max(0, x)}+{max(0, y)}")
        for widget in (top, label):
            widget.bind("<Button-1>", lambda e: top.destroy())
        top.bind("<Escape>", lambda e: top.destroy())
        top.focus_set()

    def select_bird(self, event=None):
        selected = self.bird_tree.selection()
        if not selected or self.current_result is None:
            return
        box = self.current_result["boxes"][int(selected[0])]
        self.current_bird = box
        status = box.get("gate_status")
        bird_id = str(box.get("bird_id", ""))
        number = bird_id.split("_")[-1].lstrip("0") or bird_id
        lines = [(f"{number} 号嫌疑鸟", "h")]
        verdicts = {"willow": ("判定：是柳莺 ✔", "k_willow"),
                    "willow_outside_coverage": ("判定：是柳莺，但超纲了", "k_willow"),
                    "not_willow": ("判定：不是柳莺 ✘", "k_not_willow")}
        verdict = verdicts.get(status, ("判定：薛定谔的柳莺 ？", "k_uncertain"))
        lines.append(verdict)
        lines.append((str(box.get("gate_message", "无法确认")), "key"))
        outside = status == "willow_outside_coverage"
        if outside:
            coverage = (box.get("specialist_coverage") or {}).get("willow_species", 6)
            coverage_text = "六" if coverage == 6 else str(coverage)
            lines.append((f"柳莺（覆盖外）：不在{coverage_text}种专项的已知覆盖范围。", "key"))
            lines.append(("原判保留，不强行指定专项鸟种。", "note"))
        specialist = box.get("specialist")
        if isinstance(specialist, dict):
            expanded = specialist.get("version") == "willow50-global-specialist-v1"
            if expanded:
                prefix = "专项倾向相似组外鸟：" if specialist.get("decision_kind") == "similar_non_willow" else "50种专项："
                if (specialist.get("species_fusion") or {}).get("applied"):
                    prefix = "融合倾向相似组外鸟：" if specialist.get("decision_kind") == "similar_non_willow" else "融合复核："
                lines.append((prefix + str(specialist.get("common_name") or specialist.get("scientific_name") or "无法确认"), "verdict"))
                lines.append((str(specialist.get("scientific_name") or ""), "note"))
                score_scope = specialist.get("confidence_scope", "58个训练鸟种之间的分数，不是正确率")
                lines.append((f"模型分数：{specialist['confidence']:.3f}（{score_scope}）", "note"))
                for rank, candidate in enumerate(specialist.get("top3", []), 1):
                    lines.append((f"候选{rank}：{candidate['common_name']}  {candidate['confidence']:.3f}", "key"))
                lines.append(("原网络种名与检测框保留，专项结果单独展示。", "note"))
            elif specialist.get("rejected_as_OTHER") or specialist.get("global_id") == -1:
                lines.append(("专项：组外或无法确认（OTHER）", "key"))
                lines.append(("翻译：不在专项那六种里，或者照片证据不够 —— OTHER 不等于不是柳莺", "note"))
            else:
                prefix = "专项候选（仅诊断，未确认）：" if outside else "专项："
                lines.append((prefix + str(specialist.get("common_name") or specialist.get("scientific_name") or "无法确认"),
                              "verdict"))
                if specialist.get("scientific_name"):
                    lines.append((str(specialist["scientific_name"]), "note"))
                if specialist.get("confidence") is not None:
                    lines.append((f"专项组内分数：{specialist['confidence']:.3f}（六种之间的相对把握，不是正确率）", "note"))
            if specialist.get("target_probability_mass") is not None:
                scope = "50种柳莺" if expanded else "六种目标"
                lines.append((f"{scope}总分：{specialist['target_probability_mass']:.3f}", "note"))
        tip = TIPS.get("willow" if status in ("willow", "willow_outside_coverage") else
                       "not_willow" if status == "not_willow" else "uncertain")
        lines.append((tip, "tip"))
        lines.append((f"档案编号：{bird_id}", "note"))
        self._set_detail_lines(lines)
        self.crop.update_idletasks()
        self._show_image(self.crop, box.get("crop_path"), True)
        self._refresh_preview()

    def request_close(self):
        if self.closing or self.closed:
            return
        if self.backgrounded:
            self.restore_window()
        if self.exit_dialog is not None and not self.exit_dialog.closed:
            self.exit_dialog.notify_attention()
            return
        from .exit_dialog import ExitDialog
        self.exit_dialog = ExitDialog(self)

    def push_to_background(self):
        if self.closing or self.closed:
            return
        self._background_pending = True
        try:
            if self.tray is None:
                from .resident import Tray
                self.tray = Tray(self)
            if not self.tray.show():
                if self.exit_dialog:
                    self.exit_dialog.set_message('正在给小鸟留一个托盘位置…')
                return
        except Exception as exc:
            self._background_pending = False
            self.logger.exception('后台托盘启动失败')
            if self.exit_dialog:
                self.exit_dialog.set_message('暂时无法进入后台，请最小化窗口。' + str(exc))
            return
        self._background_pending = False
        if self.exit_dialog is not None:
            self.exit_dialog.close(); self.exit_dialog = None
        self.audio.stop()
        self._hidden_children = []
        for child in self.window.winfo_children():
            if isinstance(child, tk.Toplevel) and child.winfo_viewable():
                self._hidden_children.append((child, child.state())); child.withdraw()
        self._restore_state = self.window.state()
        self.backgrounded = True
        if self.scene is not None:
            self.scene.suspended = True
        self.window.withdraw()
        self.logger.info('进入后台：保留识别器与当前照片，不卸载模型')

    def restore_window(self, images=()):
        if self.closed:
            return
        self._background_pending = False
        from .instance import foreground
        foreground(self.window)
        if self.backgrounded and getattr(self, '_restore_state', '') == 'zoomed':
            self.window.state('zoomed')
        self.backgrounded = False
        if self.tray is not None:
            self.tray.hide()
        if self.scene is not None:
            self.scene.suspended = False
        for child, state in self._hidden_children:
            try:
                if child.winfo_exists():child.deiconify();child.state(state)
            except tk.TclError:pass
        self._hidden_children = []
        if self.exit_dialog is not None and not self.exit_dialog.closed:
            self.exit_dialog.panel.lift(); self.exit_dialog.background_button.focus_set()
        if images and not self.closing:
            self.add_paths(images)
        self.logger.info('唤回原窗口：复用现有识别器')

    def _resident_poll(self):
        if self.closed:
            return
        if self.instance is not None:
            for request in self.instance.poll():
                self.restore_window(request.get('images', ()))
        if self.tray is not None:
            try:
                while True:
                    action = self.tray.actions.get_nowait()
                    if action == 'restore':self.restore_window()
                    elif action == 'exit':self.restore_window();self.quit_application()
                    elif action == 'failed':
                        self._background_pending = False
                        self.restore_window()
                        if self.exit_dialog:
                            self.exit_dialog.set_message('托盘启动失败，请先最小化窗口：' + str(self.tray.failed))
            except queue.Empty:pass
        if self._background_pending and not self.closing:
            self.push_to_background()
        self._resident_id = self.window.after(120, self._resident_poll)

    def quit_application(self):
        if self.closing:
            return
        self._background_pending = False
        if self.exit_dialog is not None:
            self.exit_dialog.close(); self.exit_dialog = None
        self.closing = True
        self.audio.stop()
        if self.scene is not None:
            self.scene.close()
        self.cancel_pending()
        self._set_busy(True)
        self.worker.commands.put(None)
        self.status.set("正在收摊……等手上这只认完就关门。")


def main(app_root, package_root, images=(), config=None, instance=None):
    window = tk.Tk()
    WillowApplication(window, app_root, package_root, initial_images=images, config=config, instance=instance)
    window.mainloop()
