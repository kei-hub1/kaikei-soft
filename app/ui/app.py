"""メインウィンドウ（タブで各画面を切り替える）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from ..logger import get_logger
from ..repositories import Repositories
from .customers_tab import CustomersTab
from .main_tab import MainTab
from .settings_tab import SettingsTab
from .templates_tab import TemplatesTab

log = get_logger("ui.app")

APP_TITLE = "定型文書作成ツール"


class App(tk.Tk):
    def __init__(self, repos: Repositories) -> None:
        super().__init__()
        self.repos = repos
        self.title(APP_TITLE)
        self.geometry("1150x780")
        self.minsize(960, 640)
        self._setup_fonts()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        self.status_var = tk.StringVar(value="")
        status = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(6, 2))
        status.pack(fill="x", side="bottom")

        self.tab_main = MainTab(self.notebook, repos, self.set_status)
        self.tab_customers = CustomersTab(self.notebook, repos, self.set_status)
        self.tab_templates = TemplatesTab(self.notebook, repos, self.set_status)
        self.tab_settings = SettingsTab(self.notebook, repos, self.set_status)
        self.notebook.add(self.tab_main, text="  文書作成  ")
        self.notebook.add(self.tab_customers, text="  顧客名簿  ")
        self.notebook.add(self.tab_templates, text="  文例管理  ")
        self.notebook.add(self.tab_settings, text="  設定（差出人・出力先）  ")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.tab_main.on_show()
        self.after(50, self._bring_to_front)

    def _bring_to_front(self) -> None:
        """他のウィンドウの後ろに隠れないよう、起動直後に最前面へ出す。"""
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except tk.TclError:
            pass

    def _setup_fonts(self) -> None:
        for name in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont"):
            try:
                f = tkfont.nametofont(name)
                f.configure(size=max(f.cget("size"), 10))
            except tk.TclError:
                pass
        style = ttk.Style(self)
        try:
            if "vista" in style.theme_names():
                style.theme_use("vista")
        except tk.TclError:
            pass

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _on_tab_changed(self, _event=None) -> None:
        tab = self.nametowidget(self.notebook.select())
        on_show = getattr(tab, "on_show", None)
        if on_show:
            on_show()

    def _on_close(self) -> None:
        try:
            self.repos.close()
        finally:
            self.destroy()

    def report_callback_exception(self, exc, val, tb) -> None:  # type: ignore[override]
        log.error("画面処理で予期しないエラー", exc_info=(exc, val, tb))
        try:
            messagebox.showerror(
                "エラー",
                f"予期しないエラーが発生しました。\n{val}\n\n詳細は logs/app.log を確認してください。",
                parent=self,
            )
        except tk.TclError:
            pass
