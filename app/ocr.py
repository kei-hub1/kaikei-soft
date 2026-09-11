"""画像から文字を読み取る (OCR)。

このソフトはローカルで完結させる方針なので、外部サービスには送らない。
使えるエンジンを自動で選ぶ:

  windows   Windows 10/11 に内蔵の OCR (Windows.Media.Ocr)。追加インストール不要。
            日本語を読むには「言語と地域」で日本語の言語機能が入っていること。
  tesseract Tesseract OCR が PATH にある場合。日本語データ (jpn) が必要。

どちらも無い場合は、画面で通帳のテキストを貼り付けて取り込める。
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PS_SCRIPT = BASE_DIR / "scripts" / "ocr_windows.ps1"

# subprocess のタイムアウト (秒)
TIMEOUT = 120


def _powershell() -> str | None:
    for exe in ("powershell.exe", "pwsh.exe", "powershell", "pwsh"):
        path = shutil.which(exe)
        if path:
            return path
    return None


def available_engines() -> list[dict]:
    """この環境で使える OCR エンジンの一覧。先頭が既定。"""
    engines: list[dict] = []
    if platform.system() == "Windows" and _powershell() and PS_SCRIPT.exists():
        engines.append({
            "code": "windows", "name": "Windows 内蔵 OCR",
            "note": "追加のインストールは不要です。日本語の言語機能が必要です。",
        })
    if shutil.which("tesseract"):
        engines.append({
            "code": "tesseract", "name": "Tesseract OCR",
            "note": "日本語データ (jpn) が入っている必要があります。",
        })
    return engines


def default_engine() -> str | None:
    e = available_engines()
    return e[0]["code"] if e else None


class OcrError(RuntimeError):
    pass


def run_ocr(image_path: str | os.PathLike, engine: str | None = None) -> str:
    """画像から文字を読み取って返す。読めなければ OcrError。"""
    path = Path(image_path)
    if not path.exists():
        raise OcrError(f"画像が見つかりません: {path}")
    engine = engine or default_engine()
    if engine is None:
        raise OcrError(
            "この環境では画像から文字を読み取れません。"
            "通帳のテキストを貼り付けて取り込んでください。")
    if engine == "windows":
        return _run_windows(path)
    if engine == "tesseract":
        return _run_tesseract(path)
    raise OcrError(f"未対応の OCR エンジンです: {engine}")


def _run_windows(path: Path) -> str:
    ps = _powershell()
    if not ps or not PS_SCRIPT.exists():
        raise OcrError("Windows の OCR を実行できません (PowerShell が見つかりません)")
    # 日本語を含む結果はコンソールの文字コードで化けるため、UTF-8 のファイルに書かせる
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ocr.txt"
        proc = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS_SCRIPT),
             "-ImagePath", str(path.resolve()), "-OutPath", str(out)],
            capture_output=True, timeout=TIMEOUT,
        )
        if proc.returncode != 0 or not out.exists():
            msg = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
            raise OcrError(f"Windows の OCR に失敗しました: {msg[:500]}")
        return out.read_text(encoding="utf-8")


def _run_tesseract(path: Path) -> str:
    langs = _tesseract_langs()
    lang = "jpn" if "jpn" in langs else None
    if lang is None:
        raise OcrError("Tesseract に日本語データ (jpn) が入っていません")
    proc = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", lang, "--psm", "6"],
        capture_output=True, timeout=TIMEOUT,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise OcrError(f"Tesseract の実行に失敗しました: {msg[:500]}")
    return proc.stdout.decode("utf-8", "replace")


def _tesseract_langs() -> set[str]:
    try:
        proc = subprocess.run(["tesseract", "--list-langs"], capture_output=True, timeout=30)
        return set(proc.stdout.decode("utf-8", "replace").split())
    except Exception:
        return set()
