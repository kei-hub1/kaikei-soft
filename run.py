"""起動スクリプト:  python run.py  → http://127.0.0.1:8765 をブラウザで開く。

Windows の自動起動 (autostart-on.bat / データ管理画面) からは
pythonw.exe run.py --background で、窓を出さずに起動する。
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# 自動起動 (Run キー) から起動されると、作業フォルダーは C:\Windows\System32 などになる。
# data フォルダー等を正しく見つけるため、常にこのファイルのフォルダーで動かす。
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

from app import autostart  # noqa: E402

# start.bat に「すでに起動している」ことを伝える終了コード (このときは pause しない)
EXIT_ALREADY_RUNNING = 3


def is_running(host: str, port: int) -> bool:
    """すでに同じポートでサーバーが動いているかを調べる。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def log_to_file() -> None:
    """窓が無い (pythonw) ときの出力先を data/logs/server.log にする。大きくなったら作り直す。"""
    log = autostart.LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > 1_000_000:
        log.replace(log.with_suffix(".old.log"))
    f = open(log, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f
    print(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} 起動 ({' '.join(sys.argv[1:])}) ====")


def start_background(open_browser: bool = False, port: int = 8765) -> None:
    """サーバーを窓なしで別プロセスとして起動して、すぐ戻る。"""
    args = [str(autostart.pythonw_path()), str(BASE_DIR / "run.py"), "--background", "--port", str(port)]
    if not open_browser:
        args.append("--no-browser")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, cwd=str(BASE_DIR), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_server(host: str, port: int) -> bool:
    """動いているサーバーに終了を頼み、止まるまで待つ。止まった (動いていなかった) ら True。"""
    if not is_running(host, port):
        return True
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/system/shutdown", data=b"", method="POST",
                                     headers={"X-Kaikei-Local": "1"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:  # 古い版のサーバーには終了の API が無い
        print(f"終了を依頼できませんでした: {e}")
        return False
    for _ in range(50):
        if not is_running(host, port):
            return True
        time.sleep(0.2)
    return False


def autostart_command(args) -> int:
    """autostart-on.bat / autostart-off.bat から呼ばれる設定操作。"""
    try:
        if args.autostart_on:
            st = autostart.enable(open_browser=not args.no_browser)
            print("自動起動を設定しました。" + ("サインイン時にブラウザで画面も開きます。" if st["open_browser"]
                                                else "サインイン時はサーバーだけを起動します。"))
            print(f"  登録内容: {st['command']}")
            if not is_running(args.host, args.port):
                start_background(open_browser=False, port=args.port)
        elif args.autostart_off:
            autostart.disable()
            print("自動起動の設定を解除しました。")
        else:
            st = autostart.status()
            print(st)
    except Exception as e:
        print(f"設定に失敗しました: {e}")
        return 1
    if args.stop and not stop_server(args.host, args.port):
        print("動いている財務エントリを止められませんでした。")
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="財務エントリ (kaikei-soft) を起動します")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    p.add_argument("--reload", action="store_true", help="開発用: ソース変更時に自動再起動")
    p.add_argument("--background", action="store_true", help="窓なしで動かす (出力は data/logs/server.log)")
    p.add_argument("--start-background", action="store_true", help="窓なしのサーバーを別に起動してすぐ戻る")
    p.add_argument("--stop", action="store_true", help="動いているサーバーを止める")
    p.add_argument("--autostart-on", action="store_true", help="Windows のサインイン時に自動で起動する")
    p.add_argument("--autostart-off", action="store_true", help="自動起動をやめる")
    p.add_argument("--autostart-status", action="store_true", help="自動起動の設定を表示する")
    args = p.parse_args()

    if args.autostart_on or args.autostart_off or args.autostart_status:
        sys.exit(autostart_command(args))
    if args.start_background:
        if not is_running(args.host, args.port):
            start_background(open_browser=not args.no_browser, port=args.port)
        return
    if args.stop:
        sys.exit(0 if stop_server(args.host, args.port) else 1)

    if args.background or sys.stdout is None:
        log_to_file()

    # 自動起動 (start-background.vbs) からは引数が渡らない環境もあるため、
    # 環境変数でもブラウザ抑止を指定できるようにしておく。
    no_browser = args.no_browser or os.environ.get("KAIKEI_NO_BROWSER") == "1"
    url = f"http://{args.host}:{args.port}/"

    # 以前の方式の自動起動 (VBScript 経由) が残っていれば、今の方式に切り替える
    if autostart.migrate_legacy():
        print("自動起動の設定を新しい方式に切り替えました。")

    # 二重起動の場合はエラーにせず、動いている方をブラウザで開く。
    if is_running(args.host, args.port):
        print(f"財務エントリ はすでに起動しています: {url}")
        if not no_browser:
            webbrowser.open(url)
        sys.exit(EXIT_ALREADY_RUNNING)

    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"財務エントリ を起動しました: {url}  (終了は Ctrl+C)")
    try:
        import uvicorn
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="warning")
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
