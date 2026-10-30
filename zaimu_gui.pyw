"""財務エントリ 自動入力（ウィンドウ画面）。

「起動.bat」から起動する。CSV を選び、月を選んでボタンを押すだけで入力できる。
入力の中身（キー操作の順番など）は zaimu_input.py と config.toml による。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import queue
import sys
import threading
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

import zaimu_input as z  # noqa: E402

RECORD_DIR = BASE_DIR / "記録"          # どこまで入力したか・入力ログ（ツール側でまとめて持つ）
LOG_FILE = RECORD_DIR / "入力ログ.txt"
LAST_DIR_FILE = RECORD_DIR / "前回のフォルダー.json"


def progress_path(csv_path: Path, ym: tuple[int, int], practice: bool) -> Path:
    """CSV の場所と月ごとの記録ファイル。同じ名前の CSV が別のフォルダーにあっても混ざらない。"""
    key = hashlib.sha1(str(csv_path.resolve()).encode("utf-8")).hexdigest()[:8]
    suffix = "_練習" if practice else ""
    return RECORD_DIR / f"{csv_path.stem}_{key}_{ym[0]}-{ym[1]:02d}{suffix}.json"


def ym_label(ym: tuple[int, int]) -> str:
    return f"{ym[0]}年{ym[1]}月"


def load_last_dir() -> str | None:
    try:
        return json.loads(LAST_DIR_FILE.read_text(encoding="utf-8")).get("dir")
    except Exception:
        return None


def save_last_dir(folder: Path):
    RECORD_DIR.mkdir(exist_ok=True)
    LAST_DIR_FILE.write_text(json.dumps({"dir": str(folder)}, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────
# 画面
# ─────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk, csv_arg: str | None = None):
        self.root = root
        self.queue: queue.Queue = queue.Queue()
        self.ctl: z.Controller | None = None
        self.running = False
        self.csv: Path | None = None
        self.months: dict[str, tuple[int, int]] = {}

        root.title("財務エントリ 自動入力")
        root.geometry("720x600")
        root.minsize(600, 480)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.load_cfg()  # 設定ファイルの誤りは起動時に知らせる
        self.build()
        self.check_libraries()
        if csv_arg:
            self.set_csv(Path(csv_arg))
        self.root.after(100, self.poll_queue)

    # ── 画面の部品 ──

    def build(self):
        pad = {"padx": 6, "pady": 4}
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="both", expand=True)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="CSV").grid(row=0, column=0, sticky="w", **pad)
        self.csv_var = tk.StringVar(value="（まだ選んでいません）")
        ttk.Label(top, textvariable=self.csv_var, relief="sunken", padding=(4, 2)).grid(
            row=0, column=1, sticky="ew", **pad)
        self.pick_btn = ttk.Button(top, text="CSV を選ぶ", command=self.pick_csv)
        self.pick_btn.grid(row=0, column=2, sticky="w", **pad)

        ttk.Label(top, text="消費税").grid(row=1, column=0, sticky="w", **pad)
        taxf = ttk.Frame(top)
        taxf.grid(row=1, column=1, columnspan=2, sticky="w", **pad)
        self.tax_var = tk.StringVar()
        self.tax_radios = []
        for tax, note in (("課税", "税区分の欄から入力"), ("免税", "借方科目の欄から入力")):
            r = ttk.Radiobutton(taxf, text=f"{tax}（{note}）", value=tax, variable=self.tax_var)
            r.pack(side="left", padx=(0, 12))
            self.tax_radios.append(r)

        ttk.Label(top, text="月").grid(row=2, column=0, sticky="nw", **pad)
        self.month_tree = ttk.Treeview(top, columns=("month", "count", "state"), show="headings",
                                       height=6, selectmode="browse")
        for col, text, width in (("month", "月", 110), ("count", "件数", 60), ("state", "状態", 300)):
            self.month_tree.heading(col, text=text)
            self.month_tree.column(col, width=width, anchor="e" if col == "count" else "w")
        self.month_tree.grid(row=2, column=1, columnspan=2, sticky="nsew", **pad)

        btns = ttk.Frame(top)
        btns.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        self.check_btn = ttk.Button(btns, text="確認", command=self.on_check)
        self.practice_btn = ttk.Button(btns, text="メモ帳で練習", command=lambda: self.start(True))
        self.start_btn = ttk.Button(btns, text="入力開始", command=lambda: self.start(False))
        self.cancel_btn = ttk.Button(btns, text="中止", command=self.cancel, state="disabled")
        self.reset_btn = ttk.Button(btns, text="この月の記録を消す", command=self.reset_progress)
        for b in (self.check_btn, self.practice_btn, self.start_btn, self.cancel_btn):
            b.pack(side="left", padx=4)
        self.reset_btn.pack(side="right", padx=4)

        self.status_var = tk.StringVar(value="「CSV を選ぶ」を押してください")
        ttk.Label(top, textvariable=self.status_var, font=("", 11, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(top, text="入力中の操作：　PgDn ＝ 一時停止　／　PgUp ＝ 開始・再開").grid(
            row=5, column=0, columnspan=3, sticky="w", padx=6)

        logf = ttk.Frame(top)
        logf.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        top.rowconfigure(6, weight=1)
        self.log = tk.Text(logf, height=12, wrap="char", state="disabled")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.topmost_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="この画面を常に手前に表示", variable=self.topmost_var,
                        command=lambda: self.root.attributes("-topmost", self.topmost_var.get())).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 0))
        self.root.attributes("-topmost", True)

        self.inputs = [self.pick_btn, self.check_btn, self.practice_btn, self.start_btn,
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
                    self.refresh_months()
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def set_running(self, running: bool):
        self.running = running
        for w in self.inputs:
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

    # ── CSV・月 ──

    def pick_csv(self):
        initial = str(self.csv.parent) if self.csv else load_last_dir()
        name = filedialog.askopenfilename(parent=self.root, title="通帳の CSV を選ぶ", initialdir=initial,
                                          filetypes=[("CSV ファイル", "*.csv"), ("すべてのファイル", "*.*")])
        if name:
            self.set_csv(Path(name))

    def set_csv(self, path: Path):
        if not path.exists():
            self.write(f"× CSV が見つかりません: {path}")
            return
        self.csv = path
        self.csv_var.set(str(path))
        save_last_dir(path.parent)
        self.clear_log()
        self.refresh_months()
        if self.months:
            self.status_var.set("消費税の「課税／免税」と、入力する月を選んでください")

    def refresh_months(self):
        selected = self.month_tree.selection()
        self.month_tree.delete(*self.month_tree.get_children())
        self.months = {}
        if not self.csv:
            return
        try:
            _, rows, errors = z.load_rows(self.csv, self.load_cfg())
        except (z.UserError, UnicodeDecodeError) as e:
            self.write(f"× {e}")
            return
        for e in errors:
            self.write(f"× {e}")
        csv_hash = hashlib.sha256(self.csv.read_bytes()).hexdigest()
        for ym, month_rows in z.group_by_month(rows).items():
            iid = f"{ym[0]}-{ym[1]:02d}"
            self.months[iid] = ym
            state = self.month_state(ym, month_rows, csv_hash)
            self.month_tree.insert("", "end", iid=iid, values=(ym_label(ym), len(month_rows), state))
        if selected and selected[0] in self.months:
            self.month_tree.selection_set(selected[0])
        elif len(self.months) == 1:
            self.month_tree.selection_set(next(iter(self.months)))

    def month_state(self, ym, rows: list[z.Row], csv_hash: str) -> str:
        pp = progress_path(self.csv, ym, practice=False)
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

    # ── 確認・入力 ──

    def gather(self) -> dict | None:
        """選んだ CSV・月・消費税を確かめ、対象の仕訳とチェック結果を返す。"""
        if not self.csv:
            messagebox.showwarning("自動入力", "「CSV を選ぶ」で CSV を選んでください。", parent=self.root)
            return None
        ym = self.selected_month()
        if not ym:
            messagebox.showwarning("自動入力", "入力する月を選んでください。", parent=self.root)
            return None
        tax = self.tax_var.get()
        if not tax:
            messagebox.showwarning("自動入力", "消費税の「課税」か「免税」を選んでください。", parent=self.root)
            return None
        try:
            cfg = self.load_cfg()
            header, rows, errors = z.load_rows(self.csv, cfg, {"消費税": tax})
        except (z.UserError, UnicodeDecodeError) as e:
            messagebox.showerror("自動入力", str(e), parent=self.root)
            return None
        rows = z.group_by_month(rows).get(ym, [])
        more_errors, warnings = z.validate(rows, header, cfg)
        return dict(cfg=cfg, path=self.csv, ym=ym, tax=tax, rows=rows,
                    errors=errors + more_errors, warnings=warnings)

    def report(self, g: dict) -> bool:
        """チェック結果を表示する。誤りがなければ True。"""
        self.clear_log()
        self.write(f"CSV: {g['path'].name}　消費税: {g['tax']}　月: {ym_label(g['ym'])}　仕訳: {len(g['rows'])}件")
        for w in g["warnings"]:
            self.write(f"！ {w}")
        if g["errors"]:
            self.write("\n次の誤りがあるため、入力できません。CSV を直してから、もう一度「CSV を選ぶ」で選んでください。")
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
        progress = z.Progress(progress_path(path, ym, practice), csv_hash, f"{ym[0]}-{ym[1]:02d}")
        rows = [r for r in g["rows"] if r.line > progress.last_completed]
        if not rows:
            messagebox.showinfo("自動入力", f"{ym_label(ym)}の仕訳はすべて入力済みです。\n"
                                "やり直すときは「この月の記録を消す」を押してください。", parent=self.root)
            return

        first = "税区分" if g["tax"] == "課税" else "借方科目"
        done = len(g["rows"]) - len(rows)
        lines = [f"CSV：{path.name}",
                 f"月：{ym_label(ym)}　消費税：{g['tax']}",
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
            lines += ["", f"財務エントリで、入力先の関与先の「会計伝票」（月次入力・{ym[1]}月分）を開いていますか？", "",
                      "「はい」を押したら：", "1. 財務エントリの画面をクリック",
                      f"2. カーソルを新しい行の「{first}」の欄に置く", "3. PgUp を押すと入力が始まります"]
        if not messagebox.askyesno("メモ帳で練習" if practice else "入力開始", "\n".join(lines), parent=self.root):
            return

        target = g["cfg"].get("target", {}).get("notepad" if practice else "zaimu")
        self.write("")
        self.status_var.set(f"{'メモ帳' if practice else '財務エントリ'}をクリックしてから PgUp を押してください")
        self.set_running(True)
        threading.Thread(target=self.worker, daemon=True,
                         args=(g["cfg"], target, rows, progress, practice, path)).start()

    def worker(self, cfg, target, rows, progress, practice, path):
        kind = "練習" if practice else "本番"
        try:
            win = z.Win()
            sender = z.Sender(cfg, win)
            self.ctl = z.Controller(cfg, target, win, notify=self.post,
                                    quit_hint="自動入力の画面の「中止」ボタン")
            self.ctl.install()
            try:
                z.write_log(f"開始（{kind}）  {path}  {progress.month_label}  CSV {rows[0].line}行目から", LOG_FILE)
                z.run_rows(rows, cfg, self.ctl, sender, progress, notify=self.post, log_file=LOG_FILE,
                           on_row_done=lambda n, t: self.queue.put(("status", f"入力中… {n}/{t}件 完了")))
            finally:
                self.ctl.uninstall()
            self.post(f"\n✔ すべて入力しました（{len(rows)}件）。")
            self.queue.put(("status", f"終了しました（{len(rows)}件）"))
            z.write_log(f"終了（{kind}）  {len(rows)}件", LOG_FILE)
        except z.Cancelled:
            msg = f"中止しました。CSV {progress.last_completed}行目まで入力済みです。"
            if progress.in_progress:
                msg += f"\n※ CSV {progress.in_progress}行目は入力途中です。財務エントリの画面で確認し、残っていれば消してください。"
            self.post("\n" + msg)
            self.queue.put(("status", "中止しました"))
            z.write_log(f"中止（{kind}）  {progress.last_completed}行目まで完了", LOG_FILE)
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
        ym = self.selected_month()
        if not (self.csv and ym):
            messagebox.showwarning("記録を消す", "CSV と月を選んでください。", parent=self.root)
            return
        paths = [progress_path(self.csv, ym, practice=p) for p in (False, True)]
        if not any(p.exists() for p in paths):
            messagebox.showinfo("記録を消す", "この月の記録はありません。", parent=self.root)
            return
        if not messagebox.askyesno("記録を消す",
                                   f"{self.csv.name} の{ym_label(ym)}の入力記録を消します。\n"
                                   "次に入力すると、この月の最初の仕訳から入力します。よろしいですか？",
                                   parent=self.root):
            return
        for p in paths:
            p.unlink(missing_ok=True)
        z.write_log(f"記録を消去  {self.csv}  {ym[0]}-{ym[1]:02d}", LOG_FILE)
        self.refresh_months()
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
        # ショートカットに CSV をドラッグ＆ドロップすると、その CSV を選んだ状態で開く
        App(root, sys.argv[1] if len(sys.argv) > 1 else None)
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
