"""文例管理画面（文例の追加・編集・削除、文書の種類の管理）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from .. import placeholders
from ..models import DEFAULT_CLOSING, DEFAULT_OPENING, DocType, Template
from ..repositories import Repositories, RepositoryError
from .widgets import PAD, TextArea, add_entry_row


class DocTypeDialog(tk.Toplevel):
    """文書の種類を追加・名前変更・削除する小さなダイアログ。"""

    def __init__(self, master, repos: Repositories) -> None:
        super().__init__(master)
        self.repos = repos
        self.title("文書の種類の管理")
        self.resizable(False, False)
        self.transient(master)
        self._types: list[DocType] = []

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="登録されている種類").grid(row=0, column=0, sticky="w")
        self.lb = tk.Listbox(frame, height=8, width=30, exportselection=False)
        self.lb.grid(row=1, column=0, rowspan=4, sticky="nsew", padx=(0, 8))
        ttk.Button(frame, text="追加…", command=self._add, width=14).grid(row=1, column=1, sticky="we", pady=2)
        ttk.Button(frame, text="名前を変更…", command=self._rename, width=14).grid(row=2, column=1, sticky="we", pady=2)
        ttk.Button(frame, text="削除", command=self._delete, width=14).grid(row=3, column=1, sticky="we", pady=2)
        ttk.Button(frame, text="閉じる", command=self.destroy, width=14).grid(row=4, column=1, sticky="swe", pady=2)
        ttk.Label(
            frame, text="※ 文例で使われている種類は削除できません。", foreground="#555"
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._reload()
        self.grab_set()

    def _reload(self) -> None:
        self._types = self.repos.doc_types.list()
        self.lb.delete(0, "end")
        for d in self._types:
            self.lb.insert("end", d.name)

    def _selected(self) -> DocType | None:
        sel = self.lb.curselection()
        return self._types[sel[0]] if sel else None

    def _add(self) -> None:
        name = simpledialog.askstring("種類の追加", "新しい種類の名前：", parent=self)
        if name is None:
            return
        try:
            self.repos.doc_types.add(name)
        except RepositoryError as e:
            messagebox.showwarning("入力の確認", str(e), parent=self)
            return
        self._reload()

    def _rename(self) -> None:
        d = self._selected()
        if d is None:
            messagebox.showinfo("選択してください", "名前を変更する種類を一覧から選んでください。", parent=self)
            return
        name = simpledialog.askstring("名前の変更", "新しい名前：", initialvalue=d.name, parent=self)
        if name is None:
            return
        try:
            self.repos.doc_types.rename(d.id, name)
        except RepositoryError as e:
            messagebox.showwarning("入力の確認", str(e), parent=self)
            return
        self._reload()

    def _delete(self) -> None:
        d = self._selected()
        if d is None:
            messagebox.showinfo("選択してください", "削除する種類を一覧から選んでください。", parent=self)
            return
        if not messagebox.askyesno("削除の確認", f"「{d.name}」を削除しますか？", parent=self):
            return
        try:
            self.repos.doc_types.delete(d.id)
        except RepositoryError as e:
            messagebox.showwarning("削除できません", str(e), parent=self)
            return
        self._reload()


class TemplatesTab(ttk.Frame):
    def __init__(self, master, repos: Repositories, set_status: Callable[[str], None]) -> None:
        super().__init__(master, padding=8)
        self.repos = repos
        self.set_status = set_status
        self._current_id: int | None = None
        self._doc_types: list[DocType] = []
        self._build()
        self.refresh()

    # ---- 画面構築 ---------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # -- 一覧 ----------------------------------------------------------
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1)
        cols = ("type", "name")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse", height=20)
        self.tree.heading("type", text="種類")
        self.tree.heading("name", text="文例名")
        self.tree.column("type", width=100)
        self.tree.column("name", width=200)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        # -- 入力フォーム --------------------------------------------------
        right = ttk.LabelFrame(self, text="文例の内容", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.rowconfigure(4, weight=1)

        self.lbl_mode = ttk.Label(right, text="新規登録", foreground="#06c")
        self.lbl_mode.grid(row=0, column=0, columnspan=3, sticky="w", **PAD)

        self.var_name = tk.StringVar()
        add_entry_row(right, 1, "文例名", self.var_name)

        ttk.Label(right, text="文書の種類").grid(row=2, column=0, sticky="e", **PAD)
        f_type = ttk.Frame(right)
        f_type.grid(row=2, column=1, sticky="we", **PAD)
        self.cb_type = ttk.Combobox(f_type, state="readonly", width=24)
        self.cb_type.pack(side="left")
        ttk.Button(f_type, text="種類を管理…", command=self._manage_types).pack(side="left", padx=8)

        self.var_subject = tk.StringVar()
        add_entry_row(right, 3, "件名", self.var_subject)

        ttk.Label(right, text="本文").grid(row=4, column=0, sticky="ne", **PAD)
        self.txt_body = TextArea(right, height=12)
        self.txt_body.grid(row=4, column=1, sticky="nsew", **PAD)

        f_opts = ttk.Frame(right)
        f_opts.grid(row=5, column=1, sticky="we", **PAD)
        self.var_has_notes = tk.BooleanVar(value=False)
        ttk.Checkbutton(f_opts, text="記書きあり（初期値）", variable=self.var_has_notes).pack(side="left")
        ttk.Label(f_opts, text="　頭語").pack(side="left")
        self.var_opening = tk.StringVar(value=DEFAULT_OPENING)
        ttk.Entry(f_opts, textvariable=self.var_opening, width=8).pack(side="left", padx=4)
        ttk.Label(f_opts, text="結語").pack(side="left")
        self.var_closing = tk.StringVar(value=DEFAULT_CLOSING)
        ttk.Entry(f_opts, textvariable=self.var_closing, width=8).pack(side="left", padx=4)
        ttk.Label(f_opts, text="（不要なら空欄）", foreground="#555").pack(side="left")

        ttk.Label(right, text="書類一覧の\n初期値", justify="right").grid(row=6, column=0, sticky="ne", **PAD)
        self.txt_encl = TextArea(right, height=4)
        self.txt_encl.grid(row=6, column=1, sticky="we", **PAD)
        ttk.Label(
            right,
            text="1行に1件。「書類名,部数」のようにカンマで区切ると部数も入ります（例：決算報告書,1）。",
            foreground="#555",
        ).grid(row=7, column=1, sticky="w", padx=6)

        ttk.Label(right, text="差し込み記号", foreground="#555").grid(row=8, column=0, sticky="ne", **PAD)
        ttk.Label(right, text=placeholders.help_text(), foreground="#555", justify="left").grid(
            row=8, column=1, sticky="w", **PAD
        )

        f_btn = ttk.Frame(right)
        f_btn.grid(row=9, column=0, columnspan=2, sticky="we", pady=(10, 0))
        ttk.Button(f_btn, text="新規", command=self._new).pack(side="left", padx=4)
        ttk.Button(f_btn, text="複製", command=self._duplicate).pack(side="left", padx=4)
        ttk.Button(f_btn, text="保存", command=self._save).pack(side="left", padx=4)
        self.btn_delete = ttk.Button(f_btn, text="削除", command=self._delete)
        self.btn_delete.pack(side="left", padx=4)
        self._new()

    # ---- 一覧・種類 --------------------------------------------------------

    def refresh(self) -> None:
        self._reload_types()
        keep = self._current_id
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        type_names = {d.id: d.name for d in self._doc_types}
        for t in self.repos.templates.list():
            self.tree.insert("", "end", iid=str(t.id), values=(type_names.get(t.doc_type_id, ""), t.name))
        if keep is not None and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))

    def on_show(self) -> None:
        self.refresh()
        self.set_status("文例を選んで編集、または「新規」「複製」で追加できます。")

    def _reload_types(self) -> None:
        prev = self._selected_type_id()
        self._doc_types = self.repos.doc_types.list()
        self.cb_type["values"] = [d.name for d in self._doc_types]
        idx = next((i for i, d in enumerate(self._doc_types) if d.id == prev), -1)
        if idx >= 0:
            self.cb_type.current(idx)
        elif self._doc_types and prev is None:
            self.cb_type.current(0)
        else:
            self.cb_type.set("")

    def _selected_type_id(self) -> int | None:
        i = self.cb_type.current()
        return self._doc_types[i].id if 0 <= i < len(self._doc_types) else None

    def _set_type(self, doc_type_id: int | None) -> None:
        idx = next((i for i, d in enumerate(self._doc_types) if d.id == doc_type_id), -1)
        if idx >= 0:
            self.cb_type.current(idx)
        elif self._doc_types:
            self.cb_type.current(0)
        else:
            self.cb_type.set("")

    def _manage_types(self) -> None:
        dlg = DocTypeDialog(self, self.repos)
        self.wait_window(dlg)
        self.refresh()

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        t = self.repos.templates.get(int(sel[0]))
        if t is not None:
            self._load(t)

    # ---- フォーム ---------------------------------------------------------

    def _load(self, t: Template) -> None:
        self._current_id = t.id
        self.var_name.set(t.name)
        self._set_type(t.doc_type_id)
        self.var_subject.set(t.subject)
        self.txt_body.set(t.body)
        self.var_has_notes.set(t.has_notes)
        self.var_opening.set(t.opening)
        self.var_closing.set(t.closing)
        self.txt_encl.set(t.default_enclosures)
        self.lbl_mode.configure(text=f"編集中：{t.name}")
        self.btn_delete.configure(state="normal")

    def _new(self) -> None:
        self._current_id = None
        self.var_name.set("")
        self.var_subject.set("")
        self.txt_body.set("")
        self.var_has_notes.set(False)
        self.var_opening.set(DEFAULT_OPENING)
        self.var_closing.set(DEFAULT_CLOSING)
        self.txt_encl.set("")
        if self._doc_types and self.cb_type.current() < 0:
            self.cb_type.current(0)
        self.lbl_mode.configure(text="新規登録")
        self.btn_delete.configure(state="disabled")
        self.tree.selection_remove(*self.tree.selection())

    def _duplicate(self) -> None:
        if self._current_id is None:
            messagebox.showinfo("複製", "複製する文例を一覧から選んでください。", parent=self)
            return
        self._current_id = None
        self.var_name.set(f"{self.var_name.get()}（コピー）")
        self.lbl_mode.configure(text="新規登録（複製）")
        self.btn_delete.configure(state="disabled")
        self.tree.selection_remove(*self.tree.selection())
        self.set_status("複製しました。内容を修正して「保存」を押すと新しい文例として登録されます。")

    def _form_template(self) -> Template:
        return Template(
            id=self._current_id,
            name=self.var_name.get(),
            doc_type_id=self._selected_type_id(),
            subject=self.var_subject.get(),
            body=self.txt_body.get(),
            has_notes=self.var_has_notes.get(),
            opening=self.var_opening.get(),
            closing=self.var_closing.get(),
            default_enclosures=self.txt_encl.get(),
        )

    def _save(self) -> None:
        t = self._form_template()
        unknown = placeholders.unknown_tokens(t.subject + "\n" + t.body)
        if unknown and not messagebox.askyesno(
            "差し込み記号の確認",
            "次の差し込み記号は定義されていません。\n\n" + "、".join(unknown) + "\n\nこのまま保存しますか？",
            parent=self,
        ):
            return
        try:
            t = self.repos.templates.save(t)
        except RepositoryError as e:
            messagebox.showwarning("入力の確認", str(e), parent=self)
            return
        self._current_id = t.id
        self.refresh()
        self._load(t)
        self.set_status(f"保存しました：{t.name}")

    def _delete(self) -> None:
        if self._current_id is None:
            return
        name = self.var_name.get()
        if not messagebox.askyesno("削除の確認", f"文例「{name}」を削除しますか？", parent=self):
            return
        self.repos.templates.delete(self._current_id)
        self._new()
        self.refresh()
        self.set_status(f"削除しました：{name}")
