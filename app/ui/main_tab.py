"""メイン画面（文書作成）。"""

from __future__ import annotations

import datetime as dt
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .. import placeholders, service
from ..logger import get_logger
from ..models import (
    DEFAULT_CLOSING,
    DEFAULT_OPENING,
    Customer,
    DocumentRequest,
    Enclosure,
    Template,
)
from ..repositories import Repositories
from ..wareki import parse_date, to_wareki
from .widgets import PAD, ScrollableFrame, TextArea, open_folder

log = get_logger("ui.main")


class EnclosureRows(ttk.Frame):
    """記書きの書類一覧（行の追加・削除ができる入力欄）。"""

    MIN_ROWS = 3

    def __init__(self, master) -> None:
        super().__init__(master)
        self._rows: list[tuple[ttk.Frame, tk.StringVar, tk.StringVar]] = []
        self._enabled = True
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="No.", width=4).pack(side="left", padx=(2, 0))
        ttk.Label(header, text="書類名").pack(side="left", padx=4, fill="x", expand=True)
        ttk.Label(header, text="部数", width=6).pack(side="left", padx=4)
        ttk.Label(header, text="", width=4).pack(side="left")
        self._body = ttk.Frame(self)
        self._body.pack(fill="both", expand=True)
        self.set_items([])

    # -- 公開メソッド --------------------------------------------------------

    def add_row(self, title: str = "", qty: str = "") -> None:
        frame = ttk.Frame(self._body)
        frame.pack(fill="x", pady=1)
        title_var = tk.StringVar(value=title)
        qty_var = tk.StringVar(value=qty)
        num = ttk.Label(frame, text="", width=4)
        num.pack(side="left", padx=(2, 0))
        e1 = ttk.Entry(frame, textvariable=title_var)
        e1.pack(side="left", padx=4, fill="x", expand=True)
        e2 = ttk.Entry(frame, textvariable=qty_var, width=6, justify="right")
        e2.pack(side="left", padx=4)
        btn = ttk.Button(frame, text="✕", width=3, command=lambda: self._remove(frame))
        btn.pack(side="left")
        self._rows.append((frame, title_var, qty_var))
        self._renumber()
        self._apply_state()

    def items(self) -> list[Enclosure]:
        return [Enclosure(title=t.get(), quantity=q.get()) for _f, t, q in self._rows]

    def set_items(self, items: list[Enclosure]) -> None:
        for frame, _t, _q in self._rows:
            frame.destroy()
        self._rows.clear()
        for item in items:
            self.add_row(item.title, item.quantity)
        while len(self._rows) < self.MIN_ROWS:
            self.add_row()

    def is_all_blank(self) -> bool:
        return all(e.is_blank for e in self.items())

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._apply_state()

    # -- 内部 ---------------------------------------------------------------

    def _remove(self, frame: ttk.Frame) -> None:
        self._rows = [r for r in self._rows if r[0] is not frame]
        frame.destroy()
        while len(self._rows) < 1:
            self.add_row()
        self._renumber()

    def _renumber(self) -> None:
        for i, (frame, _t, _q) in enumerate(self._rows, start=1):
            frame.winfo_children()[0].configure(text=f"{i}.")

    def _apply_state(self) -> None:
        state = "normal" if self._enabled else "disabled"
        for frame, _t, _q in self._rows:
            for child in frame.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Button)):
                    child.configure(state=state)


class MainTab(ttk.Frame):
    def __init__(self, master, repos: Repositories, set_status: Callable[[str], None]) -> None:
        super().__init__(master, padding=8)
        self.repos = repos
        self.set_status = set_status

        self._doc_types = []
        self._templates: list[Template] = []
        self._customers: list[Customer] = []
        self._current_template: Template | None = None
        self._selected_customer_id: int | None = None

        self._build()
        self.refresh()

    # ---- 画面構築 ---------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        # -- 文例 ----------------------------------------------------------
        f_tpl = ttk.LabelFrame(left, text="文例", padding=6)
        f_tpl.pack(fill="x", pady=(0, 6))
        f_tpl.columnconfigure(1, weight=1)
        ttk.Label(f_tpl, text="文書の種類").grid(row=0, column=0, sticky="e", **PAD)
        self.cb_type = ttk.Combobox(f_tpl, state="readonly", width=28)
        self.cb_type.grid(row=0, column=1, sticky="we", **PAD)
        self.cb_type.bind("<<ComboboxSelected>>", lambda _e: self._on_type_selected())
        ttk.Label(f_tpl, text="文例").grid(row=1, column=0, sticky="e", **PAD)
        self.cb_template = ttk.Combobox(f_tpl, state="readonly", width=28)
        self.cb_template.grid(row=1, column=1, sticky="we", **PAD)
        self.cb_template.bind("<<ComboboxSelected>>", lambda _e: self._on_template_selected())

        # -- 宛先 ----------------------------------------------------------
        f_cust = ttk.LabelFrame(left, text="宛先（顧客名簿から選択）", padding=6)
        f_cust.pack(fill="x", pady=(0, 6))
        f_cust.columnconfigure(1, weight=1)
        ttk.Label(f_cust, text="検索").grid(row=0, column=0, sticky="e", **PAD)
        self.var_search = tk.StringVar()
        e = ttk.Entry(f_cust, textvariable=self.var_search)
        e.grid(row=0, column=1, sticky="we", **PAD)
        e.bind("<KeyRelease>", lambda _e: self._reload_customers())
        self.lb_customers = tk.Listbox(f_cust, height=6, exportselection=False, activestyle="none")
        self.lb_customers.grid(row=1, column=0, columnspan=2, sticky="we", **PAD)
        self.lb_customers.bind("<<ListboxSelect>>", lambda _e: self._on_customer_selected())
        self.lbl_customer = ttk.Label(f_cust, text="（未選択）", justify="left", foreground="#444")
        self.lbl_customer.grid(row=2, column=0, columnspan=2, sticky="w", **PAD)

        # -- 作成日 --------------------------------------------------------
        f_date = ttk.LabelFrame(left, text="作成日", padding=6)
        f_date.pack(fill="x", pady=(0, 6))
        self.var_date = tk.StringVar(value=dt.date.today().strftime("%Y/%m/%d"))
        e = ttk.Entry(f_date, textvariable=self.var_date, width=14)
        e.pack(side="left", padx=4)
        e.bind("<KeyRelease>", lambda _e: self._update_date_preview())
        ttk.Button(f_date, text="今日", width=5, command=self._set_today).pack(side="left", padx=2)
        self.lbl_date = ttk.Label(f_date, text="")
        self.lbl_date.pack(side="left", padx=8)
        self._update_date_preview()

        # -- 記書き --------------------------------------------------------
        f_notes = ttk.LabelFrame(left, text="記書き", padding=6)
        f_notes.pack(fill="both", expand=True)
        self.var_has_notes = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f_notes, text="記書きあり（「記」と書類一覧を付ける）",
            variable=self.var_has_notes, command=self._on_notes_toggled,
        ).pack(anchor="w")
        scroll = ScrollableFrame(f_notes, height=170)
        scroll.pack(fill="both", expand=True, pady=4)
        self.enclosures = EnclosureRows(scroll.inner)
        self.enclosures.pack(fill="both", expand=True)
        self.btn_add_row = ttk.Button(f_notes, text="行を追加", command=self.enclosures.add_row)
        self.btn_add_row.pack(anchor="w")
        self._on_notes_toggled()

        # -- 件名・本文 ----------------------------------------------------
        f_subj = ttk.Frame(right)
        f_subj.grid(row=0, column=0, sticky="we", pady=(0, 6))
        f_subj.columnconfigure(1, weight=1)
        ttk.Label(f_subj, text="件名").grid(row=0, column=0, sticky="e", **PAD)
        self.var_subject = tk.StringVar()
        ttk.Entry(f_subj, textvariable=self.var_subject).grid(row=0, column=1, sticky="we", **PAD)

        ttk.Label(right, text="本文（「拝啓」「敬具」は自動で付きます。1行が1段落になります）").grid(
            row=1, column=0, sticky="w", padx=6
        )
        self.txt_body = TextArea(right, height=16)
        self.txt_body.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 4))

        ttk.Label(
            right,
            text="件名・本文には {宛名} {作成日} などの差し込み記号が使えます（一覧は「文例管理」タブ）。",
            foreground="#555",
        ).grid(row=3, column=0, sticky="w", padx=6)

        f_btn = ttk.Frame(right)
        f_btn.grid(row=4, column=0, sticky="we", pady=(10, 0))
        self.btn_create = ttk.Button(f_btn, text="作成（Word と PDF を出力）", command=self._create)
        self.btn_create.pack(side="left", padx=6, ipadx=12, ipady=4)
        ttk.Button(f_btn, text="出力フォルダを開く", command=self._open_output).pack(side="left", padx=6)

    # ---- データ読み込み ---------------------------------------------------

    def refresh(self) -> None:
        """他のタブで変更された内容を反映する（選択状態はできるだけ維持）。"""
        prev_type = self._selected_type_id()
        self._doc_types = self.repos.doc_types.list()
        self.cb_type["values"] = [d.name for d in self._doc_types]
        if self._doc_types:
            idx = next((i for i, d in enumerate(self._doc_types) if d.id == prev_type), 0)
            self.cb_type.current(idx)
        else:
            self.cb_type.set("")
        self._reload_templates(keep=self._current_template.id if self._current_template else None)
        self._reload_customers()

    def on_show(self) -> None:
        self.refresh()
        self.set_status("宛先と文例を選び、必要に応じて修正してから「作成」を押してください。")

    def _selected_type_id(self) -> int | None:
        i = self.cb_type.current()
        return self._doc_types[i].id if 0 <= i < len(self._doc_types) else None

    def _reload_templates(self, keep: int | None = None) -> None:
        type_id = self._selected_type_id()
        self._templates = self.repos.templates.list(type_id) if type_id else self.repos.templates.list()
        self.cb_template["values"] = [t.name for t in self._templates]
        idx = next((i for i, t in enumerate(self._templates) if t.id == keep), -1)
        if idx >= 0:
            self.cb_template.current(idx)
            self._current_template = self._templates[idx]
        else:
            self.cb_template.set("")
            self._current_template = None

    def _reload_customers(self) -> None:
        keep = self._selected_customer_id
        self._customers = self.repos.customers.list(self.var_search.get())
        self.lb_customers.delete(0, "end")
        for c in self._customers:
            label = "　".join(s for s in (c.company, c.name) if s)
            self.lb_customers.insert("end", label)
        idx = next((i for i, c in enumerate(self._customers) if c.id == keep), -1)
        if idx >= 0:
            self.lb_customers.selection_set(idx)
            self.lb_customers.see(idx)
        else:
            self._selected_customer_id = None
        self._update_customer_preview()

    # ---- イベント ---------------------------------------------------------

    def _on_type_selected(self) -> None:
        self._reload_templates()

    def _on_template_selected(self) -> None:
        i = self.cb_template.current()
        if not (0 <= i < len(self._templates)):
            return
        t = self._templates[i]
        self._current_template = t
        self.var_subject.set(t.subject)
        self.txt_body.set(t.body)
        self.var_has_notes.set(t.has_notes)
        defaults = t.enclosures()
        if defaults or self.enclosures.is_all_blank():
            self.enclosures.set_items(defaults)
        self._on_notes_toggled()
        self.set_status(f"文例「{t.name}」を反映しました。件名・本文はこの画面で修正できます。")

    def _on_customer_selected(self) -> None:
        sel = self.lb_customers.curselection()
        if sel and 0 <= sel[0] < len(self._customers):
            self._selected_customer_id = self._customers[sel[0]].id
        self._update_customer_preview()

    def _update_customer_preview(self) -> None:
        c = self._selected_customer()
        if c is None:
            self.lbl_customer.configure(text="（未選択）")
        else:
            self.lbl_customer.configure(text="\n".join(c.address_lines()) or c.display_name)

    def _selected_customer(self) -> Customer | None:
        if self._selected_customer_id is None:
            return None
        return self.repos.customers.get(self._selected_customer_id)

    def _set_today(self) -> None:
        self.var_date.set(dt.date.today().strftime("%Y/%m/%d"))
        self._update_date_preview()

    def _update_date_preview(self) -> None:
        d = parse_date(self.var_date.get())
        if d is None:
            self.lbl_date.configure(text="日付の形式が正しくありません（例：2026/09/17）", foreground="#b00")
        else:
            self.lbl_date.configure(text=to_wareki(d), foreground="#000")

    def _on_notes_toggled(self) -> None:
        enabled = self.var_has_notes.get()
        self.enclosures.set_enabled(enabled)
        self.btn_add_row.configure(state="normal" if enabled else "disabled")

    def _open_output(self) -> None:
        open_folder(self.repos.settings.output_dir())

    # ---- 作成 -------------------------------------------------------------

    def _build_request(self) -> DocumentRequest | None:
        customer = self._selected_customer()
        if customer is None:
            messagebox.showwarning("入力の確認", "宛先を選択してください。", parent=self)
            return None
        created_on = parse_date(self.var_date.get())
        if created_on is None:
            messagebox.showwarning("入力の確認", "作成日の形式が正しくありません。\n例：2026/09/17", parent=self)
            return None
        t = self._current_template
        return DocumentRequest(
            customer=customer,
            sender=self.repos.sender.get(),
            created_on=created_on,
            subject=self.var_subject.get(),
            body=self.txt_body.get(),
            has_notes=self.var_has_notes.get(),
            enclosures=self.enclosures.items(),
            opening=t.opening if t is not None else DEFAULT_OPENING,
            closing=t.closing if t is not None else DEFAULT_CLOSING,
        )

    def _create(self) -> None:
        req = self._build_request()
        if req is None:
            return
        try:
            service.validate(req)
        except service.ValidationError as e:
            messagebox.showwarning("入力の確認", str(e), parent=self)
            return

        unknown = placeholders.unknown_tokens(req.subject + "\n" + req.body)
        if unknown:
            ok = messagebox.askyesno(
                "差し込み記号の確認",
                "次の差し込み記号は定義されていないため、そのまま出力されます。\n\n"
                + "、".join(unknown)
                + "\n\nこのまま作成しますか？",
                parent=self,
            )
            if not ok:
                return

        output_dir = self.repos.settings.output_dir()
        self.set_status("作成中です。しばらくお待ちください…")
        self.btn_create.configure(state="disabled")
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            result = service.create_document(req, output_dir)
        except service.FileLockedError as e:
            messagebox.showerror("保存できません", str(e), parent=self)
            self.set_status("保存できませんでした。")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("文書作成に失敗")
            messagebox.showerror(
                "エラー",
                f"文書の作成中にエラーが発生しました。\n{e}\n\n詳細は logs/app.log を確認してください。",
                parent=self,
            )
            self.set_status("文書の作成に失敗しました。")
            return
        finally:
            self.btn_create.configure(state="normal")
            self.configure(cursor="")

        if result.pdf_ok:
            messagebox.showinfo(
                "作成しました",
                f"次のファイルを出力しました。\n\n{result.docx_path.name}\n{result.pdf_path.name}\n\n"
                f"出力先：{output_dir}",
                parent=self,
            )
            self.set_status(f"作成しました：{result.docx_path.name} / {result.pdf_path.name}")
        else:
            messagebox.showwarning(
                "PDF 変換に失敗しました",
                f"Word ファイルは作成しましたが、PDF への変換に失敗しました。\n\n"
                f"作成した Word：{result.docx_path.name}\n\n理由：\n{result.pdf_error}\n\n"
                "Word で開いて「名前を付けて保存」から PDF を作成することもできます。",
                parent=self,
            )
            self.set_status(f"Word のみ作成しました（PDF 変換に失敗）：{result.docx_path.name}")
        open_folder(output_dir)
