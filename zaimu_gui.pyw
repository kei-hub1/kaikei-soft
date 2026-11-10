"""財務エントリ 自動入力（ウィンドウ画面）。

「起動.bat」から起動する。CSV を選び、月を選んでボタンを押すだけで入力できる。
入力の中身（キー操作の順番など）は zaimu_input.py と config.toml による。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
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
PREF_FILE = RECORD_DIR / "画面の設定.json"   # 前回のフォルダー・速さ
TRACE_FILE = RECORD_DIR / "詳細ログ.txt"   # 送ったキー1つずつと、そのときの最前面のウィンドウ（ずれの調査用）
# 速さの選択肢と、待ち時間の倍率（config.toml の [timing] と各手順の wait に掛ける）
SPEEDS = {"ゆっくり（確認用）": 3.0, "標準": 1.0, "速い": 0.5, "とても速い": 0.25, "最速": 0.12}
SLOW = "ゆっくり（確認用）"   # この速さのときだけ詳細ログを残す（記録の分だけ遅くなるため）


def progress_path(csv_path: Path, ym: tuple[int, int], practice: bool) -> Path:
    """CSV の場所と月ごとの記録ファイル。同じ名前の CSV が別のフォルダーにあっても混ざらない。"""
    key = hashlib.sha1(str(csv_path.resolve()).encode("utf-8")).hexdigest()[:8]
    suffix = "_練習" if practice else ""
    return RECORD_DIR / f"{csv_path.stem}_{key}_{ym[0]}-{ym[1]:02d}{suffix}.json"


def find_progress(csv_path: Path, ym: tuple[int, int], practice: bool, rows: list[z.Row]) -> z.Progress:
    """その CSV・その月の記録を開く。

    CSV を別のフォルダーへ移したり名前を変えたりすると、記録ファイルの名前が合わなくなる。
    そのままだと「未入力」に見えて二重に入力してしまうため、中身（入力済みの仕訳）が一致する記録が
    ほかにあれば、それを引き継ぐ。
    """
    month_label = f"{ym[0]}-{ym[1]:02d}"
    path = progress_path(csv_path, ym, practice)
    if not path.exists() and RECORD_DIR.exists():
        suffix = "_練習" if practice else ""
        for other in sorted(RECORD_DIR.glob(f"*_{month_label}{suffix}.json")):
            try:
                if z.Progress(other, month_label).matches(rows):
                    other.rename(path)
                    break
            except (OSError, ValueError):
                continue
    return z.Progress(path, month_label)


def ym_label(ym: tuple[int, int]) -> str:
    return f"{ym[0]}年{ym[1]}月"


def load_pref(key: str):
    try:
        return json.loads(PREF_FILE.read_text(encoding="utf-8")).get(key)
    except Exception:
        return None


def save_pref(key: str, value):
    RECORD_DIR.mkdir(exist_ok=True)
    try:
        prefs = json.loads(PREF_FILE.read_text(encoding="utf-8"))
    except Exception:
        prefs = {}
    prefs[key] = value
    PREF_FILE.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")


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
        root.geometry("800x660")
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

        ttk.Label(top, text="補助コード").grid(row=2, column=0, sticky="w", **pad)
        subf = ttk.Frame(top)
        subf.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        # 関与先ごとに違うため、覚えておかない（前の関与先のコードを取り違えないように）
        self.sub_var = tk.StringVar()
        self.sub_entry = ttk.Entry(subf, textvariable=self.sub_var, width=8)
        self.sub_entry.pack(side="left")
        ttk.Label(subf, text="普通預金（1113）の補助コード。財務エントリで確かめて入れる。補助科目がない関与先は空欄").pack(
            side="left", padx=(8, 0))

        ttk.Label(top, text="月").grid(row=3, column=0, sticky="nw", **pad)
        self.month_tree = ttk.Treeview(top, columns=("month", "count", "state"), show="headings",
                                       height=6, selectmode="browse")
        for col, text, width in (("month", "月", 110), ("count", "件数", 60), ("state", "状態", 300)):
            self.month_tree.heading(col, text=text)
            self.month_tree.column(col, width=width, anchor="e" if col == "count" else "w")
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
        ttk.Button(btns, text="記録フォルダー", command=self.open_records).pack(side="right", padx=4)

        self.status_var = tk.StringVar(value="「CSV を選ぶ」を押してください")
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

        opts = ttk.Frame(top)
        opts.grid(row=8, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 0))
        ttk.Label(opts, text="速さ").pack(side="left")
        speed = load_pref("speed")
        self.speed_var = tk.StringVar(value=speed if speed in SPEEDS else "標準")
        self.speed_box = ttk.Combobox(opts, textvariable=self.speed_var, values=list(SPEEDS),
                                      state="readonly", width=14)
        self.speed_box.bind("<<ComboboxSelected>>", lambda e: save_pref("speed", self.speed_var.get()))
        self.speed_box.pack(side="left", padx=(4, 0))
        cont = load_pref("continue_months")
        self.continue_var = tk.BooleanVar(value=True if cont is None else bool(cont))
        self.continue_chk = ttk.Checkbutton(opts, text="続けて次の月も入力する", variable=self.continue_var,
                                            command=lambda: save_pref("continue_months", self.continue_var.get()))
        self.continue_chk.pack(side="left", padx=(12, 0))
        self.each_var = tk.BooleanVar(value=False)
        self.each_chk = ttk.Checkbutton(opts, text="1件ごとに止めて確認する", variable=self.each_var)
        self.each_chk.pack(side="left", padx=(12, 0))
        hide = load_pref("hide_while_running")
        self.hide_var = tk.BooleanVar(value=True if hide is None else bool(hide))
        opts2 = ttk.Frame(top)
        opts2.grid(row=9, column=0, columnspan=3, sticky="ew", padx=6, pady=(2, 0))
        self.hide_chk = ttk.Checkbutton(opts2, text="入力中はこの画面をしまう", variable=self.hide_var,
                                        command=lambda: save_pref("hide_while_running", self.hide_var.get()))
        self.hide_chk.pack(side="left")
        self.topmost_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts2, text="常に手前に表示", variable=self.topmost_var,
                        command=lambda: self.root.attributes("-topmost", self.topmost_var.get())).pack(
            side="left", padx=(12, 0))
        self.root.attributes("-topmost", True)

        self.inputs = [self.pick_btn, self.check_btn, self.practice_btn, self.start_btn,
                       self.reset_btn, self.sub_entry, self.speed_box, self.continue_chk, self.each_chk, self.hide_chk,
                       *self.tax_radios]

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
        """入力中のスレッドから画面へ文字を送る。止まったとき（■）は、しまっていた画面を出す。"""
        self.queue.put(("log", text))
        if text.startswith("■"):
            self.queue.put(("show", None))

    def show_window(self):
        self.root.deiconify()
        self.root.lift()

    def poll_queue(self):
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == "log":
                    self.write(value)
                elif kind == "status":
                    self.status_var.set(value)
                elif kind == "show":
                    self.show_window()
                elif kind == "done":
                    self.set_running(False)
                    self.refresh_months()
                    self.show_window()
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def set_running(self, running: bool):
        self.running = running
        for w in self.inputs:
            idle = "readonly" if isinstance(w, ttk.Combobox) else "normal"
            w.configure(state="disabled" if running else idle)
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
        initial = str(self.csv.parent) if self.csv else load_pref("dir")
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
        save_pref("dir", str(path.parent))
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
        for ym, month_rows in z.group_by_month(rows).items():
            iid = f"{ym[0]}-{ym[1]:02d}"
            self.months[iid] = ym
            state = self.month_state(ym, month_rows)
            self.month_tree.insert("", "end", iid=iid, values=(ym_label(ym), len(month_rows), state))
        if selected and selected[0] in self.months:
            self.month_tree.selection_set(selected[0])
        elif len(self.months) == 1:
            self.month_tree.selection_set(next(iter(self.months)))

    def month_state(self, ym, rows: list[z.Row]) -> str:
        prog = find_progress(self.csv, ym, False, rows)
        if not prog.data:
            return "未入力"
        done, problem = prog.resolve(rows)
        if problem:
            return "入力済みの仕訳が CSV の中で変わっています（入力開始で詳しく表示）"
        state = "入力済み" if done == len(rows) else ("未入力" if done == 0 else f"{done}件まで入力済み")
        if prog.in_progress:
            state += "（前回、途中で終了）"
        return state

    def selected_month(self) -> tuple[int, int] | None:
        sel = self.month_tree.selection()
        return self.months.get(sel[0]) if sel else None

    # ── 確認・入力 ──

    def target_months(self) -> list[tuple[int, int]]:
        """入力する月。「続けて次の月も入力する」なら、選んだ月から CSV の最後の月まで。"""
        ym = self.selected_month()
        if not ym:
            return []
        months = sorted(self.months.values())
        return [m for m in months if m >= ym] if self.continue_var.get() else [ym]

    def gather(self) -> dict | None:
        """選んだ CSV・月・消費税を確かめ、月ごとの対象の仕訳とチェック結果を返す。"""
        if not self.csv:
            messagebox.showwarning("自動入力", "「CSV を選ぶ」で CSV を選んでください。", parent=self.root)
            return None
        yms = self.target_months()
        if not yms:
            messagebox.showwarning("自動入力", "入力する月を選んでください。", parent=self.root)
            return None
        tax = self.tax_var.get()
        if not tax:
            messagebox.showwarning("自動入力", "消費税の「課税」か「免税」を選んでください。", parent=self.root)
            return None
        try:
            cfg = self.load_cfg()
            header, rows, errors = z.load_rows(self.csv, cfg, {"消費税": tax})
            errors += z.apply_sub_code(rows, z.bank_account(cfg), self.sub_var.get())
        except (z.UserError, UnicodeDecodeError) as e:
            messagebox.showerror("自動入力", str(e), parent=self.root)
            return None
        groups = z.group_by_month(rows)
        months, warnings = [], []
        for ym in yms:
            month_rows = groups.get(ym, [])
            errors += [f"{ym_label(ym)}: {e}" for e in z.apply_tax(month_rows, cfg)]
            more_errors, more_warnings = z.validate(month_rows, header, cfg)
            errors += [f"{ym_label(ym)}: {e}" for e in more_errors]
            warnings += [f"{ym_label(ym)}: {w}" for w in more_warnings]
            months.append(dict(ym=ym, rows=month_rows))
        return dict(cfg=cfg, path=self.csv, tax=tax, sub=self.sub_var.get().strip() or "なし",
                    months=months, errors=errors, warnings=warnings)

    def report(self, g: dict) -> bool:
        """チェック結果を表示する。誤りがなければ True。"""
        self.clear_log()
        span = ym_label(g["months"][0]["ym"])
        if len(g["months"]) > 1:
            span += f"〜{ym_label(g['months'][-1]['ym'])}"
        total = sum(len(m["rows"]) for m in g["months"])
        self.write(f"CSV: {g['path'].name}　消費税: {g['tax']}　普通預金の補助コード: {g['sub']}　"
                   f"月: {span}　仕訳: {total}件")
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
        for m in g["months"]:
            self.write(f"\n{ym_label(m['ym'])}の仕訳:")
            for r in m["rows"]:
                self.write(f"  {z.row_summary(r)}")
        first_rows = [m["rows"][0] for m in g["months"] if m["rows"]]
        if first_rows:
            self.write("\n1件目の操作の順番:")
            for line in z.plan_lines(g["cfg"]["steps"], first_rows[0].values):
                self.write(f"  {line}")
        if len(g["months"]) > 1:
            self.write("\n月の切り替え:")
            yms = [m["ym"] for m in g["months"]]
            if g["cfg"]["month_switch"]:
                for line in z.plan_lines(g["cfg"]["month_switch"], z.month_switch_values(yms[0], yms[1])):
                    self.write(f"  {line}")
                for note in self.gap_notes(yms):
                    self.write(f"  ※ {note}")
            else:
                self.write("  月の変わり目で一時停止します（手で次の月に切り替えてから PgUp）")
        self.write("\n問題ありません。（「確認」ではキーは送っていません）")
        self.status_var.set("確認しました")

    @staticmethod
    def gap_notes(yms: list[tuple[int, int]]) -> list[str]:
        """月が続いていないところ。自動の切り替えは「次の月」にしか使えないため、そこでは一時停止する。"""
        return [f"{a[1]}月分のあとは{b[1]}月分で、月が続いていないため、一時停止します（手で切り替えて PgUp）"
                for a, b in zip(yms, yms[1:]) if not z.is_next_month(a, b)]

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
        path = g["path"]
        plan, problems = [], []   # plan は、まだ入力していない仕訳がある月だけ
        for m in g["months"]:
            ym = m["ym"]
            progress = find_progress(path, ym, practice, m["rows"])
            done, problem = progress.resolve(m["rows"])
            if problem:
                problems.append(f"{ym_label(ym)}: {problem}")
            elif done < len(m["rows"]):
                plan.append(dict(ym=ym, rows=m["rows"], start=done, todo=len(m["rows"]) - done, progress=progress))
        if problems:
            self.write("\n次の理由で、入力できません。")
            for e in problems:
                self.write(f"× {e}")
            messagebox.showerror("自動入力", "前回の入力の記録と CSV が合わないため、入力できません。下の欄を見てください。",
                                 parent=self.root)
            return
        if not plan:
            messagebox.showinfo("自動入力", "選んだ月の仕訳はすべて入力済みです。\n"
                                "やり直すときは「この月の記録を消す」を押してください。", parent=self.root)
            return

        first_field = "税区分" if g["tax"] == "課税" else "借方科目"
        first_ym = plan[0]["ym"]
        lines = [f"CSV：{path.name}　消費税：{g['tax']}", f"普通預金の補助コード：{g['sub']}", ""]
        for m in plan:
            lines.append(f"{ym_label(m['ym'])}：{m['todo']}件"
                         + (f"（入力済みの{m['start']}件は飛ばします）" if m["start"] else ""))
        if len(plan) > 1:
            how = "自動で切り替えます" if g["cfg"]["month_switch"] else "一時停止します（手で切り替えて PgUp）"
            lines += ["", f"月の変わり目では、財務エントリの月を{how}。"]
            if g["cfg"]["month_switch"]:
                lines += [f"※ {note}" for note in self.gap_notes([m["ym"] for m in plan])]
        if plan[0]["progress"].in_progress:
            # 記録にある行番号は、CSV の行がずれると古くなる。途中だったのは、次に入力する仕訳
            line = plan[0]["rows"][plan[0]["start"]].line
            lines += ["", f"※ 前回は CSV {line}行目の入力途中で終了しています。",
                      "入力途中の行が残っていれば、先に手で消してください。"]
        if g["warnings"]:
            lines += ["", f"※ 注意が{len(g['warnings'])}件あります（下の欄を見てください）。"]
        if practice:
            lines += ["", "メモ帳を開いておいてください。", "",
                      "「はい」を押したら：", "1. メモ帳をクリック", "2. PgUp を押すと入力が始まります"]
        else:
            lines += ["", f"財務エントリで、入力先の関与先の「会計伝票」（月次入力・{first_ym[1]}月分）を開いていますか？", "",
                      "「はい」を押したら：", "1. 財務エントリの画面をクリック",
                      f"2. カーソルを新しい行の「{first_field}」の欄に置く", "3. PgUp を押すと入力が始まります"]
        if not messagebox.askyesno("メモ帳で練習" if practice else "入力開始", "\n".join(lines), parent=self.root):
            return

        target = g["cfg"].get("target", {}).get("notepad" if practice else "zaimu")
        self.write("")
        self.status_var.set(f"{'メモ帳' if practice else '財務エントリ'}をクリックしてから PgUp を押してください")
        self.set_running(True)
        options = dict(speed=SPEEDS[self.speed_var.get()], stop_each_row=self.each_var.get(),
                       trace_file=TRACE_FILE if self.speed_var.get() == SLOW else None)
        if self.hide_var.get():
            self.root.iconify()  # 入力中は画面をしまう（止まったとき・終わったときに出てくる）
        threading.Thread(target=self.worker, daemon=True,
                         args=(g["cfg"], target, plan, practice, path, first_field, options)).start()

    def worker(self, cfg, target, plan, practice, path, first_field, options):
        kind = "練習" if practice else "本番"
        current, sender = plan[0], None
        try:
            win = z.Win()
            sender = z.Sender(cfg, win)
            self.ctl = z.Controller(cfg, target, win, notify=self.post,
                                    quit_hint="自動入力の画面の「中止」ボタン")
            runner = z.Runner(cfg, self.ctl, sender, options["speed"], options["trace_file"])
            self.ctl.install()
            try:
                for i, current in enumerate(plan):
                    ym, rows, progress = current["ym"], current["rows"], current["progress"]
                    if i > 0:
                        self.post(f"\n── {ym[1]}月分に切り替えます")
                        self.queue.put(("status", f"{ym[1]}月分に切り替え中…"))
                        runner.switch_month(plan[i - 1]["ym"], ym, first_field)
                    first_line = rows[current["start"]].line
                    header = f"開始（{kind}）  {path}  {progress.month_label}  CSV {first_line}行目から"
                    self.post(f"\n── {ym_label(ym)}（{current['todo']}件）")
                    z.write_log(header, LOG_FILE)
                    if options["trace_file"]:
                        z.write_log(f"──── {header}", options["trace_file"])
                    label = ym_label(ym)
                    runner.run_rows(rows, current["start"], progress, notify=self.post, log_file=LOG_FILE,
                                    on_row_done=lambda n, t, label=label: self.queue.put(
                                        ("status", f"{label} 入力中… {n}/{t}件 完了")),
                                    stop_each_row=options["stop_each_row"])
                    z.write_log(f"終了（{kind}）  {progress.month_label}  {current['todo']}件", LOG_FILE)
            finally:
                self.ctl.uninstall()
            total = sum(m["todo"] for m in plan)
            self.post(f"\n✔ すべて入力しました（{len(plan)}か月・{total}件）。")
            self.queue.put(("status", f"終了しました（{len(plan)}か月・{total}件）"))
        except z.Cancelled:
            progress = current["progress"]
            msg = f"中止しました。{ym_label(current['ym'])}は CSV {progress.last_completed}行目まで入力済みです。"
            if progress.in_progress:
                msg += f"\n※ CSV {progress.in_progress}行目は入力途中です。財務エントリの画面で確認し、残っていれば消してください。"
            self.post("\n" + msg)
            self.queue.put(("status", "中止しました"))
            z.write_log(f"中止（{kind}）  {progress.month_label}  {progress.last_completed}行目まで完了", LOG_FILE)
        except Exception:
            self.post("\nエラーで止まりました:\n" + traceback.format_exc())
            self.queue.put(("status", "エラーで止まりました"))
        finally:
            if sender:
                sender.clear_clipboard()
            self.ctl = None
            self.queue.put(("done", None))

    def open_records(self):
        RECORD_DIR.mkdir(exist_ok=True)
        if sys.platform == "win32":
            os.startfile(RECORD_DIR)
        else:
            self.write(f"記録フォルダー: {RECORD_DIR}")

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
