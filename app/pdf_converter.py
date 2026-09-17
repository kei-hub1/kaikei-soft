"""Word ファイルを PDF に変換する。

優先順位:
  1. Microsoft Word（pywin32 の COM 操作。Windows のみ）
  2. LibreOffice（インストールされていれば。Word がない PC やテスト環境向け）
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .logger import get_logger

log = get_logger("pdf")

WD_EXPORT_FORMAT_PDF = 17


class PdfConversionError(Exception):
    """PDF 変換に失敗した（Word ファイル自体は作成済み）。"""


def convert_docx_to_pdf(docx_path: Path, pdf_path: Path) -> str:
    """docx を pdf に変換し、使用した変換方法の名前を返す。失敗時は PdfConversionError。"""
    docx_path = Path(docx_path).resolve()
    pdf_path = Path(pdf_path).resolve()
    errors: list[str] = []

    if sys.platform == "win32":
        try:
            _convert_with_word(docx_path, pdf_path)
            return "Microsoft Word"
        except Exception as e:  # noqa: BLE001 - 次の手段に進む
            log.warning("Word による PDF 変換に失敗: %s", e)
            errors.append(f"Word: {e}")

    soffice = find_libreoffice()
    if soffice:
        try:
            _convert_with_libreoffice(soffice, docx_path, pdf_path)
            return "LibreOffice"
        except Exception as e:  # noqa: BLE001
            log.warning("LibreOffice による PDF 変換に失敗: %s", e)
            errors.append(f"LibreOffice: {e}")
    elif sys.platform != "win32":
        errors.append("LibreOffice が見つかりません。")

    if not errors:
        errors.append("利用できる変換手段（Microsoft Word / LibreOffice）が見つかりません。")
    raise PdfConversionError("\n".join(errors))


# ---- Microsoft Word（COM） --------------------------------------------------


def _convert_with_word(docx_path: Path, pdf_path: Path) -> None:
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError as e:
        raise PdfConversionError(
            "pywin32 がインストールされていません。「初回セットアップ.bat」を実行してください。"
        ) from e

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(
            str(docx_path), ReadOnly=True, AddToRecentFiles=False, Visible=False
        )
        doc.ExportAsFixedFormat(str(pdf_path), WD_EXPORT_FORMAT_PDF)
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        finally:
            try:
                if word is not None:
                    word.Quit()
            finally:
                pythoncom.CoUninitialize()

    if not pdf_path.exists():
        raise PdfConversionError("PDF ファイルが作成されませんでした。")


# ---- LibreOffice ---------------------------------------------------------


def find_libreoffice() -> str | None:
    """LibreOffice の実行ファイルを探す。見つからなければ None。"""
    for name in ("soffice", "libreoffice", "soffice.exe"):
        path = shutil.which(name)
        if path:
            return path
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return None


def _convert_with_libreoffice(soffice: str, docx_path: Path, pdf_path: Path) -> None:
    # 一時フォルダに出力してから目的の名前に移す（同名ファイルとの衝突を避ける）
    with tempfile.TemporaryDirectory(prefix="kaikei_pdf_") as tmp:
        cmd = [
            soffice,
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            tmp,
            str(docx_path),
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        produced = Path(tmp) / (docx_path.stem + ".pdf")
        if proc.returncode != 0 or not produced.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise PdfConversionError(f"変換コマンドが失敗しました。{detail}")
        shutil.move(str(produced), str(pdf_path))
