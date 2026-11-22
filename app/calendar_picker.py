"""Offline date/time picker built with Tk and Python's calendar module."""
from .i18n import tr
import calendar
from datetime import date, datetime
import tkinter as tk
from tkinter import ttk


class CalendarPicker(tk.Toplevel):
    def __init__(self, parent, value="", on_select=None, family="Microsoft YaHei UI"):
        super().__init__(parent)
        self.title(tr("选择拍摄日期与时间"))
        self.configure(background="#f6f3e2")
        self.resizable(False, False)
        self.transient(parent)
        self.on_select = on_select
        self.family = family
        initial = None
        if value:
            try:
                initial = datetime.fromisoformat(str(value))
            except ValueError:
                pass
        today = date.today()
        self.selected_date = initial.date() if initial else today
        self.year = tk.StringVar(self, str(self.selected_date.year))
        self.month = tk.StringVar(self, f"{self.selected_date.month:02d}")
        self.with_time = tk.BooleanVar(self, bool(value and (" " in str(value) or "T" in str(value))))
        self.hour = tk.StringVar(self, f"{initial.hour if initial else 8:02d}")
        self.minute = tk.StringVar(self, f"{initial.minute if initial else 0:02d}")
        self.day_buttons = {}
        self._build()
        self._render_month()
        self._sync_time()
        self.bind("<Escape>", lambda event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self.geometry(f"+{max(0, parent.winfo_rootx() + 60)}+{max(0, parent.winfo_rooty() + 80)}")
        self.grab_set()

    def _button(self, parent, text, command, **kwargs):
        return tk.Button(parent, text=text, command=command, background="#fffdf4", foreground="#466d2d",
                         activebackground="#e5edce", relief="flat", font=(self.family, 10),
                         padx=10, pady=5, cursor="hand2", **kwargs)

    def _build(self):
        header = tk.Frame(self, background="#f6f3e2")
        header.pack(fill="x", padx=14, pady=(14, 8))
        self._button(header, "‹", lambda: self.move_month(-1)).pack(side="left")
        self.year_box = ttk.Combobox(header, textvariable=self.year, state="readonly", width=6,
                                     values=[str(year) for year in range(1900, 2101)])
        self.year_box.pack(side="left", padx=(8, 3))
        tk.Label(header, text=tr("年"), background="#f6f3e2", foreground="#687052").pack(side="left")
        self.month_box = ttk.Combobox(header, textvariable=self.month, state="readonly", width=4,
                                      values=[f"{month:02d}" for month in range(1, 13)])
        self.month_box.pack(side="left", padx=(8, 3))
        tk.Label(header, text=tr("月"), background="#f6f3e2", foreground="#687052").pack(side="left")
        self._button(header, "›", lambda: self.move_month(1)).pack(side="right")
        self.year_box.bind("<<ComboboxSelected>>", lambda event: self._render_month())
        self.month_box.bind("<<ComboboxSelected>>", lambda event: self._render_month())
        self.days_frame = tk.Frame(self, background="#f6f3e2")
        self.days_frame.pack(padx=14)
        self.chosen = tk.StringVar(self, "")
        tk.Label(self, textvariable=self.chosen, background="#f6f3e2", foreground="#466d2d",
                 font=(self.family, 10, "bold")).pack(fill="x", padx=15, pady=9)
        time_row = tk.Frame(self, background="#f6f3e2")
        time_row.pack(fill="x", padx=14)
        tk.Checkbutton(time_row, text=tr("同时记录时分"), variable=self.with_time, command=self._sync_time,
                       background="#f6f3e2", foreground="#687052", font=(self.family, 10)).pack(side="left")
        self.hour_box = ttk.Combobox(time_row, textvariable=self.hour, state="readonly", width=3,
                                     values=[f"{hour:02d}" for hour in range(24)])
        self.hour_box.pack(side="left", padx=(7, 2))
        tk.Label(time_row, text=":", background="#f6f3e2").pack(side="left")
        self.minute_box = ttk.Combobox(time_row, textvariable=self.minute, state="readonly", width=3,
                                       values=[f"{minute:02d}" for minute in range(60)])
        self.minute_box.pack(side="left", padx=2)
        actions = tk.Frame(self, background="#f6f3e2")
        actions.pack(fill="x", padx=14, pady=14)
        self._button(actions, tr("不确定 / 清除"), self.clear).pack(side="left")
        self._button(actions, tr("今天"), self.choose_today).pack(side="left", padx=7)
        self._button(actions, tr("确定"), self.confirm).pack(side="right")

    def _sync_time(self):
        state = "readonly" if self.with_time.get() else "disabled"
        self.hour_box.configure(state=state)
        self.minute_box.configure(state=state)

    def _render_month(self):
        for widget in self.days_frame.winfo_children():
            widget.destroy()
        self.day_buttons = {}
        year, month = int(self.year.get()), int(self.month.get())
        for column, title in enumerate((tr("一"), tr("二"), tr("三"), tr("四"), tr("五"), tr("六"), tr("日"))):
            tk.Label(self.days_frame, text=title, background="#f6f3e2", foreground="#687052",
                     font=(self.family, 10), width=4).grid(row=0, column=column, pady=5)
        for row, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(year, month), 1):
            for column, day in enumerate(week):
                if day:
                    button = self._button(self.days_frame, str(day), lambda value=day: self.choose_day(value), width=3)
                    button.grid(row=row, column=column, padx=1, pady=1)
                    if self.selected_date == date(year, month, day):
                        button.configure(background="#466d2d", foreground="white")
                    self.day_buttons[day] = button
        self.chosen.set(tr("已选：") + self.selected_date.isoformat())

    def move_month(self, amount):
        year, month = int(self.year.get()), int(self.month.get())
        serial = year * 12 + month - 1 + amount
        year, month = divmod(serial, 12)
        if 1900 <= year <= 2100:
            self.year.set(str(year))
            self.month.set(f"{month + 1:02d}")
            self._render_month()

    def choose_day(self, day):
        self.selected_date = date(int(self.year.get()), int(self.month.get()), int(day))
        self._render_month()

    def choose_today(self):
        self.selected_date = date.today()
        self.year.set(str(self.selected_date.year))
        self.month.set(f"{self.selected_date.month:02d}")
        self._render_month()

    def confirm(self):
        value = self.selected_date.isoformat()
        if self.with_time.get():
            value += f" {int(self.hour.get()):02d}:{int(self.minute.get()):02d}"
        if self.on_select:
            self.on_select(value)
        self.destroy()

    def clear(self):
        if self.on_select:
            self.on_select("")
        self.destroy()
