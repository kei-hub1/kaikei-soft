"""取り込みファイル (画像 / PDF / DocuWorks) の読み込みのテスト。"""
import io
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import docfiles

pdfium = pytest.importorskip("pypdfium2")
PIL = pytest.importorskip("PIL")
from PIL import Image


PASSBOOK_LINES = [
    "2026-04-01 KA)YAMADA SHOUTEN 330,000 1,530,000",
    "2026-04-05 ATM 50,000 1,480,000",
    "2026-04-10 DENKIDAI 12,800 1,467,200",
]


def make_text_pdf(path: Path, lines=PASSBOOK_LINES):
    """文字情報を持つ PDF (検索可能 PDF 相当) を作る。"""
    def esc(t):
        # PDF の文字列リテラルでは \ ( ) をエスケープする
        return t.replace("\\", r"\\\\").replace("(", r"\(").replace(")", r"\)")
    content = "BT /F1 11 Tf " + " ".join(
        f"1 0 0 1 20 {700 - i * 20} Tm ({esc(l)}) Tj" for i, l in enumerate(lines)) + " ET"
    stream = content.encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj" % i + body + b"endobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer<</Root 1 0 R/Size %d>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def make_image_only_pdf(path: Path):
    """文字情報を持たない (画像だけの) PDF を作る。"""
    img = Image.new("RGB", (600, 400), "white")
    pdf = pdfium.PdfDocument.new()
    bitmap = pdfium.PdfBitmap.from_pil(img)
    pdf_image = pdfium.PdfImage.new(pdf)
    pdf_image.set_bitmap(bitmap)
    page = pdf.new_page(600, 400)
    page.insert_obj(pdf_image)
    page.gen_content()
    pdf.save(str(path))
    return path


def jpeg_bytes(size=(400, 300), quality=80):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 形式の判別
# ---------------------------------------------------------------------------

def test_supported_suffixes_cover_image_pdf_and_xdw():
    assert ".jpg" in docfiles.SUPPORTED_SUFFIXES
    assert ".pdf" in docfiles.SUPPORTED_SUFFIXES
    assert ".xdw" in docfiles.SUPPORTED_SUFFIXES
    assert docfiles.pdf_support() is True


def test_unsupported_suffix_is_rejected(tmp_path):
    f = tmp_path / "a.docx"
    f.write_bytes(b"x")
    with pytest.raises(docfiles.DocumentError) as e:
        docfiles.load(f, tmp_path)
    assert "対応していない形式" in str(e.value)


def test_image_is_passed_through(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(jpeg_bytes())
    doc = docfiles.load(f, tmp_path)
    assert doc.text is None and doc.images == [f]


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def test_searchable_pdf_uses_its_text_layer(tmp_path):
    """文字情報がある PDF は OCR を通さずそのまま読む。"""
    doc = docfiles.load(make_text_pdf(tmp_path / "p.pdf"), tmp_path)
    assert doc.images == []
    assert doc.text is not None
    assert "330,000" in doc.text and "1,530,000" in doc.text
    assert "YAMADA" in doc.text
    assert doc.method == "PDF の文字情報"


def test_searchable_pdf_text_parses_into_rows(tmp_path):
    """PDF の文字情報から、そのまま明細を組み立てられる。"""
    from app.passbook import parse_passbook_text
    doc = docfiles.load(make_text_pdf(tmp_path / "p.pdf"), tmp_path)
    rows = parse_passbook_text(doc.text, 2026, 1_200_000)["rows"]
    assert [r["direction"] for r in rows] == ["in", "out", "out"]
    assert [r["amount"] for r in rows] == [330000, 50000, 12800]
    assert all(not r["issues"] for r in rows)


def test_image_only_pdf_is_rendered_to_images(tmp_path):
    doc = docfiles.load(make_image_only_pdf(tmp_path / "scan.pdf"), tmp_path)
    assert doc.text is None
    assert len(doc.images) == 1 and doc.images[0].exists()
    with Image.open(doc.images[0]) as img:
        assert img.width > 600      # 拡大して描画している
    assert "画像" in doc.method


def test_broken_pdf_reports_clearly(tmp_path):
    f = tmp_path / "broken.pdf"
    f.write_bytes(b"%PDF-1.4 this is not a pdf")
    with pytest.raises(docfiles.DocumentError):
        docfiles.load(f, tmp_path)


# ---------------------------------------------------------------------------
# DocuWorks (.xdw)
# ---------------------------------------------------------------------------

def test_xdw_without_converter_extracts_embedded_images(tmp_path):
    """スキャンした .xdw のように画像が素のまま入っていれば取り出せる。"""
    blob = b"DocuWorks-like header" + b"\x00" * 500 + jpeg_bytes((800, 600)) + b"\x00" * 100 \
        + jpeg_bytes((800, 600)) + b"tail"
    f = tmp_path / "scan.xdw"
    f.write_bytes(blob)
    doc = docfiles.load(f, tmp_path / "work")
    assert doc.text is None
    assert len(doc.images) == 2
    assert all(p.exists() for p in doc.images)
    for p in doc.images:
        with Image.open(p) as img:
            assert img.size == (800, 600)
    assert "DocuWorks" in doc.method and "公開されていない" in doc.note


def test_xdw_with_no_readable_image_gives_guidance(tmp_path):
    f = tmp_path / "compressed.xdw"
    f.write_bytes(b"XDW" + zlib.compress(b"page data" * 5000))
    with pytest.raises(docfiles.DocumentError) as e:
        docfiles.load(f, tmp_path / "work")
    msg = str(e.value)
    assert "PDF" in msg and "書き出して" in msg
    assert "変換コマンド" in msg


def test_xdw_ignores_tiny_embedded_images(tmp_path):
    """アイコンなどの小さな画像は明細ではないので拾わない。"""
    f = tmp_path / "icons.xdw"
    f.write_bytes(b"head" + jpeg_bytes((16, 16)) + jpeg_bytes((24, 24)))
    with pytest.raises(docfiles.DocumentError):
        docfiles.load(f, tmp_path / "work")


def test_xdw_uses_configured_converter(tmp_path):
    """設定された変換コマンドで PDF にしてから読む。"""
    src = tmp_path / "doc.xdw"
    src.write_bytes(b"anything")
    pdf_src = make_text_pdf(tmp_path / "ready.pdf")
    # 入力を無視して用意済みの PDF を出力先へコピーするだけのコマンド
    cmd = f'{sys.executable} -c "import shutil,sys; shutil.copy(r\'{pdf_src}\', sys.argv[1])" "{{output}}" "{{input}}"'
    doc = docfiles.load(src, tmp_path / "work", cmd)
    assert doc.text is not None and "330,000" in doc.text
    assert doc.method.startswith("DocuWorks を変換")


def test_xdw_converter_failure_is_reported(tmp_path):
    src = tmp_path / "doc.xdw"
    src.write_bytes(b"anything")
    cmd = f'{sys.executable} -c "import sys; sys.exit(1)" "{{input}}" "{{output}}"'
    with pytest.raises(docfiles.DocumentError) as e:
        docfiles.load(src, tmp_path / "work", cmd)
    assert "変換に失敗" in str(e.value)


def test_missing_converter_is_reported(tmp_path):
    src = tmp_path / "doc.xdw"
    src.write_bytes(b"anything")
    with pytest.raises(docfiles.DocumentError) as e:
        docfiles.load(src, tmp_path / "work", 'no_such_program_xyz "{input}" "{output}"')
    assert "変換" in str(e.value)


def test_carve_images_validates_content(tmp_path):
    """壊れた JPEG は取り出さない。"""
    broken = b"\xff\xd8\xff" + b"\x00" * 20000 + b"\xff\xd9"
    assert docfiles.carve_images(broken, tmp_path / "w") == []
