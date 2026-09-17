"""文書作成の流れをまとめる（入力チェック → Word 保存 → PDF 変換）。"""

from __future__ import annotations

import errno
from pathlib import Path

from . import docx_builder, filenames
from .logger import get_logger
from .models import DocumentRequest, DocumentResult
from .pdf_converter import PdfConversionError, convert_docx_to_pdf
from .placeholders import PlaceholderContext, render

log = get_logger("service")


class ValidationError(Exception):
    """利用者の入力不備。メッセージをそのまま画面に表示する。"""


class FileLockedError(Exception):
    """出力先のファイルが開かれているなどの理由で保存できない。"""


def validate(req: DocumentRequest) -> None:
    """必須項目のチェック。問題があれば ValidationError。"""
    problems: list[str] = []
    if not req.customer or not req.customer.display_name:
        problems.append("宛先を選択してください。")
    if not req.subject.strip():
        problems.append("件名を入力してください。")
    if not req.body.strip():
        problems.append("本文を入力してください。")
    if req.has_notes and not req.active_enclosures():
        problems.append("記書きありの場合は、書類を1件以上入力してください。")
    if problems:
        raise ValidationError("\n".join(problems))


def create_document(req: DocumentRequest, output_dir: Path) -> DocumentResult:
    """Word と PDF を出力する。PDF に失敗しても Word は残し、結果に理由を入れる。"""
    validate(req)

    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FileLockedError(f"出力先フォルダを作成できません。\n{output_dir}\n{e}") from e

    ctx = PlaceholderContext(customer=req.customer, sender=req.sender, created_on=req.created_on)
    subject_for_name = render(req.subject, ctx)
    stem = filenames.build_stem(req.created_on, req.customer.display_name, subject_for_name)
    stem = filenames.unique_stem(output_dir, stem)
    docx_path = output_dir / f"{stem}.docx"
    pdf_path = output_dir / f"{stem}.pdf"

    try:
        docx_builder.save_document(req, docx_path)
    except PermissionError as e:
        log.exception("Word ファイルの保存に失敗: %s", docx_path)
        raise FileLockedError(_locked_message(docx_path)) from e
    except OSError as e:
        log.exception("Word ファイルの保存に失敗: %s", docx_path)
        if e.errno in (errno.EACCES, errno.EBUSY):
            raise FileLockedError(_locked_message(docx_path)) from e
        raise
    log.info("Word 出力: %s", docx_path)

    result = DocumentResult(docx_path=docx_path)
    try:
        result.pdf_method = convert_docx_to_pdf(docx_path, pdf_path)
        result.pdf_path = pdf_path
        log.info("PDF 出力 (%s): %s", result.pdf_method, pdf_path)
    except PdfConversionError as e:
        result.pdf_error = str(e)
        log.error("PDF 変換に失敗: %s", e)
    except Exception as e:  # noqa: BLE001 - PDF 失敗でも Word は残す
        result.pdf_error = f"{type(e).__name__}: {e}"
        log.exception("PDF 変換中に予期しないエラー")
    return result


def _locked_message(path: Path) -> str:
    return (
        "ファイルを保存できませんでした。\n"
        f"{path}\n\n"
        "同じ名前のファイルを Word で開いたままになっていないか確認し、"
        "閉じてからもう一度「作成」を押してください。"
    )
