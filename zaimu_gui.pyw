"""財務エントリ 自動入力（ウィンドウ画面）。

「起動.bat」から起動する。関与先・CSV・月を選んでボタンを押すだけで入力できる。
入力の中身（キー操作の順番など）は zaimu_input.py と config.toml による。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import queue
import sys
import threading
import tomllib
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import tkinter as tk  # noqa: E402
from tkinter import messagebox, simpledialog, ttk  # noqa: E402

import zaimu_input as z  # noqa: E402

CLIENT_SETTING = "設定.toml"
RECORD_DIR = "記録"
CLIENT_LOG = "入力ログ.txt"
TAXES = ("課税", "免税")
BAD_NAME_CHARS = set('\\/:*?"<>|')


# ─────────────────────────────────────────────
# 関与先フォルダー
# ─────────────────────────────────────────────

def client_label(folder: Path) -> str:
    """「10614_望月昭光」→「10614 望月昭光」"""
    return folder.name.replace("_", " ", 1)


def read_client_tax(folder: Path) -> str:
    path = folder / CLIENT_SETTING
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        tax = tomllib.load(f).get("消費税", "")
    return tax if tax in TAXES else ""


def write_client_tax(folder: Path, tax: str):
    (folder / CLIENT_SETTING).write_text(
        "# この関与先だけの設定（自動入力の画面から書き換わります）\n"
        f'"消費税" = "{tax}"   # "課税" または "免税"\n',
        encoding="utf-8")


def progress_path(folder: Path, csv_path: Path, ym: tuple[int, int], practice: bool) -> Path:
    suffix = "_練習" if practice else ""
    return folder / RECORD_DIR / f"{csv_path.stem}_{ym[0]}-{ym[1]:02d}{suffix}.json"


def ym_label(ym: tuple[int, int]) -> str:
    return f"{ym[0]}年{ym[1]}月"


# ─────────────────────────────────────────────
# 画面
# ─────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.queue: queue.Queue = queue.Queue()
        self.ctl: z.Controller | None = None
        self.running = False
        self.clients: dict[str, Path] = {}
        self.months: dict[str, tuple[int, int]] = {}

        root.title("財務エントリ 自動入力")
        root.geometry("720x640")
        root.minsize(600, 520)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.cfg = self.load_cfg()
        clients = self.cfg.get("folders", {}).get("clients", "関与先")
        self.clients_dir = (BASE_DIR / clients).resolve()
        self.clients_dir.mkdir(parents=True, exist_ok=True)

        self.build()
        self.refresh_clients()
        self.check_libraries()
        self.root.after(100, self.poll_queue)

    # ── 画面の部品 ──

    def build(self):
        pad = {"padx": 6, "pady": 4}
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="both", expand=True)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="関与先").grid(row=0, column=0, sticky="w", **pad)
        self.client_var = tk.StringVar()
        self.client_box = ttk.Combobox(top, textvariable=self.client_var, state="readonly")
        self.client_box.grid(row=0, column=1, sticky="ew", **pad)
        self.client_box.bind("<<ComboboxSelected>>", lambda e: self.on_client())
        cbtn = ttk.Frame(top)
        cbtn.grid(row=0, column=2, sticky="w")
        self.add_btn = ttk.Button(cbtn, text="関与先を追加", command=self.add_client)
        self.add_btn.pack(side="left", padx=2)
        self.open_btn = ttk.Button(cbtn, text="フォルダーを開く", command=self.open_folder)
        self.open_btn.pack(side="left", padx=2)

        ttk.Label(top, text="消費税").grid(row=1, column=0, sticky="w", **pad)
        taxf = ttk.Frame(top)
        taxf.grid(row=1, column=1, columnspan=2, sticky="w", **pad)
        self.tax_var = tk.StringVar()
        self.tax_radios = []
        for tax, note in (("課税", "税区分の欄から入力"), ("免税", "借方科目の欄から入力")):
            r = ttk.Radiobutton(taxf, text=f"{tax}（{note}）", value=tax, variable=self.tax_var,
                                command=self.on_tax)
            r.pack(side="left", padx=(0, 12))
            self.tax_radios.append(r)
        self.tax_note = ttk.Label(taxf, foreground="#c00000")
        self.tax_note.pack(side="left")

        ttk.Label(top, text="CSV").grid(row=2, column=0, sticky="w", **pad)
        self.csv_var = tk.StringVar()
        self.csv_box = ttk.Combobox(top, textvariable=self.csv_var, state="readonly")
        self.csv_box.grid(row=2, column=1, sticky="ew", **pad)
        self.csv_box.bind("<<ComboboxSelected>>", lambda e: self.on_csv())
        self.reload_btn = ttk.Button(top, text="最新の状態にする", command=self.reload)
        self.reload_btn.grid(row=2, column=2, sticky="w", **pad)

        ttk.Label(top, text="月").grid(row=3, column=0, sticky="nw", **pad)
        self.month_tree = ttk.Treeview(top, columns=("month", "count", "state"), show="headings",
                                       height=6, selectmode="browse")
        for col, text, width in (("month", "月", 110), ("count", "件数", 60), ("state", "状態", 300)):
            self.month_tree.heading(col, text=text)
            self.month_tree.column(col, width=width, anchor="w" if col != "count" else "e")
        self.month_tree.grid(row=3, column=1, columnspan=2, sticky="nsew", **pad)

        btns = ttk.Frame(top)
        btns.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        self.check_btn = ttk.Button(btns, text="確認", command=self.on_check)
        self.practice_btn = ttk.Button(btns, text="メモ帳で練習", command=lambda: self.start(True))
        self.start_btn = ttk.Button(btns, text="入力開始", command=lambda: self.start(False))
        self.cancel_btn = ttk.Button(btns, text="中止", command=self.cancel, state="disabled")
        self.reset_btn = ttk.Button(btns, text="この月の記録を消す", command=self.reset_progress)
        for b in (self.check_btn, self.practice_btn, self.start_btn, self.cancel_btn):
            b.pack(side="left", padx=4)
        self.reset_btn.pack(side="right", padx=4)

        self.status_var = tk.StringVar(value="関与先・CSV・月を選んでください")
        ttk.Label(top, textvariable=self.status_var, font=("", 11, "bold")).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(top, text="入力中の操作：　PgDn ＝ 一時停止　／　PgUp ＝ 開始・再開").grid(
            row=6, column=0, columnspan=3, sticky="w", padx=6)

        logf = ttk.Frame(top)
        logf.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        top.rowconfigure(7, weight=1)
        self.log = tk.Text(logf, height=12, wrap="char", state="disabled")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.topmost_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="この画面を常に手前に表示", variable=self.topmost_var,
                        command=lambda: self.root.attributes("-topmost", self.topmost_var.get())).grid(
            row=8, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 0))
        self.root.attributes("-topmost", True)

        self.inputs = [self.client_box, self.csv_box, self.month_tree, self.add_btn, self.open_btn,
                       self.reload_btn, self.check_btn, self.practice_btn, self.start_btn,
                       self.reset_btn, *self.tax_radios]

    # ── 表示 ──

    def write(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def post(self, text: str):
        """入力中のスレッドから画面へ文字を送る。"""
        self.queue.put(("log", text))

    def poll_queue(self):
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == "log":
                    self.write(value)
                elif kind == "status":
                    self.status_var.set(value)
                elif kind == "done":
                    self.set_running(False)
                    self.on_csv(keep_selection=True)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def set_running(self, running: bool):
        self.running = running
        for w in self.inputs:
            if isinstance(w, ttk.Treeview):
                continue
            if isinstance(w, ttk.Combobox):
                w.configure(state="disabled" if running else "readonly")
            else:
                w.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    # ── 設定・ライブラリ ──

    def load_cfg(self) -> dict:
        return z.load_config(z.DEFAULT_CONFIG)

    def check_libraries(self):
        if sys.platform != "win32":
            self.write("※ Windows 以外のため、「確認」だけ使えます。")
            return
        missing = []
        for name in ("pywinauto", "keyboard", "pyperclip"):
            try:
                __import__(name)
            except Exception:
                missing.append(name)
        if missing:
            self.write(f"※ 必要なライブラリが入っていません（{', '.join(missing)}）。"
                       f"いったんこの画面を閉じ、「準備.bat」をダブルクリックしてください。")

    # ── 関与先・CSV・月 ──

    def refresh_clients(self, select: str | None = None):
        folders = sorted(p for p in self.clients_dir.iterdir() if p.is_dir())
        self.clients = {client_label(p): p for p in folders}
        self.client_box.configure(values=list(self.clients))
        if select and select in self.clients:
            self.client_var.set(select)
        elif self.client_var.get() not in self.clients:
            self.client_var.set("")
        if not self.clients:
            self.write(f"関与先がまだありません。「関与先を追加」を押してください。\n"
                       f"（関与先のフォルダーの場所: {self.clients_dir}）")
        self.on_client()

    def client_dir(self) -> Path | None:
        return self.clients.get(self.client_var.get())

    def on_client(self):
        folder = self.client_dir()
        self.tax_var.set(read_client_tax(folder) if folder else "")
        self.update_tax_note()
        csvs = sorted(p.name for p in folder.glob("*.csv")) if folder else []
        self.csv_box.configure(values=csvs)
        if self.csv_var.get() not in csvs:
            self.csv_var.set(csvs[0] if len(csvs) == 1 else "")
        if folder and not csvs:
            self.write(f"「{client_label(folder)}」のフォルダーに CSV がありません。"
                       f"「フォルダーを開く」で開き、通帳の CSV を入れてから「最新の状態にする」を押してください。")
        self.on_csv()

    def update_tax_note(self):
        missing = self.client_dir() and not self.tax_var.get()
        self.tax_note.configure(text="← 選んでください" if missing else "")

    def on_tax(self):
        folder = self.client_dir()
        if folder:
            write_client_tax(folder, self.tax_var.get())
            self.write(f"「{client_label(folder)}」の消費税を「{self.tax_var.get()}」にしました。")
        self.update_tax_note()

    def csv_path(self) -> Path | None:
        folder = self.client_dir()
        return folder / self.csv_var.get() if folder and self.csv_var.get() else None

    def on_csv(self, keep_selection: bool = False):
        selected = self.month_tree.selection()
        self.month_tree.delete(*self.month_tree.get_children())
        self.months = {}
        path = self.csv_path()
        if not path or not path.exists():
            return
        try:
            _, rows, errors = z.load_rows(path, self.load_cfg())
        except z.UserError as e:
            self.write(f"× {e}")
            return
        for e in errors:
            self.write(f"× {path.name} {e}")
        csv_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for ym, month_rows in z.group_by_month(rows).items():
            iid = f"{ym[0]}-{ym[1]:02d}"
            self.months[iid] = ym
            state = self.month_state(path, ym, month_rows, csv_hash)
            self.month_tree.insert("", "end", iid=iid, values=(ym_label(ym), len(month_rows), state))
        if keep_selection and selected and selected[0] in self.months:
            self.month_tree.selection_set(selected[0])
        elif len(self.months) == 1:
            self.month_tree.selection_set(next(iter(self.months)))

    def month_state(self, path: Path, ym, rows: list[z.Row], csv_hash: str) -> str:
        pp = progress_path(self.client_dir(), path, ym, practice=False)
        if not pp.exists():
            return "未入力"
        prog = z.Progress(pp, csv_hash, "")
        done = sum(1 for r in rows if r.line <= prog.last_completed)
        state = "入力済み" if done == len(rows) else ("未入力" if done == 0 else f"{done}件まで入力済み")
        if prog.in_progress:
            state += "（前回、途中で終了）"
        if prog.data.get("csv_sha256") != csv_hash:
            state += "（入力後に CSV が変更されています）"
        return state

    def selected_month(self) -> tuple[int, int] | None:
        sel = self.month_tree.selection()
        return self.months.get(sel[0]) if sel else None

    def reload(self):
        self.refresh_clients(select=self.client_var.get())

    def add_client(self):
        code = simpledialog.askstring("関与先を追加", "関与先コード（例: 10614）", parent=self.root)
        if not code:
            return
        name = simpledialog.askstring("関与先を追加", "関与先名（例: 望月昭光）", parent=self.root)
        if not name:
            return
        folder_name = f"{code.strip()}_{name.strip().replace(' ', '').replace('　', '')}"
        if BAD_NAME_CHARS & set(folder_name):
            messagebox.showerror("関与先を追加", f"次の文字は使えません: {' '.join(sorted(BAD_NAME_CHARS))}",
                                 parent=self.root)
            return
        folder = self.clients_dir / folder_name
        if folder.exists():
            messagebox.showinfo("関与先を追加", "その関与先はすでにあります。", parent=self.root)
        else:
            folder.mkdir()
            self.write(f"関与先「{client_label(folder)}」のフォルダーを作りました。")
        self.refresh_clients(select=client_label(folder))
        self.write("消費税の「課税」「免税」を選び、「フォルダーを開く」で通帳の CSV を入れてください。")

    def open_folder(self):
        folder = self.client_dir() or self.clients_dir
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            self.write(f"フォルダー: {folder}")

    # ── 確認・入力 ──

    def gather(self) -> dict | None:
        """選んだ関与先・CSV・月を確かめ、対象の仕訳とチェック結果を返す。"""
        folder, path, ym = self.client_dir(), self.csv_path(), self.selected_month()
        missing = [n for n, v in (("関与先", folder), ("CSV", path), ("月", ym)) if not v]
        if missing:
            messagebox.showwarning("自動入力", f"{'・'.join(missing)}を選んでください。", parent=self.root)
            return None
        tax = self.tax_var.get()
        if not tax:
            messagebox.showwarning("自動入力", "この関与先の消費税（課税／免税）を選んでください。", parent=self.root)
            return None
        try:
            cfg = self.load_cfg()
            header, rows, errors = z.load_rows(path, cfg, {"消費税": tax})
        except z.UserError as e:
            messagebox.showerror("自動入力", str(e), parent=self.root)
            return None
        rows = z.group_by_month(rows).get(ym, [])
        more_errors, warnings = z.validate(rows, header, cfg)
        return dict(cfg=cfg, folder=folder, path=path, ym=ym, tax=tax, rows=rows,
                    errors=errors + more_errors, warnings=warnings)

    def report(self, g: dict) -> bool:
        """チェック結果を表示する。誤りがなければ True。"""
        self.clear_log()
        self.write(f"関与先: {client_label(g['folder'])}（{g['tax']}）　CSV: {g['path'].name}　"
                   f"月: {ym_label(g['ym'])}　仕訳: {len(g['rows'])}件")
        for w in g["warnings"]:
            self.write(f"！ {w}")
        if g["errors"]:
            self.write("\n次の誤りがあるため、入力できません。CSV を直してから「最新の状態にする」を押してください。")
            for e in g["errors"]:
                self.write(f"× {e}")
            return False
        return True

    def on_check(self):
        g = self.gather()
        if not g or not self.report(g):
            return
        self.write("\n入力する仕訳:")
        for r in g["rows"]:
            self.write(f"  {z.row_summary(r)}")
        if g["rows"]:
            self.write("\n1件目の操作の順番:")
            for line in z.plan_lines(g["cfg"]["steps"], g["rows"][0].values):
                self.write(f"  {line}")
        self.write("\n問題ありません。（「確認」ではキーは送っていません）")
        self.status_var.set("確認しました")

    def start(self, practice: bool):
        if self.running:
            return
        if sys.platform != "win32":
            messagebox.showinfo("自動入力", "入力は Windows でのみ動きます。", parent=self.root)
            return
        g = self.gather()
        if not g or not self.report(g):
            if g:
                messagebox.showerror("自動入力", "CSV に誤りがあるため入力できません。下の欄を見てください。",
                                     parent=self.root)
            return
        path, ym = g["path"], g["ym"]
        csv_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        progress = z.Progress(progress_path(g["folder"], path, ym, practice), csv_hash, f"{ym[0]}-{ym[1]:02d}")
        rows = [r for r in g["rows"] if r.line > progress.last_completed]
        if not rows:
            messagebox.showinfo("自動入力", f"{ym_label(ym)}の仕訳はすべて入力済みです。\n"
                                "やり直すときは「この月の記録を消す」を押してください。", parent=self.root)
            return

        first = "税区分" if g["tax"] == "課税" else "借方科目"
        done = len(g["rows"]) - len(rows)
        lines = [f"関与先：{client_label(g['folder'])}（{g['tax']}）",
                 f"月：{ym_label(ym)}",
                 f"入力する仕訳：{len(rows)}件" + (f"（入力済みの{done}件は飛ばします）" if done else "")]
        if progress.in_progress:
            lines += ["", f"※ 前回は CSV {progress.in_progress}行目の入力途中で終了しています。",
                      "入力途中の行が残っていれば、先に手で消してください。"]
        if g["warnings"]:
            lines += ["", f"※ 注意が{len(g['warnings'])}件あります（下の欄を見てください）。"]
        if practice:
            lines += ["", "メモ帳を開いておいてください。", "",
                      "「はい」を押したら：", "1. メモ帳をクリック", "2. PgUp を押すと入力が始まります"]
        else:
            lines += ["", f"財務エントリで、この関与先の「会計伝票」（月次入力・{ym[1]}月分）を開いていますか？", "",
                      "「はい」を押したら：", "1. 財務エントリの画面をクリック",
                      f"2. カーソルを新しい行の「{first}」の欄に置く", "3. PgUp を押すと入力が始まります"]
        if not messagebox.askyesno("メモ帳で練習" if practice else "入力開始", "\n".join(lines), parent=self.root):
            return

        target = g["cfg"].get("target", {}).get("notepad" if practice else "zaimu")
        log_file = g["folder"] / RECORD_DIR / CLIENT_LOG
        self.write("")
        self.status_var.set(f"{'メモ帳' if practice else '財務エントリ'}をクリックしてから PgUp を押してください")
        self.set_running(True)
        threading.Thread(target=self.worker, daemon=True,
                         args=(g["cfg"], target, rows, progress, log_file, practice, g["path"])).start()

    def worker(self, cfg, target, rows, progress, log_file, practice, path):
        kind = "練習" if practice else "本番"
        try:
            win = z.Win()
            sender = z.Sender(cfg, win)
            self.ctl = z.Controller(cfg, target, win, notify=self.post,
                                    quit_hint="自動入力の画面の「中止」ボタン")
            self.ctl.install()
            try:
                z.write_log(f"開始（{kind}）  {path.name}  {progress.month_label}  CSV {rows[0].line}行目から", log_file)
                z.run_rows(rows, cfg, self.ctl, sender, progress, notify=self.post, log_file=log_file,
                           on_row_done=lambda n, t: self.queue.put(("status", f"入力中… {n}/{t}件 完了")))
            finally:
                self.ctl.uninstall()
            self.post(f"\n✔ すべて入力しました（{len(rows)}件）。")
            self.queue.put(("status", f"終了しました（{len(rows)}件）"))
            z.write_log(f"終了（{kind}）  {len(rows)}件", log_file)
        except z.Cancelled:
            msg = f"中止しました。CSV {progress.last_completed}行目まで入力済みです。"
            if progress.in_progress:
                msg += f"\n※ CSV {progress.in_progress}行目は入力途中です。財務エントリの画面で確認し、残っていれば消してください。"
            self.post("\n" + msg)
            self.queue.put(("status", "中止しました"))
            z.write_log(f"中止（{kind}）  {progress.last_completed}行目まで完了", log_file)
        except Exception:
            self.post("\nエラーで止まりました:\n" + traceback.format_exc())
            self.queue.put(("status", "エラーで止まりました"))
        finally:
            self.ctl = None
            self.queue.put(("done", None))

    def cancel(self):
        if self.ctl:
            self.ctl.cancel()
            self.status_var.set("中止しています…")

    def reset_progress(self):
        folder, path, ym = self.client_dir(), self.csv_path(), self.selected_month()
        if not (folder and path and ym):
            messagebox.showwarning("記録を消す", "関与先・CSV・月を選んでください。", parent=self.root)
            return
        pp = progress_path(folder, path, ym, practice=False)
        practice_pp = progress_path(folder, path, ym, practice=True)
        if not pp.exists() and not practice_pp.exists():
            messagebox.showinfo("記録を消す", "この月の記録はありません。", parent=self.root)
            return
        if not messagebox.askyesno("記録を消す",
                                   f"{client_label(folder)}の{ym_label(ym)}（{path.name}）の入力記録を消します。\n"
                                   "次に入力すると、この月の最初の仕訳から入力します。よろしいですか？",
                                   parent=self.root):
            return
        for p in (pp, practice_pp):
            p.unlink(missing_ok=True)
        z.write_log(f"記録を消去  {path.name}  {ym[0]}-{ym[1]:02d}", folder / RECORD_DIR / CLIENT_LOG)
        self.on_csv(keep_selection=True)
        self.write(f"{ym_label(ym)}の記録を消しました。")

    def on_close(self):
        if self.running:
            if not messagebox.askyesno("終了", "入力中です。中止して閉じますか？", parent=self.root):
                return
            if self.ctl:
                self.ctl.cancel()
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 高解像度の画面で文字がぼやけないように
        except Exception:
            pass
    root = tk.Tk()
    try:
        App(root)
    except Exception as e:
        messagebox.showerror("財務エントリ 自動入力", f"起動できませんでした。\n\n{e}")
        raise
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (BASE_DIR / "エラー.txt").write_text(f"{dt.datetime.now()}\n{traceback.format_exc()}", encoding="utf-8")
        raise
