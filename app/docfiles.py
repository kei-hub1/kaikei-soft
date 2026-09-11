"""取り込んだファイルから、文字またはページ画像を取り出す。

対応:
  画像 (.jpg .png ...)  そのまま OCR にかける
  PDF                   文字情報があればそれを使う (OCR より正確)。
                        無ければページを画像にして OCR にかける
  DocuWorks (.xdw)      公開仕様が無いため、次の順に試す
                        1. 設定された変換コマンド (DocuWorks の変換ツールなど)
                        2. ファイル内に埋め込まれた画像の取り出し (スキャン文書向けの簡易処理)
                        いずれも駄目なら、DocuWorks で PDF に書き出すよう案内する

PDF の読み取りには pypdfium2 と Pillow を使う。入っていない場合でも
画像ファイルの取り込みは動くよう、読み込みは任意扱いにしている。
"""
from __future__ import annotations

import os
import platform
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
PDF_SUFFIXES = {".pdf"}
XDW_SUFFIXES = {".xdw", ".xbd"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES | XDW_SUFFIXES

# PDF のページを画像にするときの倍率 (文字が小さい通帳でも読めるように大きめ)
RENDER_SCALE = 3.0
MAX_PAGES = 50
CONVERT_TIMEOUT = 180

# DocuWorks が入っていそうな場所 (存在の確認だけに使う)
DOCUWORKS_DIRS = (
    r"C:\Program Files\FUJIFILM\DocuWorks",
    r"C:\Program Files (x86)\FUJIFILM\DocuWorks",
    r"C:\Program Files\Fuji Xerox\DocuWorks",
    r"C:\Program Files (x86)\Fuji Xerox\DocuWorks",
)


class DocumentError(RuntimeError):
    pass


@dataclass
class LoadedDocument:
    """取り込んだファイルの中身。text があれば OCR は不要。"""
    text: str | None = None
    images: list[Path] = field(default_factory=list)
    method: str = ""          # 画面に出す処理方法
    note: str = ""


def pdf_support() -> bool:
    try:
        import pypdfium2  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def docuworks_installed() -> bool:
    return any(Path(d).is_dir() for d in DOCUWORKS_DIRS)


def supported_note() -> dict:
    """画面に出す、対応形式と前提の説明。"""
    return {
        "images": sorted(IMAGE_SUFFIXES),
        "pdf": pdf_support(),
        "xdw": True,
        "docuworks_installed": platform.system() == "Windows" and docuworks_installed(),
    }


def load(path: str | os.PathLike, workdir: Path, xdw_command: str = "") -> LoadedDocument:
    """ファイルを読み込み、文字またはページ画像を返す。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return LoadedDocument(images=[p], method="画像")
    if suffix in PDF_SUFFIXES:
        return _load_pdf(p, workdir)
    if suffix in XDW_SUFFIXES:
        return _load_xdw(p, workdir, xdw_command)
    raise DocumentError(
        f"対応していない形式です ({suffix})。"
        f"画像 ({', '.join(sorted(IMAGE_SUFFIXES))})、PDF、DocuWorks (.xdw) を選んでください。")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _load_pdf(p: Path, workdir: Path) -> LoadedDocument:
    if not pdf_support():
        raise DocumentError(
            "PDF を読み込むための部品が入っていません。"
            "start.bat を実行し直すか、コマンドプロンプトで "
            "「py -3 -m pip install pypdfium2 pillow」を実行してください。")
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(str(p))
    except Exception as e:
        raise DocumentError(f"PDF を開けませんでした: {e}")

    pages = min(len(doc), MAX_PAGES)
    if pages == 0:
        raise DocumentError("PDF にページがありません")

    # 1. 文字情報 (検索可能 PDF) があればそれを使う。OCR より確実。
    texts = []
    for i in range(pages):
        try:
            texts.append(doc[i].get_textpage().get_text_bounded() or "")
        except Exception:
            texts.append("")
    text = "\n".join(texts).strip()
    if _looks_like_real_text(text):
        note = ""
        if len(doc) > pages:
            note = f"{len(doc)} ページのうち先頭 {pages} ページを読み込みました。"
        return LoadedDocument(text=text, method="PDF の文字情報", note=note)

    # 2. 文字情報が無い (画像だけの PDF) ならページを画像にして OCR にかける
    images = []
    for i in range(pages):
        img_path = workdir / f"page_{i + 1:03d}.png"
        try:
            doc[i].render(scale=RENDER_SCALE).to_pil().save(img_path)
        except Exception as e:
            raise DocumentError(f"PDF のページを画像にできませんでした: {e}")
        images.append(img_path)
    note = f"{len(doc)} ページのうち先頭 {pages} ページを読み込みました。" if len(doc) > pages else ""
    return LoadedDocument(images=images, method="PDF のページを画像にして読み取り", note=note)


def _looks_like_real_text(text: str) -> bool:
    """検索可能 PDF かどうかの判定。数字と文字がある程度含まれていれば本物とみなす。"""
    if len(text) < 20:
        return False
    return bool(re.search(r"\d", text))


# ---------------------------------------------------------------------------
# DocuWorks (.xdw)
# ---------------------------------------------------------------------------

def _load_xdw(p: Path, workdir: Path, xdw_command: str) -> LoadedDocument:
    # 1. 設定された変換コマンドを使う
    if xdw_command.strip():
        out = _run_xdw_command(p, workdir, xdw_command)
        loaded = load(out, workdir / "converted")
        loaded.method = f"DocuWorks を変換 → {loaded.method}"
        return loaded

    # 2. 埋め込まれた画像を取り出す (スキャンした .xdw で有効なことがある)
    images = carve_images(p.read_bytes(), workdir)
    if images:
        return LoadedDocument(
            images=images, method="DocuWorks から画像を取り出して読み取り",
            note=f"{len(images)} 枚の画像を取り出しました。DocuWorks の仕様は公開されていないため、"
                 "取り出せない場合や順序が入れ替わる場合があります。"
                 "正しく読めないときは、DocuWorks で PDF に書き出してから取り込んでください。")

    raise DocumentError(
        "DocuWorks 形式 (.xdw) を読み取れませんでした。次のいずれかをお試しください。\n"
        "(1) DocuWorks Desk でファイルを開き、PDF または JPEG に書き出してから取り込む\n"
        "(2) 「データ管理」画面で DocuWorks の変換コマンドを設定する"
        + ("" if docuworks_installed() else "\n※ このパソコンには DocuWorks が見つかりませんでした。"))


def _run_xdw_command(p: Path, workdir: Path, template: str) -> Path:
    """設定された変換コマンドを実行し、できたファイルを返す。

    テンプレートには {input} と {output} を入れておく。
    例: "C:\\Tools\\xdw2pdf.exe" "{input}" "{output}"
    """
    out_dir = workdir / "converted"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (p.stem + ".pdf")
    cmd = template.replace("{input}", str(p)).replace("{output}", str(out))
    try:
        args = cmd if os.name == "nt" else shlex.split(cmd)
        proc = subprocess.run(args, shell=(os.name == "nt"), capture_output=True, timeout=CONVERT_TIMEOUT)
    except FileNotFoundError:
        raise DocumentError("設定された DocuWorks の変換コマンドが見つかりません。「データ管理」画面で確認してください。")
    except subprocess.TimeoutExpired:
        raise DocumentError("DocuWorks の変換に時間がかかりすぎました。")
    produced = [f for f in sorted(out_dir.iterdir()) if f.is_file()] if out_dir.is_dir() else []
    if not produced:
        msg = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        raise DocumentError(f"DocuWorks の変換に失敗しました。{msg[:300]}")
    return out if out.exists() else produced[0]


# 画像の先頭・末尾の並び (JPEG / PNG)
_JPEG_START, _JPEG_END = b"\xff\xd8\xff", b"\xff\xd9"
_PNG_START, _PNG_END = b"\x89PNG\r\n\x1a\n", b"IEND\xaeB`\x82"
MIN_CARVED_BYTES = 8 * 1024


def carve_images(data: bytes, workdir: Path, min_bytes: int = MIN_CARVED_BYTES) -> list[Path]:
    """バイト列に埋め込まれた JPEG / PNG を取り出す。

    DocuWorks の仕様は公開されていないため、スキャン画像がそのまま入っている
    場合にだけ効く簡易的な処理。取り出したものは実際に画像として開けるか確かめる。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    found: list[Path] = []
    for start_sig, end_sig, ext in ((_JPEG_START, _JPEG_END, ".jpg"), (_PNG_START, _PNG_END, ".png")):
        pos = 0
        while len(found) < MAX_PAGES:
            s = data.find(start_sig, pos)
            if s < 0:
                break
            e = data.find(end_sig, s + len(start_sig))
            if e < 0:
                break
            e += len(end_sig)
            blob = data[s:e]
            pos = e
            if len(blob) < min_bytes:
                continue
            out = workdir / f"embedded_{len(found) + 1:03d}{ext}"
            out.write_bytes(blob)
            if _is_readable_image(out):
                found.append(out)
            else:
                out.unlink(missing_ok=True)
    return found


def _is_readable_image(path: Path) -> bool:
    try:
        from PIL import Image
    except Exception:
        # Pillow が無い場合は確認できないので、そのまま通す
        return True
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False
