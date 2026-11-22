"""Viewport-sized bird cards, drawn with a reusable pool of Tk Canvas items.

No model/database work lives here. ``owner`` supplies the existing reference
image lookup and species-detail callback. Only pixel preparation runs outside Tk.
"""
from .i18n import species_name, tr

from collections import deque, OrderedDict
from functools import lru_cache
import math
import tkinter as tk
from tkinter import font as tkfont, ttk


PAPER = "#f6f3e2"
CARD = "#fffdf4"
GREEN = "#466d2d"
SOFT = "#687052"
LINE = "#d9dfbd"
ACCENT = "#7ea24a"
OUTGROUP = "#a39a7c"


def _willow(card):
    value = card.get("is_willow")
    if value is None:
        value = str(card.get("scientific_name") or "").split(" ", 1)[0] == "Phylloscopus"
    return bool(value)


class SpeciesCardList(tk.Frame):
    """A list whose number of drawing items depends on viewport height, not rows.

    Public API: ``canvas``, ``set_cards(cards, selected=None)``,
    ``set_selected(scientific_name)``, ``contains_pointer(x, y)`` and ``close()``.
    ``owner._image`` must return a Tk PhotoImage or None. Images stay alive while
    their slots are displayed, even when the owner's bounded cache evicts them.
    """

    def __init__(self, parent, owner, on_drawn=None, thumbnail_loader=None):
        super().__init__(parent, background=PAPER)
        self.owner = owner
        self.on_drawn = on_drawn
        self._thumbnail_loader = thumbnail_loader
        self._worker = self._inflight = None
        self._thumbs = OrderedDict()
        self._layout_key = None
        self._closed = False
        self._draw_after = None
        self._scroll_region = None
        self.canvas = tk.Canvas(self, background=PAPER, highlightthickness=0,
                                bd=0, width=1, height=1, takefocus=True)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._scrolled)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._fonts = {
            "name": tkfont.Font(root=self, family=owner.family, size=13, weight="bold"),
            "scientific": tkfont.Font(root=self, family=owner.family, size=9, slant="italic"),
            "note": tkfont.Font(root=self, family=owner.family, size=9),
            "count": tkfont.Font(root=self, family=owner.family, size=9, weight="bold"),
        }
        self._name_height = self._fonts["name"].metrics("linespace")
        self._measure = {key: lru_cache(maxsize=256)(font.measure) for key, font in self._fonts.items()}
        self._sci_height = self._fonts["scientific"].metrics("linespace")
        self._note_height = self._fonts["note"].metrics("linespace")
        self.row_height = max(120, 2 * self._name_height + self._sci_height + self._note_height + 40)
        self._cards = []
        self._indices = {}
        self._selected = None
        self._hovered = None
        self._slots = []
        self._generation = 0
        self._render_serial = 0
        self._draw_after = None
        self._thumb_after = None
        self._pending = deque()
        self._closed = False
        self._empty = self.canvas.create_text(20, 24, anchor="nw", text=tr("当前分区没有匹配的鸟种卡。"),
                                              fill=SOFT, font=self._fonts["note"], state="hidden")
        self.canvas.bind("<Configure>", self._schedule_draw, add="+")
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda event: self._wheel(event, -1))
        self.canvas.bind("<Button-5>", lambda event: self._wheel(event, 1))
        for key in ("Up", "Down", "Home", "End", "Prior", "Next", "Return", "space"):
            self.canvas.bind(f"<{key}>", self._key)
        self.canvas.configure(yscrollincrement=24)

    def set_cards(self, cards, selected=None):
        previous = tuple(self._indices)
        self._cards = list(cards)
        self._indices = {str(card.get("scientific_name") or ""): i
                         for i, card in enumerate(self._cards)}
        self._selected = selected
        self._hovered = None
        self._generation += 1
        self._pending.clear()
        self._update_scroll_region()
        if tuple(self._indices) != previous:
            self.canvas.yview_moveto(0)
        if selected in self._indices:
            self._ensure_visible(self._indices[selected])
        self._schedule_draw()

    def set_selected(self, scientific_name):
        self._selected = scientific_name
        if scientific_name in self._indices:
            self._ensure_visible(self._indices[scientific_name])
        for slot in self._slots:
            self._paint_border(slot)

    def contains_pointer(self, x, y):
        if self._closed or not self.winfo_ismapped():
            return False
        left, top = self.winfo_rootx(), self.winfo_rooty()
        return left <= x < left + self.winfo_width() and top <= y < top + self.winfo_height()

    def _scrolled(self, first, last):
        self.scrollbar.set(first, last)
        self._schedule_draw()

    def _schedule_draw(self, event=None):
        if not self._closed and self._draw_after is None:
            self._draw_after = self.after_idle(self._draw)

    def _update_scroll_region(self):
        region = (0, 0, max(1, self.canvas.winfo_width()), max(1, len(self._cards) * self.row_height))
        if region != self._scroll_region:
            self._scroll_region = region
            self.canvas.configure(scrollregion=region)

    def _make_slot(self):
        c = self.canvas
        return {
            "border": c.create_rectangle(0, 0, 1, 1, fill=CARD, outline=LINE),
            "accent": c.create_rectangle(0, 0, 1, 1, fill=ACCENT, outline=""),
            "image": c.create_image(0, 0, anchor="center"),
            "placeholder": c.create_text(0, 0, text="暂无参考图", fill=SOFT, font=self._fonts["note"]),
            "name": c.create_text(0, 0, anchor="nw", fill=GREEN, font=self._fonts["name"]),
            "scientific": c.create_text(0, 0, anchor="nw", fill=SOFT, font=self._fonts["scientific"]),
            "note": c.create_text(0, 0, anchor="nw", fill="#7c8266", font=self._fonts["note"]),
            "badge": c.create_rectangle(0, 0, 1, 1, fill=GREEN, outline=""),
            "count": c.create_text(0, 0, anchor="center", fill="white", font=self._fonts["count"]),
            "index": None, "photo": None, "loaded_key": None, "visible": True,
        }

    @staticmethod
    def _item_ids(slot):
        return (slot[key] for key in ("border", "accent", "image", "placeholder", "name",
                                     "scientific", "note", "badge", "count"))

    def _fit(self, text, measure, width):
        text = str(text)
        if measure(text) <= width:
            return text
        if width <= measure("…"):
            return "…"
        lo, hi = 0, len(text)
        while lo < hi:
            middle = (lo + hi + 1) // 2
            if measure(text[:middle] + "…") <= width:
                lo = middle
            else:
                hi = middle - 1
        return text[:lo] + "…"

    def _title_lines(self, text, width):
        text = str(text)
        measure = self._measure["name"]
        if measure(text) <= width:
            return text
        lo, hi = 1, len(text)
        while lo < hi:
            middle = (lo + hi + 1) // 2
            if measure(text[:middle]) <= width:
                lo = middle
            else:
                hi = middle - 1
        return text[:lo] + "\n" + self._fit(text[lo:], measure, width)

    def _draw(self):
        self._draw_after = None
        if self._closed or not self.winfo_exists():
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 40 or height < 2:
            return
        self._update_scroll_region()
        top = max(0, self.canvas.canvasy(0))
        start = max(0, int(top // self.row_height) - 1)
        end = min(len(self._cards), math.ceil((top + height) / self.row_height) + 1)
        layout = (self._generation, width, start, end)
        if layout == self._layout_key:
            if self.on_drawn:
                self.on_drawn()
            return
        self._layout_key = layout
        self._render_serial += 1
        serial = self._render_serial
        self._pending.clear()
        self.canvas.itemconfigure(self._empty, state="hidden" if self._cards else "normal")
        needed = max(0, end - start)
        while len(self._slots) < needed:
            self._slots.append(self._make_slot())
        for position, slot in enumerate(self._slots):
            if position >= needed:
                if not slot["visible"]:
                    continue
                for item in self._item_ids(slot):
                    self.canvas.itemconfigure(item, state="hidden")
                slot.update(index=None, photo=None, loaded_key=None, visible=False)
                self.canvas.itemconfigure(slot["image"], image="")
                continue
            index = start + position
            card = self._cards[index]
            sci = str(card.get("scientific_name") or "")
            key = (self._generation, index, sci)
            if slot["loaded_key"] != key:
                slot["photo"] = None
                self.canvas.itemconfigure(slot["image"], image="")
            slot.update(index=index, species=sci, serial=serial)
            if not slot["visible"]:
                for item in self._item_ids(slot):
                    self.canvas.itemconfigure(item, state="normal")
                slot["visible"] = True
            y, bottom = index * self.row_height + 1, (index + 1) * self.row_height - 8
            c = self.canvas
            c.coords(slot["border"], 2, y, width - 6, bottom)
            c.coords(slot["accent"], 3, y + 1, 7, bottom - 1)
            c.itemconfigure(slot["accent"], fill=ACCENT if _willow(card) else OUTGROUP)
            c.coords(slot["image"], 69, (y + bottom) / 2)
            c.coords(slot["placeholder"], 69, (y + bottom) / 2)
            c.itemconfigure(slot["placeholder"], state="hidden" if slot["photo"] else "normal")
            text_x, text_y = 133, y + 10
            text_width = max(40, width - text_x - 18)
            count = int(card.get("observation_count") or 0)
            count_text = tr("{0} 次").format(count)
            badge_w = self._measure["count"](count_text) + 12 if count else 0
            # Keep counts beside the final caption so long Chinese names retain
            # the full text column instead of being squeezed by a top badge.
            title = self._title_lines(species_name(card.get("common_name"), sci), text_width)
            c.coords(slot["name"], text_x, text_y)
            c.itemconfigure(slot["name"], text=title)
            sci_y = text_y + self._name_height * (title.count("\n") + 1) + 3
            c.coords(slot["scientific"], text_x, sci_y)
            c.itemconfigure(slot["scientific"], text=self._fit(sci, self._measure["scientific"], text_width))
            note_y = bottom - self._note_height - 12
            images = int(card.get("image_count") or 0)
            note = (tr("{0} 张照片").format(images) if images else tr("还没有本地照片"))
            if not _willow(card):
                note += tr(" · 非柳莺")
            c.coords(slot["note"], text_x, note_y)
            c.itemconfigure(slot["note"], text=self._fit(note, self._measure["note"],
                                                       text_width - (badge_w + 6 if count else 0)))
            if count:
                c.itemconfigure(slot["badge"], state="normal")
                bx, by = width - 16 - badge_w, note_y - 2
                c.coords(slot["badge"], bx, by, bx + badge_w, by + self._note_height + 4)
                c.coords(slot["count"], bx + badge_w / 2, by + (self._note_height + 4) / 2)
                c.itemconfigure(slot["count"], text=count_text, state="normal")
            else:
                c.itemconfigure(slot["badge"], state="hidden")
                c.itemconfigure(slot["count"], state="hidden")
            self._paint_border(slot)
            if slot["loaded_key"] != key:
                self._pending.append((self._generation, serial, position, index, sci))
        if self._pending and self._thumb_after is None:
            self._thumb_after = self.after(1, self._load_next_thumbnail)
        if self.on_drawn:
            self.on_drawn()

    def _paint_border(self, slot):
        if slot.get("index") is None:
            return
        selected = slot.get("species") == self._selected
        colour = GREEN if selected else ACCENT if slot["index"] == self._hovered else LINE
        self.canvas.itemconfigure(slot["border"], outline=colour, width=2 if selected else 1)

    def _load_next_thumbnail(self):
        self._thumb_after = None
        if self._closed:
            return
        if self._inflight:
            future, job, key = self._inflight
            if not future.done():
                self._thumb_after = self.after(10, self._load_next_thumbnail)
                return
            self._inflight = None
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(future.result(), master=self)
                self._thumbs[key] = photo
                if len(self._thumbs) > 32:
                    self._thumbs.popitem(last=False)
            except (OSError, ValueError, tk.TclError):
                photo = None
            self._apply_thumbnail(job, photo)
        while self._pending:
            job = self._pending.popleft()
            generation, serial, position, index, sci = job
            if generation != self._generation or position >= len(self._slots):
                continue
            slot = self._slots[position]
            if slot.get("serial") != serial or slot.get("index") != index:
                continue
            photo = None
            try:
                path, _ = self.owner._reference_image(self._cards[index])
                if path and self._thumbnail_loader is None:
                    photo = self.owner._image(path, (104, 76), cover=True, radius=8, background=CARD)
                elif path:
                    from pathlib import Path
                    path = Path(path)
                    stat = path.stat()
                    key = (path, stat.st_size, stat.st_mtime_ns)
                    if key in self._thumbs:
                        self._thumbs.move_to_end(key)
                        photo = self._thumbs[key]
                    else:
                        if self._worker is None:
                            from concurrent.futures import ThreadPoolExecutor
                            self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bird-card-thumbnail")
                        self._inflight = (self._worker.submit(self._thumbnail_loader, path), job, key)
                        self._thumb_after = self.after(10, self._load_next_thumbnail)
                        return
            except (OSError, ValueError, tk.TclError):
                pass
            self._apply_thumbnail(job, photo)
            break
        if self._pending and not self._closed:
            self._thumb_after = self.after(1, self._load_next_thumbnail)

    def _apply_thumbnail(self, job, photo):
        generation, serial, position, index, sci = job
        slot = self._slots[position]
        if generation == self._generation and slot.get("serial") == serial and slot.get("species") == sci:
            slot["photo"] = photo
            slot["loaded_key"] = (generation, index, sci)
            self.canvas.itemconfigure(slot["image"], image=photo or "")
            self.canvas.itemconfigure(slot["placeholder"], state="hidden" if photo else "normal")

    def _index_at(self, y):
        index = int(self.canvas.canvasy(y) // self.row_height)
        return index if 0 <= index < len(self._cards) else None

    def _click(self, event):
        self.canvas.focus_set()
        index = self._index_at(event.y)
        if index is not None:
            self._choose(index)
        return "break"

    def _choose(self, index):
        if not 0 <= index < len(self._cards):
            return
        sci = str(self._cards[index].get("scientific_name") or "")
        self.owner.choose_species(sci)

    def _motion(self, event):
        index = self._index_at(event.y)
        if index != self._hovered:
            self._hovered = index
            self.canvas.configure(cursor="hand2" if index is not None else "")
            for slot in self._slots:
                self._paint_border(slot)

    def _leave(self, event):
        self._hovered = None
        for slot in self._slots:
            self._paint_border(slot)

    def _wheel(self, event, units=None):
        if units is None:
            delta = getattr(event, "delta", 0)
            units = int(-delta / 120) or (-1 if delta > 0 else 1)
        self.canvas.yview_scroll(units * 3, "units")
        return "break"

    def _ensure_visible(self, index):
        height = self.canvas.winfo_height()
        if height < 2:
            return
        top = self.canvas.canvasy(0)
        row_top, row_bottom = index * self.row_height, (index + 1) * self.row_height
        target = row_top if row_top < top else row_bottom - height if row_bottom > top + height else None
        if target is not None:
            total = max(1, len(self._cards) * self.row_height)
            self.canvas.yview_moveto(max(0, target) / total)

    def _key(self, event):
        if not self._cards:
            return "break"
        index = self._indices.get(self._selected, -1)
        page = max(1, self.canvas.winfo_height() // self.row_height - 1)
        key = event.keysym
        if key == "Home":
            index = 0
        elif key == "End":
            index = len(self._cards) - 1
        elif key in ("Up", "Prior"):
            index = max(0, index - (page if key == "Prior" else 1))
        elif key in ("Down", "Next"):
            index = min(len(self._cards) - 1, index + (page if key == "Next" else 1))
        elif index < 0:
            index = 0
        self._choose(index)
        return "break"

    def close(self):
        if self._closed:
            return
        self._closed = True
        for timer in (self._draw_after, self._thumb_after):
            if timer is not None:
                try:
                    self.after_cancel(timer)
                except tk.TclError:
                    pass
        self._draw_after = self._thumb_after = None
        self._pending.clear()
        if self._worker is not None:
            self._worker.shutdown(wait=False, cancel_futures=True)
        self._inflight = None
        self._thumbs.clear()
        for slot in self._slots:
            slot["photo"] = None
        self._cards.clear()
        self._indices.clear()

    def destroy(self):
        self.close()
        super().destroy()


def prepare_card_tile(path):
    from .display_images import load_thumbnail
    from .library_ui import _rounded
    return _rounded(load_thumbnail(path, (104, 76), cover=True), 8, CARD)
