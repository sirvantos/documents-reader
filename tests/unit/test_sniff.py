import io
import zipfile
from pathlib import Path

import pytest

from docreader.sniff import SniffResult, sniff
from tests.synthetic import make_pdfs

REASONS = {
    "hidden": "скрытый или служебный файл",
    "empty": "пустой файл",
    "word": "формат не поддерживается: документ Word — сохраните его в PDF",
    "image": "формат не поддерживается: изображение — сохраните документ в PDF",
    "unsupported": "формат не поддерживается",
}


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buf.getvalue()


def _assert_rejected(result: SniffResult, code: str) -> None:
    assert result.kind == "rejected"
    assert result.reason_code == code
    assert result.reason == REASONS[code]


def _assert_pdf(result: SniffResult) -> None:
    assert result.kind == "pdf"
    assert result.reason_code is None
    assert result.reason is None


def test_hidden_ds_store(tmp_path):
    _assert_rejected(sniff(_write(tmp_path / ".DS_Store", b"\x00\x00\x00\x01Bud1")), "hidden")


def test_hidden_name_wins_over_real_pdf(tmp_path):
    path = make_pdfs.make_digital(tmp_path / ".hidden.pdf", pages=1)
    _assert_rejected(sniff(path), "hidden")


def test_empty_file(tmp_path):
    path = make_pdfs.make_empty(tmp_path / "empty.pdf")
    assert path.stat().st_size == 0
    _assert_rejected(sniff(path), "empty")


def test_pdf_at_offset_zero(tmp_path):
    _assert_pdf(sniff(make_pdfs.make_digital(tmp_path / "a.pdf", pages=1)))


def test_pdf_with_junk_before_header(tmp_path):
    data = b"J" * 500 + b"%PDF-1.4\n" + b"rest"
    _assert_pdf(sniff(_write(tmp_path / "junk.pdf", data)))


def test_pdf_header_after_1024_bytes_is_unsupported(tmp_path):
    data = b"J" * 1100 + b"%PDF-1.4\n"
    _assert_rejected(sniff(_write(tmp_path / "late.pdf", data)), "unsupported")


def test_doc_header(tmp_path):
    _assert_rejected(sniff(make_pdfs.make_fake_doc(tmp_path / "a.doc")), "word")


def test_docx_zip_with_word_dir(tmp_path):
    _assert_rejected(sniff(make_pdfs.make_fake_docx(tmp_path / "a.docx")), "word")


def test_docx_detected_by_content_with_other_name(tmp_path):
    _assert_rejected(sniff(make_pdfs.make_fake_docx(tmp_path / "a.bin")), "word")


def test_zip_without_word_and_other_name_is_unsupported(tmp_path):
    path = _write(tmp_path / "x.zip", _zip({"a.txt": b"hello"}))
    _assert_rejected(sniff(path), "unsupported")


def test_zip_named_docx_without_word_dir_is_word(tmp_path):
    path = _write(tmp_path / "x.docx", _zip({"a.txt": b"hello"}))
    _assert_rejected(sniff(path), "word")


def test_jpeg(tmp_path):
    _assert_rejected(sniff(make_pdfs.make_jpeg(tmp_path / "a.jpg")), "image")


def test_jpeg_header_bytes(tmp_path):
    _assert_rejected(sniff(_write(tmp_path / "b.jpg", b"\xff\xd8\xff\xe0" + bytes(32))), "image")


def test_png(tmp_path):
    _assert_rejected(sniff(make_pdfs.make_png(tmp_path / "a.png")), "image")


def test_png_header_bytes(tmp_path):
    _assert_rejected(sniff(_write(tmp_path / "b.png", b"\x89PNG\r\n\x1a\n" + bytes(32))), "image")


@pytest.mark.parametrize("header", [b"II*\x00", b"MM\x00*"], ids=["tiff-le", "tiff-be"])
def test_tiff(tmp_path, header):
    _assert_rejected(sniff(_write(tmp_path / "a.tif", header + bytes(32))), "image")


def test_plain_text_is_unsupported(tmp_path):
    _assert_rejected(sniff(make_pdfs.make_unknown(tmp_path / "a.txt")), "unsupported")
