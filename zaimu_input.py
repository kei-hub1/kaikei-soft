"""財務エントリ（会計伝票・月次入力）に、CSV の仕訳をキー操作で入力する。

使い方は README.md を参照。キー操作の順番は config.toml の [[steps]] で決める。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import string
import sys
import time
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "config.toml"
LOG_FILE = BASE_DIR / "zaimu_input.log"

# press に書けるキー名（pywinauto の send_keys の名前と同じ）
KEY_NAMES = {
    "ENTER", "TAB", "ESC", "BACKSPACE", "DELETE", "SPACE",
    "UP", "DOWN", "LEFT", "RIGHT", "HOME", "END",
    *(f"F{i}" for i in range(1, 13)),
}
STEP_KEYS = {"name", "type", "paste", "press", "wait", "manual",
             "when_not_empty", "when_column", "when_in"}
# send_keys で特別な意味を持つ文字（{} で囲んで送る）
SEND_KEYS_SPECIAL = set("+^%~(){}[]")


class UserError(Exception):
    """設定や CSV の誤り。メッセージを表示して終了する。"""


class Cancelled(Exception):
    """入力の途中で中止した。"""


# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────

@dataclass
class Step:
    name: str
    type: str | None = None
    paste: str | None = None
    press: list[str] = field(default_factory=list)
    wait: float = 0.0
    manual: str | None = None
    when_not_empty: str | None = None
    when_column: str | None = None
    when_in: list[str] | None = None

    def templates(self) -> list[str]:
        return [t for t in (self.type, self.paste) if t]

    def applies(self, values: dict[str, str]) -> bool:
        if self.when_not_empty and not values.get(self.when_not_empty, "").strip():
            return False
        if self.when_column and values.get(self.when_column, "").strip() not in (self.when_in or []):
            return False
        return True


def load_config(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        raise UserError(f"設定ファイルが見つかりません: {path}")
    except tomllib.TOMLDecodeError as e:
        raise UserError(f"設定ファイルの書き方に誤りがあります: {path}\n  {e}")

    steps = []
    for i, raw in enumerate(cfg.get("steps", []), 1):
        where = f"[[steps]] の {i} 番目（{raw.get('name', '名前なし')}）"
        unknown = set(raw) - STEP_KEYS
        if unknown:
            raise UserError(f"{where}: 知らない項目があります: {', '.join(sorted(unknown))}")
        if raw.get("type") and raw.get("paste"):
            raise UserError(f"{where}: type と paste は同時に書けません")
        for key in raw.get("press", []):
            if key not in KEY_NAMES:
                raise UserError(f"{where}: press のキー名 '{key}' は使えません。"
                                f"使える名前: {' '.join(sorted(KEY_NAMES))}")
        if bool(raw.get("when_column")) != bool(raw.get("when_in")):
            raise UserError(f"{where}: when_column と when_in は両方そろえて書いてください")
        steps.append(Step(name=raw.get("name", f"手順{i}"), **{k: v for k, v in raw.items() if k != "name"}))
    if not steps:
        raise UserError("設定ファイルに [[steps]] がありません")
    cfg["steps"] = steps
    return cfg


# ─────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────

@dataclass
class Row:
    line: int                 # CSV 上の行番号（見出しが1行目）
    date: dt.date
    values: dict[str, str]    # CSV の値 + {年} {月} {日} {金額}


def read_csv_text(path: Path, encoding: str) -> str:
    data = path.read_bytes()
    if encoding != "auto":
        return data.decode(encoding)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp932")


def parse_date(text: str) -> dt.date:
    text = unicodedata.normalize("NFKC", text).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


def normalize_amount(text: str) -> str:
    return re.sub(r"[,，円\s]", "", unicodedata.normalize("NFKC", text))


def load_rows(path: Path, cfg: dict, extra: dict[str, str] | None = None) -> tuple[list[str], list[Row], list[str]]:
    """CSV を読む。戻り値は（見出し, 行, 誤りの一覧）。

    extra は、すべての行に追加する値（例: 関与先の {消費税}）。見出しにも加えて返す。
    """
    extra = extra or {}
    csv_cfg = cfg.get("csv", {})
    date_col = csv_cfg.get("date_column", "日付")
    amount_col = csv_cfg.get("amount_column", "金額")
    try:
        text = read_csv_text(path, csv_cfg.get("encoding", "auto"))
    except FileNotFoundError:
        raise UserError(f"CSV が見つかりません: {path}")

    reader = csv.reader(text.splitlines())
    header = [h.strip() for h in next(reader, [])]
    for col in (date_col, amount_col):
        if col not in header:
            raise UserError(f"CSV の見出しに「{col}」がありません。見出し: {', '.join(header)}")

    rows, errors = [], []
    for line, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        values = {h: (cells[i].strip() if i < len(cells) else "") for i, h in enumerate(header)}
        try:
            date = parse_date(values[date_col])
        except ValueError:
            errors.append(f"{line}行目: 日付「{values[date_col]}」を読み取れません")
            continue
        values.update(年=str(date.year), 月=str(date.month), 日=str(date.day),
                      金額=normalize_amount(values[amount_col]), **extra)
        rows.append(Row(line, date, values))
    return header + [k for k in extra if k not in header], rows, errors


def parse_month(text: str) -> tuple[int | None, int]:
    """'1' / '01' / '2026-01' / '2026/1' を（年, 月）にする。"""
    m = re.fullmatch(r"(?:(\d{4})[-/])?(\d{1,2})", text.strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise UserError(f"--month の形式が違います: {text}（例: 1 または 2026-01）")
    return (int(m.group(1)) if m.group(1) else None), int(m.group(2))


def group_by_month(rows: list[Row]) -> dict[tuple[int, int], list[Row]]:
    """（年, 月）ごとに分ける。古い月から順。"""
    groups: dict[tuple[int, int], list[Row]] = {}
    for r in sorted(rows, key=lambda r: (r.date.year, r.date.month, r.line)):
        groups.setdefault((r.date.year, r.date.month), []).append(r)
    return groups


def filter_month(rows: list[Row], year: int | None, month: int) -> list[Row]:
    picked = [r for r in rows if r.date.month == month and (year is None or r.date.year == year)]
    years = sorted({r.date.year for r in picked})
    if year is None and len(years) > 1:
        raise UserError(f"{month}月の仕訳が複数の年（{', '.join(map(str, years))}）にあります。"
                        f"--month {years[-1]}-{month:02d} のように年も指定してください")
    return picked


# ─────────────────────────────────────────────
# 入力前のチェック
# ─────────────────────────────────────────────

def template_fields(template: str) -> list[str]:
    return [f for _, f, _, _ in string.Formatter().parse(template) if f]


def render(template: str, values: dict[str, str]) -> str:
    return template.format_map(values)


def validate(rows: list[Row], header: list[str], cfg: dict) -> tuple[list[str], list[str]]:
    """（誤り, 注意）を返す。誤りが1件でもあれば入力しない。"""
    errors, warnings = [], []
    steps: list[Step] = cfg["steps"]
    known = set(header) | {"年", "月", "日", "金額"}

    for step in steps:
        for t in step.templates():
            for f in template_fields(t):
                if f not in known:
                    errors.append(f"設定「{step.name}」の {{{f}}} が CSV の見出しにありません")
        for col in (step.when_not_empty, step.when_column):
            if col and col not in known:
                errors.append(f"設定「{step.name}」の条件の列「{col}」が CSV の見出しにありません")
    if errors:
        return errors, warnings

    check = cfg.get("check", {})
    allowed = {"借方科目コード": check.get("debit_accounts"), "貸方科目コード": check.get("credit_accounts")}
    max_bytes: dict[str, int] = check.get("max_bytes", {})
    used_cols = {f for s in steps for t in s.templates() for f in template_fields(t)}
    used_cols |= {c for s in steps for c in (s.when_not_empty, s.when_column) if c}

    for row in rows:
        v = row.values
        where = f"{row.line}行目"
        for col, codes in allowed.items():
            if codes is not None and col in v and v[col] not in codes:
                errors.append(f"{where}: {col}「{v[col]}」は入力対象外です（対象: {', '.join(codes)}）")
        if not re.fullmatch(r"\d+", v["金額"]) or int(v["金額"]) == 0:
            errors.append(f"{where}: 金額「{v.get(cfg.get('csv', {}).get('amount_column', '金額'))}」が正の整数ではありません")
        for col, limit in max_bytes.items():
            text = v.get(col, "")
            try:
                size = len(text.encode("cp932"))
            except UnicodeEncodeError:
                continue  # 下の貼り付けのチェックで報告する
            if size > limit:
                errors.append(f"{where}: {col}「{text}」が長すぎます（{size}バイト／上限{limit}バイト）")
        for step in steps:
            if not step.applies(v):
                continue
            if step.type:
                s = render(step.type, v)
                if not s.isascii():
                    errors.append(f"{where}: 「{step.name}」で打つ文字「{s}」に半角英数字以外が含まれます"
                                  f"（日本語は paste を使ってください）")
            if step.paste:
                s = render(step.paste, v)
                bad = [c for c in s if not _cp932_ok(c)]
                if bad:
                    errors.append(f"{where}: 「{step.name}」に財務エントリで使えない文字があります: {''.join(bad)}")
        for col in ("借方補助コード", "貸方補助コード"):
            if v.get(col) and col not in used_cols:
                warnings.append(f"{where}: {col}「{v[col]}」がありますが、設定では補助科目を入力しません")
    return errors, warnings


def _cp932_ok(ch: str) -> bool:
    try:
        ch.encode("cp932")
        return True
    except UnicodeEncodeError:
        return False


# ─────────────────────────────────────────────
# 1仕訳分の操作の組み立て
# ─────────────────────────────────────────────

@dataclass
class Action:
    step: str
    kind: str          # "type" / "paste" / "press" / "wait" / "manual"
    value: str | float


def build_actions(steps: list[Step], values: dict[str, str]) -> list[Action]:
    actions = []
    for s in steps:
        if not s.applies(values):
            continue
        if s.manual:
            actions.append(Action(s.name, "manual", s.manual))
        if s.type:
            actions.append(Action(s.name, "type", render(s.type, values)))
        if s.paste:
            text = render(s.paste, values)
            if text:
                actions.append(Action(s.name, "paste", text))
        for key in s.press:
            actions.append(Action(s.name, "press", key))
        if s.wait:
            actions.append(Action(s.name, "wait", float(s.wait)))
    return actions


def describe(action: Action) -> str:
    return {
        "type": lambda v: f"「{v}」を打つ",
        "paste": lambda v: f"「{v}」を貼り付け",
        "press": lambda v: f"{v} を押す",
        "wait": lambda v: f"{v}秒待つ",
        "manual": lambda v: f"一時停止して手作業（{v}）",
    }[action.kind](action.value)


def plan_lines(steps: list[Step], values: dict[str, str]) -> list[str]:
    """1仕訳分の操作を、欄ごとに1行の説明にする。"""
    lines: dict[str, list[str]] = {}
    for a in build_actions(steps, values):
        lines.setdefault(a.step, []).append(describe(a))
    return [f"{step}: {' → '.join(descs)}" for step, descs in lines.items()]


def row_summary(row: Row) -> str:
    v = row.values
    return (f"CSV {row.line}行目  {row.date:%Y/%m/%d}  "
            f"借方{v.get('借方科目コード', '')} / 貸方{v.get('貸方科目コード', '')}  "
            f"{int(v['金額']):,}円  {v.get('取引先名', '')}  {v.get('摘要', '')}")


# ─────────────────────────────────────────────
# Windows 操作（ウィンドウの確認・キー送信）
# ─────────────────────────────────────────────

class Win:
    """Windows API の薄いラッパー。Windows 以外では使わない。"""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wt = ctypes, wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.imm32 = ctypes.WinDLL("imm32", use_last_error=True)
        u, k = self.user32, self.kernel32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW.restype = wintypes.LPARAM
        self.imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
        self.imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]

    def foreground(self) -> tuple[int, str, int]:
        """最前面のウィンドウの（ハンドル, タイトル, プロセスID）。"""
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return 0, "", 0
        n = self.user32.GetWindowTextLengthW(hwnd)
        buf = self.ctypes.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
        return hwnd, buf.value, pid.value

    def process_name(self, pid: int) -> str:
        h = self.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return "?"
        try:
            size = self.wt.DWORD(1024)
            buf = self.ctypes.create_unicode_buffer(size.value)
            if self.kernel32.QueryFullProcessImageNameW(h, 0, buf, self.ctypes.byref(size)):
                return Path(buf.value).name
            return "?"
        finally:
            self.kernel32.CloseHandle(h)

    def ime_off(self):
        """入力中の欄の IME をオフにする。"""
        ct, wt = self.ctypes, self.wt

        class GUITHREADINFO(ct.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND),
                        ("hwndFocus", wt.HWND), ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
                        ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]

        hwnd = self.user32.GetForegroundWindow()
        tid = self.user32.GetWindowThreadProcessId(hwnd, None)
        info = GUITHREADINFO(cbSize=ct.sizeof(GUITHREADINFO))
        if self.user32.GetGUIThreadInfo(tid, ct.byref(info)) and info.hwndFocus:
            hwnd = info.hwndFocus
        ime = self.imm32.ImmGetDefaultIMEWnd(hwnd)
        if ime:
            self.user32.SendMessageW(ime, 0x0283, 0x0006, 0)  # WM_IME_CONTROL, IMC_SETOPENSTATUS, 閉じる


class Sender:
    """キーを送る。"""

    def __init__(self, cfg: dict, win: Win):
        from pywinauto.keyboard import send_keys
        import pyperclip
        self.send_keys, self.pyperclip, self.win = send_keys, pyperclip, win
        mode = cfg.get("input", {}).get("char_mode", "vk")
        if mode not in ("vk", "unicode"):
            raise UserError(f"[input] char_mode は \"vk\" か \"unicode\" にしてください（今: {mode}）")
        self.vk_packet = mode == "unicode"
        self.ime_off_before_type = cfg.get("input", {}).get("ime_off_before_type", False)

    def before_type(self):
        if self.ime_off_before_type:
            self.win.ime_off()

    def type_char(self, ch: str):
        if ch in SEND_KEYS_SPECIAL:
            ch = "{%s}" % ch
        elif ch == " ":
            ch = "{SPACE}"
        self.send_keys(ch, pause=0, vk_packet=self.vk_packet)

    def press(self, key: str):
        self.send_keys("{%s}" % key, pause=0, vk_packet=False)

    def paste(self, text: str):
        self.pyperclip.copy(text)
        for _ in range(20):
            if self.pyperclip.paste() == text:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("クリップボードに文字を入れられませんでした")
        self.send_keys("^v", pause=0, vk_packet=False)


class Controller:
    """PgDn / PgUp による一時停止・再開と、入力先ウィンドウの確認。"""

    def __init__(self, cfg: dict, target: dict, win: Win, notify=print,
                 quit_hint: str = "この画面をクリックして Ctrl+C"):
        self.win, self.target, self.notify, self.quit_hint = win, target, notify, quit_hint
        self.resume_wait = cfg.get("timing", {}).get("resume_wait", 0.5)
        hk = cfg.get("hotkeys", {})
        self.pause_key, self.resume_key = hk.get("pause", "page down"), hk.get("resume", "page up")
        names = {"page down": "PgDn", "page up": "PgUp"}
        self.pause_label = names.get(self.pause_key, self.pause_key)
        self.resume_label = names.get(self.resume_key, self.resume_key)
        self.paused = True
        self.cancelled = False
        self.target_pid: int | None = None
        self.position = ""   # 今どこを入力しているか（停止時の表示用）

    def install(self):
        import keyboard
        self.keyboard = keyboard
        keyboard.add_hotkey(self.pause_key, self._on_pause, suppress=True)
        keyboard.add_hotkey(self.resume_key, self._on_resume, suppress=True)

    def uninstall(self):
        self.keyboard.unhook_all()

    def _on_pause(self):
        if not self.paused:
            self.paused = True
            self.notify(f"■ 一時停止しました（{self.position}の手前）\n"
                        f"  再開: {self.resume_label}　／　終了: {self.quit_hint}")

    def _on_resume(self):
        self.paused = False

    def cancel(self):
        self.cancelled = True

    def stop(self, message: str):
        self.paused = True
        self.notify(f"■ {message}\n  再開: {self.resume_label}　／　終了: {self.quit_hint}")

    def _target_ok(self) -> tuple[bool, str]:
        _, title, pid = self.win.foreground()
        allowed = self.target.get("allowed_titles") or []
        if self.target_pid is None:
            want_exact, want_part = self.target.get("title"), self.target.get("title_contains")
            if (want_exact and title == want_exact) or (want_part and want_part in title):
                self.target_pid = pid
                return True, ""
            return False, (f"最前面のウィンドウが入力先ではありません（今:「{title}」／"
                           f"必要:「{want_exact or want_part}」）")
        if pid != self.target_pid:
            return False, f"最前面のウィンドウが入力先ではないため停止しました（今:「{title}」）"
        if allowed and title not in allowed:
            return False, f"許可していないウィンドウ「{title}」が最前面のため停止しました"
        return True, ""

    def checkpoint(self):
        """キーを1つ送る直前に呼ぶ。停止中なら再開まで待ち、入力先を確かめる。"""
        while True:
            if self.paused:
                while self.paused:
                    if self.cancelled:
                        raise Cancelled
                    time.sleep(0.05)
                time.sleep(self.resume_wait)
                ok, why = self._target_ok()
                if ok:
                    self.notify("▶ 入力します")
                    return
                self.stop(why)
                continue
            if self.cancelled:
                raise Cancelled
            ok, why = self._target_ok()
            if ok:
                return
            self.stop(why)


# ─────────────────────────────────────────────
# 進み具合の記録
# ─────────────────────────────────────────────

class Progress:
    def __init__(self, path: Path, csv_hash: str, month_label: str):
        self.path, self.csv_hash, self.month_label = path, csv_hash, month_label
        self.data = {}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    @property
    def last_completed(self) -> int:
        return self.data.get("last_completed_line", 0)

    @property
    def in_progress(self) -> int | None:
        return self.data.get("in_progress_line")

    def save(self, last_completed: int, in_progress: int | None):
        self.data = {
            "csv_sha256": self.csv_hash,
            "month": self.month_label,
            "last_completed_line": last_completed,
            "in_progress_line": in_progress,
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_log(message: str, path: Path = LOG_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")


def ask_yes(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() in ("y", "yes")


# ─────────────────────────────────────────────
# 実行
# ─────────────────────────────────────────────

def run_rows(rows: list[Row], cfg: dict, ctl: Controller, sender: Sender, progress: Progress,
             notify=print, log_file: Path = LOG_FILE, on_row_done=None):
    timing = cfg.get("timing", {})
    key_interval = timing.get("key_interval", 0.2)
    paste_wait = timing.get("paste_wait", 0.3)
    row_wait = timing.get("row_wait", 0.5)
    last_done = progress.last_completed

    for n, row in enumerate(rows, 1):
        notify(f"[{n}/{len(rows)}] {row_summary(row)}")
        progress.save(last_done, row.line)
        for a in build_actions(cfg["steps"], row.values):
            ctl.position = f"CSV {row.line}行目の「{a.step}」"
            if a.kind == "type":
                sender.before_type()
                for ch in a.value:
                    ctl.checkpoint()
                    sender.type_char(ch)
                    time.sleep(key_interval)
            elif a.kind == "press":
                ctl.checkpoint()
                sender.press(a.value)
                time.sleep(key_interval)
            elif a.kind == "paste":
                ctl.checkpoint()
                sender.paste(a.value)
                time.sleep(paste_wait)
            elif a.kind == "wait":
                time.sleep(a.value)
            elif a.kind == "manual":
                ctl.stop(f"手作業: {a.value}（CSV {row.line}行目「{a.step}」）")
                ctl.checkpoint()
        last_done = row.line
        progress.save(last_done, None)
        write_log(f"完了  {row_summary(row)}", log_file)
        if on_row_done:
            on_row_done(n, len(rows))
        time.sleep(row_wait)


def watch_window():
    win = Win()
    print("最前面のウィンドウを表示します（終了: Ctrl+C）")
    last = None
    while True:
        hwnd, title, pid = win.foreground()
        now = (hwnd, title, pid)
        if now != last:
            print(f"タイトル:「{title}」  プロセスID: {pid}  プログラム: {win.process_name(pid)}")
            last = now
        time.sleep(0.3)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="財務エントリ（会計伝票・月次入力）へ CSV の仕訳を入力する")
    p.add_argument("csv", nargs="?", type=Path, help="入力する CSV ファイル")
    p.add_argument("--month", help="入力する月（例: 1 または 2026-01）")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="設定ファイル（既定: config.toml）")
    p.add_argument("--dry-run", action="store_true", help="キーを送らず、送る予定の操作を表示するだけ")
    p.add_argument("--notepad", action="store_true", help="練習用: メモ帳に入力する")
    p.add_argument("--tax", choices=["課税", "免税"], default="課税", help="関与先の消費税（既定: 課税）")
    p.add_argument("--from-line", type=int, help="CSV のこの行番号から入力する（記録より優先）")
    p.add_argument("--reset", action="store_true", help="前回の記録を無視して最初から入力する")
    p.add_argument("--watch-window", action="store_true", help="最前面のウィンドウのタイトル等を表示するだけ")
    args = p.parse_args(argv)

    try:
        if args.watch_window:
            watch_window()
            return 0
        if not args.csv or not args.month:
            p.error("CSV ファイルと --month を指定してください")

        cfg = load_config(args.config)
        year, month = parse_month(args.month)
        month_label = f"{year}-{month:02d}" if year else f"{month:02d}"
        header, all_rows, errors = load_rows(args.csv, cfg, {"消費税": args.tax})
        rows = filter_month(all_rows, year, month)
        # 日付を読めない行は、どの月か分からないため、月に関係なく誤りとする
        more_errors, warnings = validate(rows, header, cfg)
        errors += more_errors

        print(f"CSV: {args.csv}　対象月: {month_label}　対象の仕訳: {len(rows)}件（CSV 全体 {len(all_rows)}件）")
        if errors:
            print("\n次の誤りがあるため、入力しません。CSV か設定を直してから、もう一度実行してください。")
            for e in errors:
                print(f"  × {e}")
            return 1
        if not rows:
            print("対象の仕訳がありません。")
            return 1

        # 再開位置
        csv_hash = hashlib.sha256(args.csv.read_bytes()).hexdigest()
        suffix = "_notepad" if args.notepad else ""
        progress = Progress(args.csv.with_name(f"{args.csv.stem}_{month_label}{suffix}.progress.json"),
                            csv_hash, month_label)
        start_after = 0
        if args.from_line:
            start_after = args.from_line - 1
        elif not args.reset and progress.data:
            if progress.data.get("csv_sha256") != csv_hash:
                print(f"\n※ 前回の記録（{progress.path.name}）のあとで CSV が変更されています。")
            print(f"前回の記録: CSV {progress.last_completed}行目まで入力済み")
            if progress.in_progress:
                print(f"※ 前回は CSV {progress.in_progress}行目の入力途中で終了しています。"
                      f"財務エントリに入力途中の行が残っていれば、手で消してから続けてください。")
            start_after = progress.last_completed
        rows = [r for r in rows if r.line > start_after]
        if not rows:
            print("この月の仕訳はすべて入力済みです（最初からやり直すときは --reset）。")
            return 0
        print(f"入力する仕訳: {len(rows)}件（CSV {rows[0].line}行目から {rows[-1].line}行目まで）")

        if warnings:
            print("\n注意:")
            for w in warnings:
                print(f"  ! {w}")

        if args.dry_run:
            for row in rows:
                print(f"\n── {row_summary(row)}")
                for line in plan_lines(cfg["steps"], row.values):
                    print(f"   {line}")
            print("\n（--dry-run のため、キーは送っていません）")
            return 0

        if sys.platform != "win32":
            raise UserError("キーの送信は Windows でのみ動きます（--dry-run は使えます）")
        if not ask_yes("\n入力を始めますか？"):
            return 0

        target_name = "notepad" if args.notepad else "zaimu"
        target = cfg.get("target", {}).get(target_name)
        if not target:
            raise UserError(f"設定ファイルに [target.{target_name}] がありません")
        win = Win()
        sender = Sender(cfg, win)
        ctl = Controller(cfg, target, win)
        ctl.install()
        first = "税区分" if args.tax == "課税" else "借方科目"
        where = "メモ帳" if args.notepad else f"財務エントリの「会計伝票」画面（カーソルは{first}の欄）"
        print(f"\n{where}をクリックしてから、{ctl.resume_label} を押すと入力を始めます。")
        print(f"途中で止めるときは {ctl.pause_label}、再開は {ctl.resume_label} です。")
        write_log(f"開始  {args.csv}  {month_label}  {target_name}  CSV {rows[0].line}行目から")
        try:
            run_rows(rows, cfg, ctl, sender, progress)
        except (KeyboardInterrupt, Cancelled):
            print(f"\n終了しました。記録: CSV {progress.last_completed}行目まで入力済み")
            if progress.in_progress:
                print(f"※ CSV {progress.in_progress}行目は入力途中です。財務エントリの画面で確認してください。")
            write_log(f"中断  {progress.last_completed}行目まで完了")
            return 1
        finally:
            ctl.uninstall()
        print(f"\nすべて入力しました（{len(rows)}件）。")
        write_log(f"終了  {len(rows)}件")
        return 0
    except UserError as e:
        print(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
