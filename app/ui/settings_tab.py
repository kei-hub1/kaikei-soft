"""設定画面（差出人情報・出力先フォルダ）。"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .. import __version__, paths
from ..models import Sender
from ..repositories import Repositories
from .widgets import PAD, add_entry_row, open_folder


class SettingsTab(ttk.Frame):
    def __init__(self, master, repos: Repositories, set_status: Callable[[str], None]) -> None:
        super().__init__(master, padding=8)
        self.repos = repos
        self.set_status = set_status
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        # -- 差出人 --------------------------------------------------------
        f_sender = ttk.LabelFrame(self, text="差出人（事務所情報）　※ 一度登録すれば以降の文書に自動で入ります", padding=8)
        f_sender.grid(row=0, column=0, sticky="we", pady=(0, 10))
        f_sender.columnconfigure(1, weight=1)
        self.vars = {k: tk.StringVar() for k in
                     ("office", "accountant", "postal", "address", "tel", "fax", "email", "staff")}
        add_entry_row(f_sender, 0, "事務所名", self.vars["office"], width=50)
        add_entry_row(f_sender, 1, "税理士名", self.vars["accountant"], width=50)
        add_entry_row(f_sender, 2, "郵便番号", self.vars["postal"], width=14).grid(sticky="w")
        add_entry_row(f_sender, 3, "住所", self.vars["address"], width=50)
        add_entry_row(f_sender, 4, "電話番号", self.vars["tel"], width=24).grid(sticky="w")
        add_entry_row(f_sender, 5, "FAX番号", self.vars["fax"], width=24).grid(sticky="w")
        add_entry_row(f_sender, 6, "メールアドレス", self.vars["email"], width=40).grid(sticky="w")
        add_entry_row(f_sender, 7, "担当者名", self.vars["staff"], width=24).grid(sticky="w")
        ttk.Label(
            f_sender,
            text="※ 空欄の項目は文書に出力されません。税理士名は「税理士　○○」と表示されます。",
            foreground="#555",
        ).grid(row=8, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Button(f_sender, text="差出人を保存", command=self._save_sender).grid(
            row=9, column=0, columnspan=2, sticky="w", padx=6, pady=(8, 0)
        )

        # -- 出力先 --------------------------------------------------------
        f_out = ttk.LabelFrame(self, text="出力先フォルダ", padding=8)
        f_out.grid(row=1, column=0, sticky="we", pady=(0, 10))
        f_out.columnconfigure(1, weight=1)
        self.var_output = tk.StringVar()
        ttk.Label(f_out, text="フォルダ").grid(row=0, column=0, sticky="e", **PAD)
        ttk.Entry(f_out, textvariable=self.var_output).grid(row=0, column=1, sticky="we", **PAD)
        ttk.Button(f_out, text="参照…", command=self._browse).grid(row=0, column=2, **PAD)
        f_btn = ttk.Frame(f_out)
        f_btn.grid(row=1, column=1, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(f_btn, text="出力先を保存", command=self._save_output).pack(side="left", padx=4)
        ttk.Button(f_btn, text="初期値に戻す", command=self._reset_output).pack(side="left", padx=4)
        ttk.Button(f_btn, text="フォルダを開く", command=lambda: open_folder(Path(self.var_output.get()))).pack(
            side="left", padx=4
        )
        ttk.Label(
            f_out, text=f"初期値：{paths.DEFAULT_OUTPUT_DIR}", foreground="#555"
        ).grid(row=2, column=1, columnspan=2, sticky="w", **PAD)

        # -- 情報 ----------------------------------------------------------
        f_info = ttk.LabelFrame(self, text="情報", padding=8)
        f_info.grid(row=2, column=0, sticky="we")
        ttk.Label(
            f_info,
            text=f"バージョン：{__version__}\nデータ：{paths.DB_PATH}\nログ：{paths.LOG_PATH}",
            justify="left", foreground="#555",
        ).pack(anchor="w")

    def refresh(self) -> None:
        s = self.repos.sender.get()
        for k, v in self.vars.items():
            v.set(getattr(s, k))
        self.var_output.set(str(self.repos.settings.output_dir()))

    def on_show(self) -> None:
        self.refresh()
        self.set_status("差出人と出力先を設定して、それぞれ「保存」を押してください。")

    def _save_sender(self) -> None:
        s = Sender(**{k: v.get() for k, v in self.vars.items()})
        self.repos.sender.save(s)
        self.set_status("差出人を保存しました。")
        messagebox.showinfo("保存しました", "差出人情報を保存しました。", parent=self)

    def _browse(self) -> None:
        d = filedialog.askdirectory(parent=self, initialdir=self.var_output.get() or str(paths.APP_DIR))
        if d:
            self.var_output.set(str(Path(d)))

    def _save_output(self) -> None:
        value = self.var_output.get().strip()
        if not value:
            messagebox.showwarning("入力の確認", "出力先フォルダを入力してください。", parent=self)
            return
        p = Path(value)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("保存できません", f"フォルダを作成できませんでした。\n{p}\n{e}", parent=self)
            return
        self.repos.settings.set_output_dir(p)
        self.var_output.set(str(p))
        self.set_status(f"出力先を保存しました：{p}")
        messagebox.showinfo("保存しました", f"出力先フォルダ：\n{p}", parent=self)

    def _reset_output(self) -> None:
        self.var_output.set(str(paths.DEFAULT_OUTPUT_DIR))
