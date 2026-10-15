"""Windows のサインイン時に、財務エントリを自動で起動する設定。

以前はスタートアップフォルダーにショートカット (ZaimuEntry-Server.lnk) を置き、
VBScript (start-background.vbs) 経由で start.bat を最小化起動していた。
この方式は次の理由で立ち上がらないことがあったため、やめた。

- 新しい Windows 11 では VBScript が既定で無効になりつつある
- インターネットから入手したファイルは、実行前に警告が出て止まることがある
- 起動に失敗しても、最小化された黒い窓の中にしかメッセージが残らない

今は HKEY_CURRENT_USER の Run キーに、pythonw.exe (窓を出さない Python) で
run.py --background を起動するコマンドを登録する。管理者権限は不要。
起動時のメッセージやエラーは data/logs/server.log に残る。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUN_PY = BASE_DIR / "run.py"
LOG_FILE = BASE_DIR / "data" / "logs" / "server.log"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# タスク マネージャーの「スタートアップ アプリ」で無効にすると、ここに記録される
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = "ZaimuEntry"
LEGACY_LNK = "ZaimuEntry-Server.lnk"


def supported() -> bool:
    return sys.platform == "win32"


def pythonw_path() -> Path:
    """窓を出さずに Python を動かす pythonw.exe。見つからなければ今の Python。"""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def command(open_browser: bool) -> str:
    cmd = f'"{pythonw_path()}" "{RUN_PY}" --background'
    return cmd if open_browser else cmd + " --no-browser"


def legacy_shortcut() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / LEGACY_LNK


def _winreg():
    import winreg  # Windows 以外には無い
    return winreg


def _read(key_path: str):
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            return winreg.QueryValueEx(k, VALUE_NAME)[0]
    except FileNotFoundError:
        return None


def _delete(key_path: str) -> None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
    except FileNotFoundError:
        pass


def _exe_of(cmd: str) -> str:
    """登録コマンドの先頭 (実行ファイル) を取り出す。"""
    cmd = cmd.strip()
    if cmd.startswith('"'):
        return cmd[1:].split('"', 1)[0]
    return cmd.split(" ", 1)[0]


def status() -> dict:
    out = {
        "supported": supported(), "registered": False, "enabled": False, "open_browser": True,
        "path_ok": False, "problem": "", "command": "", "legacy": False, "log_file": str(LOG_FILE),
    }
    if not supported():
        out["problem"] = "自動起動の設定は Windows でのみ使えます"
        return out
    lnk = legacy_shortcut()
    out["legacy"] = bool(lnk and lnk.exists())
    cmd = _read(RUN_KEY)
    if not cmd:
        if out["legacy"]:
            out["problem"] = "以前の方式 (スタートアップのショートカット) で設定されています。設定し直してください"
        return out
    out["registered"] = True
    out["command"] = cmd
    out["open_browser"] = "--no-browser" not in cmd
    approved = _read(APPROVED_KEY)
    # 先頭バイトが奇数 (03 など) なら、タスク マネージャーで「無効」にされている
    disabled = isinstance(approved, (bytes, bytearray)) and len(approved) > 0 and approved[0] & 1
    out["enabled"] = not disabled
    exe = _exe_of(cmd)
    out["path_ok"] = str(RUN_PY) in cmd and Path(exe).exists()
    if disabled:
        out["problem"] = "Windows の「スタートアップ アプリ」で無効にされています。設定し直すと有効に戻ります"
    elif str(RUN_PY) not in cmd:
        out["problem"] = "別のフォルダーの財務エントリが登録されています (フォルダーを移動しましたか？)。設定し直してください"
    elif not Path(exe).exists():
        out["problem"] = f"登録されている Python ({exe}) が見つかりません。設定し直してください"
    return out


def enable(open_browser: bool = True) -> dict:
    """自動起動を登録する (既にあれば上書き)。無効化の記録と以前の方式のショートカットは消す。"""
    if not supported():
        raise RuntimeError("自動起動の設定は Windows でのみ使えます")
    winreg = _winreg()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, command(open_browser))
    _delete(APPROVED_KEY)
    _remove_legacy()
    return status()


def disable() -> dict:
    if not supported():
        raise RuntimeError("自動起動の設定は Windows でのみ使えます")
    _delete(RUN_KEY)
    _delete(APPROVED_KEY)
    _remove_legacy()
    return status()


def _remove_legacy() -> None:
    lnk = legacy_shortcut()
    if lnk and lnk.exists():
        try:
            lnk.unlink()
        except OSError:
            pass


def migrate_legacy() -> bool:
    """以前の方式 (VBScript 経由のショートカット) で登録されていれば、今の方式に切り替える。

    サーバー起動のたびに呼ぶ。切り替えたら True。
    """
    if not supported():
        return False
    lnk = legacy_shortcut()
    if not (lnk and lnk.exists()):
        return False
    try:
        if _read(RUN_KEY):
            _remove_legacy()
        else:
            enable(open_browser=True)
        return True
    except OSError:
        return False
