"""顧客名簿画面（登録・編集・削除）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from ..models import HONORIFIC_CHOICES, Customer
from ..repositories import Repositories, RepositoryError
from .widgets import PAD, add_entry_row


class CustomersTab(ttk.Frame):
    def __init__(self, master, repos: Repositories, set_status: Callable[[str], None]) -> None:
        super().__init__(master, padding=8)
        self.repos = repos
        self.set_status = set_status
        self._current_id: int | None = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)

        # -- 一覧 ----------------------------------------------------------
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        f_search = ttk.Frame(left)
        f_search.grid(row=0, column=0, sticky="we", pady=(0, 4))
        ttk.Label(f_search, text="検索").pack(side="left", padx=4)
        self.var_search = tk.StringVar()
        e = ttk.Entry(f_search, textvariable=self.var_search)
        e.pack(side="left", fill="x", expand=True, padx=4)
        e.bind("<KeyRelease>", lambda _e: self.refresh())

        cols = ("company", "name", "address")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("company", text="会社名")
        self.tree.heading("name", text="氏名")
        self.tree.heading("address", text="住所")
        self.tree.column("company", width=200)
        self.tree.column("name", width=120)
        self.tree.column("address", width=260)
        self.tree.grid(row=1, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        # -- 入力フォーム --------------------------------------------------
        right = ttk.LabelFrame(self, text="顧客情報", padding=8)
        right.grid(row=0, column=1, sticky="ns")
        right.columnconfigure(1, weight=1)

        self.lbl_mode = ttk.Label(right, text="新規登録", foreground="#06c")
        self.lbl_mode.grid(row=0, column=0, columnspan=2, sticky="w", **PAD)

        self.vars = {k: tk.StringVar() for k in
                     ("company", "department", "name", "honorific", "postal", "address1", "address2")}
        add_entry_row(right, 1, "会社名", self.vars["company"])
        add_entry_row(right, 2, "部署名", self.vars["department"])
        add_entry_row(right, 3, "氏名", self.vars["name"])
        ttk.Label(right, text="敬称").grid(row=4, column=0, sticky="e", **PAD)
        self.cb_honorific = ttk.Combobox(
            right, textvariable=self.vars["honorific"], values=HONORIFIC_CHOICES, width=8
        )
        self.cb_honorific.grid(row=4, column=1, sticky="w", **PAD)
        add_entry_row(right, 5, "郵便番号", self.vars["postal"], width=14).grid(sticky="w")
        add_entry_row(right, 6, "住所1", self.vars["address1"])
        add_entry_row(right, 7, "住所2", self.vars["address2"])

        ttk.Label(
            right,
            text="※ 会社名のみ・氏名のみでも登録できます。\n"
                 "　 氏名がない場合は会社名に敬称が付きます（例：御中）。\n"
                 "　 空欄の項目は文書に出力されません。",
            foreground="#555", justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w", **PAD)

        f_btn = ttk.Frame(right)
        f_btn.grid(row=9, column=0, columnspan=2, sticky="we", pady=(12, 0))
        ttk.Button(f_btn, text="新規", command=self._new).pack(side="left", padx=4)
        ttk.Button(f_btn, text="保存", command=self._save).pack(side="left", padx=4)
        self.btn_delete = ttk.Button(f_btn, text="削除", command=self._delete)
        self.btn_delete.pack(side="left", padx=4)
        self._new()

    # ---- 一覧 -------------------------------------------------------------

    def refresh(self) -> None:
        keep = self._current_id
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for c in self.repos.customers.list(self.var_search.get()):
            addr = " ".join(s for s in (c.address1, c.address2) if s)
            self.tree.insert("", "end", iid=str(c.id), values=(c.company, c.name, addr))
        if keep is not None and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))
            self.tree.see(str(keep))

    def on_show(self) -> None:
        self.refresh()
        self.set_status("一覧から選ぶと右側で編集できます。「新規」で空のフォームになります。")

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        c = self.repos.customers.get(int(sel[0]))
        if c is None:
            return
        self._load(c)

    # ---- フォーム ---------------------------------------------------------

    def _load(self, c: Customer) -> None:
        self._current_id = c.id
        self.vars["company"].set(c.company)
        self.vars["department"].set(c.department)
        self.vars["name"].set(c.name)
        self.vars["honorific"].set(c.honorific)
        self.vars["postal"].set(c.postal)
        self.vars["address1"].set(c.address1)
        self.vars["address2"].set(c.address2)
        self.lbl_mode.configure(text=f"編集中：{c.display_name}")
        self.btn_delete.configure(state="normal")

    def _new(self) -> None:
        self._current_id = None
        for k, v in self.vars.items():
            v.set("様" if k == "honorific" else "")
        self.lbl_mode.configure(text="新規登録")
        self.btn_delete.configure(state="disabled")
        self.tree.selection_remove(*self.tree.selection())

    def _form_customer(self) -> Customer:
        return Customer(
            id=self._current_id,
            company=self.vars["company"].get(),
            department=self.vars["department"].get(),
            name=self.vars["name"].get(),
            honorific=self.vars["honorific"].get(),
            postal=self.vars["postal"].get(),
            address1=self.vars["address1"].get(),
            address2=self.vars["address2"].get(),
        )

    def _save(self) -> None:
        try:
            c = self.repos.customers.save(self._form_customer())
        except RepositoryError as e:
            messagebox.showwarning("入力の確認", str(e), parent=self)
            return
        self._current_id = c.id
        self.refresh()
        self._load(c)
        self.set_status(f"保存しました：{c.display_name}")

    def _delete(self) -> None:
        if self._current_id is None:
            return
        c = self.repos.customers.get(self._current_id)
        name = c.display_name if c else ""
        if not messagebox.askyesno("削除の確認", f"「{name}」を削除しますか？", parent=self):
            return
        self.repos.customers.delete(self._current_id)
        self._new()
        self.refresh()
        self.set_status(f"削除しました：{name}")
