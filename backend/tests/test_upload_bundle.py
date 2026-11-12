import io
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image

from services.upload_bundle import (
    EXIF_ORIENTATION,
    PHOTO_PAGE_LONG_SIDE,
    UploadedFile,
    assemble_pdf,
    detect_kind,
)


def _photo(path: Path, size=(300, 400), mode="RGB", fmt="JPEG", orientation: int | None = None) -> Path:
    image = Image.new(mode, size, (200, 200, 200) if mode == "RGB" else (200, 200, 200, 128))
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[EXIF_ORIENTATION] = orientation
        kwargs["exif"] = exif
    image.save(path, fmt, **kwargs)
    return path


def _pdf(path: Path, pages: int) -> Path:
    document = fitz.open()
    for index in range(pages):
        document.new_page().insert_text((72, 72), f"Pagina {index + 1}")
    document.save(path)
    document.close()
    return path


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("processo.PDF", None, "pdf"),
        ("blob", "application/pdf", "pdf"),
        ("folha.jpeg", None, "image"),
        ("IMG_0001.JPG", "", "image"),
        ("print.png", "image/png", "image"),
        ("foto", "image/jpeg; charset=binary", "image"),
        ("notas.txt", "text/plain", None),
        ("foto.heic", "image/heic", None),
    ],
)
def test_detect_kind(filename, content_type, expected):
    assert detect_kind(filename, content_type) == expected


def test_assemble_keeps_upload_order_and_embeds_photos(tmp_path: Path):
    files = [
        UploadedFile(_photo(tmp_path / "a.jpg"), "image"),
        UploadedFile(_pdf(tmp_path / "b.pdf", 2), "pdf"),
        UploadedFile(_photo(tmp_path / "c.png", mode="RGBA", fmt="PNG"), "image"),
    ]
    target = tmp_path / "junto.pdf"
    assemble_pdf(files, target)

    with fitz.open(target) as document:
        assert document.page_count == 4
        assert "Pagina 1" in document[1].get_text()
        for index in (0, 3):
            page = document[index]
            assert len(page.get_images()) == 1
            assert max(page.rect.width, page.rect.height) == pytest.approx(PHOTO_PAGE_LONG_SIDE)
            assert page.rect.height > page.rect.width


def test_assemble_embeds_upright_jpeg_without_recompressing(tmp_path: Path):
    photo = _photo(tmp_path / "a.jpg")
    target = tmp_path / "junto.pdf"
    assemble_pdf([UploadedFile(photo, "image")], target)

    with fitz.open(target) as document:
        xref = document[0].get_images()[0][0]
        assert document.extract_image(xref)["image"] == photo.read_bytes()


def test_assemble_applies_exif_rotation(tmp_path: Path):
    # Foto de celular deitada no arquivo, com a orientação só no EXIF (6 = girar 90°).
    photo = _photo(tmp_path / "deitada.jpg", size=(400, 300), orientation=6)
    target = tmp_path / "junto.pdf"
    assemble_pdf([UploadedFile(photo, "image")], target)

    with fitz.open(target) as document:
        page = document[0]
        assert page.rect.height > page.rect.width
        image = Image.open(io.BytesIO(document.extract_image(page.get_images()[0][0])["image"]))
        assert image.size == (300, 400)


def test_assemble_rejects_unreadable_files(tmp_path: Path):
    fake_photo = tmp_path / "foto.jpg"
    fake_photo.write_bytes(b"nao e imagem")
    with pytest.raises(ValueError, match="INVALID_IMAGE"):
        assemble_pdf([UploadedFile(fake_photo, "image")], tmp_path / "x.pdf")

    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"nao e pdf")
    with pytest.raises(ValueError, match="INVALID_PDF"):
        assemble_pdf([UploadedFile(fake_pdf, "pdf")], tmp_path / "y.pdf")
