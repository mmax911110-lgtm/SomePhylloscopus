"""Side-by-side identification using the annotated plates from the local foldout."""
import tkinter as tk
from tkinter import ttk
from unicodedata import normalize

from .art import load_plates
from .library_ui import CARD, GREEN, INK, LINE, PAPER, SELECT, SOFT


def guide_plate(bird, plates):
    scientific = (bird.get("scientific_name") or "").strip().casefold()
    common = (bird.get("common_name") or "").strip()
    # The foldout uses older combinations; the epithet affinis occurs twice.
    return (next((p for p in plates if p["scientific_name"].casefold() == scientific), None)
            or next((p for p in plates if p["name_cn"] == common), None))


def _query_key(text):
    return " ".join(normalize("NFKC", text).casefold().replace("_", " ").split())


def _search_names(bird):
    scientific = _query_key(bird.get("scientific_name") or "")
    common = _query_key(bird.get("common_name") or "")
    keys = {name for name in (scientific, common) if name}
    genus, _, species = scientific.partition(" ")
    if genus and species:
        keys.add(species)
        keys.add(f"{genus[0]}. {species}")
        keys.add(f"{genus[0]}.{species}")
    return keys


class _PlateCanvas(tk.Canvas):
    def __init__(self, parent, view, plate):
        super().__init__(parent, background="white", highlightthickness=0, width=1, height=1,
                         cursor="hand2", takefocus=True)
        self.view, self.plate = view, plate
        self._timer = self.photo = None
        self.bind("<Configure>", self._resize)
        for event in ("<Button-1>", "<Return>", "<space>"):
            self.bind(event, self._zoom)

    def _resize(self, event):
        if self._timer is not None:
            self.after_cancel(self._timer)
        self._timer = self.after_idle(self._draw) if self.photo is None else self.after(60, self._draw)

    def _draw(self):
        self._timer = None
        w, h = self.winfo_width(), self.winfo_height()
        self.photo = self.view._image(self.plate["path"], (max(w - 12, 1), max(h - 12, 1)))
        self.delete("all")
        if self.photo:
            self.create_image(w / 2, h / 2, image=self.photo)
        else:
            self.create_text(w / 2, h / 2, text="本地图版暂时无法读取", fill=SOFT)

    def _zoom(self, event):
        viewer = self.view._open_image(self.plate["path"], self.plate["name_cn"] + " · 折页原图", parent=self.winfo_toplevel())
        if viewer is not None:
            viewer.transient(self.winfo_toplevel())
            viewer.lift()

    def destroy(self):
        if self._timer is not None:
            self.after_cancel(self._timer)
            self._timer = None
        super().destroy()


class PlateComparison(tk.Toplevel):
    def __init__(self, view, birds):
        super().__init__(view.window)
        self.view, self.birds, self.plates = view, birds, load_plates()
        self.names = {p["no"]: _search_names(dict(common_name=p["name_cn"], scientific_name=p["scientific_name"]))
                      for p in self.plates}
        for card in view.library.catalog.values():
            plate = guide_plate(card, self.plates)
            if plate:
                self.names[plate["no"]].update(_search_names(card))
        self.title("识别对比 · 柳莺折页")
        self.configure(background=PAPER)
        self.transient(view.window)
        self.geometry(f"{min(1100, self.winfo_screenwidth() - 50)}x{min(630, self.winfo_screenheight() - 90)}")
        self.minsize(650, 400)
        self.bind("<Escape>", lambda e: self.destroy())
        bar = tk.Frame(self, background=PAPER)
        bar.pack(fill="x", padx=16, pady=(12, 7))
        view._label(bar, "识别对比", 17, GREEN, True).pack(side="left")
        if len(birds) > 1:
            view._label(bar, "选择档案中的鸟", 10, SOFT).pack(side="left", padx=(18, 6))
            self.bird_box = ttk.Combobox(bar, state="readonly", width=24, values=[
                f"{n} 号鸟 · {b.get('common_name') or b.get('scientific_name') or '鸟种未确认'}"
                for n, b in enumerate(birds, 1)])
            self.bird_box.current(0)
            self.bird_box.pack(side="left")
            self.bird_box.bind("<<ComboboxSelected>>", lambda e: self._set_anchor(self.bird_box.current()))
        note = "图版来源：《两岸三地50种柳莺类辨识》简体版（2013） · 点击图版可放大查看标注"
        view._label(self, note, 9, SOFT, anchor="w").pack(side="bottom", fill="x", padx=16, pady=(4, 12))
        panes = tk.Frame(self, background=PAPER)
        panes.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        panes.rowconfigure(0, weight=1)
        self.sides = []
        for n in range(2):
            panes.columnconfigure(n, weight=1, uniform="plate")
            side = tk.Frame(panes, background=CARD, highlightbackground=LINE, highlightthickness=1)
            side.grid(row=0, column=n, sticky="nsew", padx=(0, 5) if n == 0 else (5, 0))
            self.sides.append(side)
        self.query = tk.StringVar(self)
        self.query.trace_add("write", lambda *_: self._filter())
        self._set_anchor(0)

    def _set_anchor(self, index):
        bird = self.birds[index]
        self.anchor_plate = guide_plate(bird, self.plates)
        left = self.sides[0]
        self.view._clear(left)
        name = bird.get("common_name") or bird.get("scientific_name") or "鸟种未确认"
        self._heading(left, "当前鸟种", name, bird.get("scientific_name"))
        if self.anchor_plate:
            self._picture(left, self.anchor_plate)
        else:
            self.view._label(left, "本地折页中没有这只鸟的图版。", 11, SOFT).pack(expand=True)
        self._picker()

    def _heading(self, parent, role, name, scientific, change=False):
        line = tk.Frame(parent, background=CARD)
        line.pack(fill="x", padx=12, pady=(10, 0))
        line.columnconfigure(0, weight=1)
        self.view._label(line, role, 9, SOFT).grid(row=0, column=0, sticky="w")
        self.view._label(line, name, 17, GREEN, True).grid(row=1, column=0, sticky="w")
        if change:
            self.view._button(line, "换一种鸟", self._picker).grid(row=0, column=1, rowspan=2, sticky="ne")
        self.view._label(parent, scientific or "", 10, SOFT, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

    def _picture(self, side, plate):
        _PlateCanvas(side, self.view, plate).pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _picker(self):
        right = self.sides[1]
        self.view._clear(right)
        self.listbox = None
        if not self.anchor_plate:
            self.view._label(right, "需要两张折页图版才能并排对比。", 11, SOFT).pack(expand=True)
            return
        self.view._label(right, "选择另一种鸟", 15, GREEN, True, anchor="w").pack(fill="x", padx=12, pady=(12, 3))
        self.view._label(right, "输入中文名或学名（如 P. inornatus），回车或点击对比。", 9, SOFT, anchor="w",
                         justify="left", wraplength=300).pack(fill="x", padx=12)
        self.query.set("")
        search = ttk.Entry(right, textvariable=self.query, font=(self.view.family, 11))
        search.pack(fill="x", padx=12, pady=7)
        search.bind("<Return>", lambda e: self._choose(0))
        search.bind("<Down>", self._focus_results)
        box = tk.Frame(right, background=CARD)
        box.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.listbox = tk.Listbox(box, width=1, font=(self.view.family, 11), bg=CARD, fg=INK,
                                  relief="flat", selectbackground=SELECT, selectforeground=GREEN,
                                  highlightcolor=GREEN, highlightbackground=LINE, exportselection=False)
        scroll = ttk.Scrollbar(box, command=self.listbox.yview)
        scroll.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<ButtonRelease-1>", self._click)
        self.listbox.bind("<Return>", lambda e: self._choose(self.listbox.index("active")))
        self.count = self.view._label(right, "", 9, SOFT, anchor="w")
        self.count.pack(fill="x", padx=12, pady=(0, 8))
        self._filter()
        search.focus_set()

    def _filter(self):
        if self.listbox is None:
            return
        term = _query_key(self.query.get())
        words = term.split()
        latin = [w for w in words if w.isascii()]
        other = [w for w in words if not w.isascii()]
        def matches(names):
            return ((not latin or any(all(w in name for w in latin) for name in names))
                    and all(any(w in name for name in names) for w in other))
        self.options = [p for p in self.plates if p["no"] != self.anchor_plate["no"] and
                        (not term or matches(self.names[p["no"]]))]
        if term:
            self.options.sort(key=lambda p: term not in self.names[p["no"]])
        self.listbox.delete(0, "end")
        if self.options:
            self.listbox.insert("end", *(f"{p['name_cn']}  ·  {p['scientific_name']}" for p in self.options))
        self.count.configure(text=f"可选 {len(self.options)} 种" if self.options else "没有匹配的图版，请换个名字试试。")

    def _focus_results(self, event):
        if self.options:
            self.listbox.focus_set()
            self.listbox.activate(0)
            self.listbox.selection_set(0)
            self.listbox.see(0)
        return "break"

    def _click(self, event):
        idx = self.listbox.nearest(event.y)
        bounds = self.listbox.bbox(idx) if self.options else None
        if bounds and bounds[1] <= event.y < bounds[1] + bounds[3]:
            self._choose(idx)

    def _choose(self, idx):
        if 0 <= idx < len(self.options):
            p = self.options[idx]
            self.listbox = None
            right = self.sides[1]
            self.view._clear(right)
            self._heading(right, "对比鸟种", p["name_cn"], p["scientific_name"], change=True)
            self._picture(right, p)
