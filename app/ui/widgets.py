"""画面で共通に使う小さな部品。"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..logger import get_logger

log = get_logger("ui")

PAD = {"padx": 6, "pady": 3}


class ScrollableFrame(ttk.Frame):
    """縦スクロールできる枠。中身は ``inner`` に配置する。"""

    def __init__(self, master, height: int | None = None, **kw) -> None:
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        if height:
            self.canvas.configure(height=height)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda _e: self._bind_wheel())
        self.canvas.bind("<Leave>", lambda _e: self._unbind_wheel())

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    def _bind_wheel(self) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel)
        self.canvas.bind_all("<Button-5>", self._on_wheel)

    def _unbind_wheel(self) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event) -> None:
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")


class TextArea(ttk.Frame):
    """スクロールバー付きの複数行テキスト。"""

    def __init__(self, master, height: int = 8, width: int = 60, **kw) -> None:
        super().__init__(master, **kw)
        self.text = tk.Text(self, height=height, width=width, wrap="char", undo=True)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value or "")
        self.text.edit_reset()

    def set_enabled(self, enabled: bool) -> None:
        self.text.configure(state="normal" if enabled else "disabled")


def add_entry_row(parent, row: int, label: str, var: tk.StringVar, width: int = 40,
                  column: int = 0, **entry_kw) -> ttk.Entry:
    """「ラベル：入力欄」の1行を grid で配置する。"""
    ttk.Label(parent, text=label).grid(row=row, column=column, sticky="e", **PAD)
    entry = ttk.Entry(parent, textvariable=var, width=width, **entry_kw)
    entry.grid(row=row, column=column + 1, sticky="we", **PAD)
    return entry


def open_folder(path: Path) -> None:
    """エクスプローラー等でフォルダを開く。失敗しても例外は投げない。"""
    try:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:  # noqa: BLE001
        log.warning("フォルダを開けませんでした: %s (%s)", path, e)
