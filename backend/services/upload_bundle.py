"""Junta os arquivos enviados (PDFs e fotos) em um único PDF temporário.

O perito pode enviar o processo inteiro ou só as páginas do cartão de ponto e do holerite,
inclusive como fotos tiradas do papel. Cada foto vira uma página; os PDFs entram com todas
as suas páginas, na ordem do envio. Tudo fica em tempfile e o service apaga no `finally`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageOps, UnidentifiedImageError

PDF_SUFFIXES = (".pdf",)
PDF_TYPES = frozenset({"application/pdf", "application/x-pdf"})
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
IMAGE_TYPES = frozenset({"image/jpeg", "image/jpg", "image/pjpeg", "image/png", "image/webp"})

# Lado maior da página de uma foto, em pontos (altura de uma folha A4). A imagem embutida
# mantém os pixels originais (o OCR local lê a imagem, não a página renderizada); o tamanho
# da página só define a escala da renderização enviada ao Gemini (150 DPI).
PHOTO_PAGE_LONG_SIDE = 842.0
PHOTO_JPEG_QUALITY = 90
# Protege a memória contra imagens gigantes ou malformadas (descompressão).
MAX_IMAGE_PIXELS = 60_000_000
EXIF_ORIENTATION = 0x0112


@dataclass(frozen=True)
class UploadedFile:
    path: Path
    kind: str  # "pdf" | "image"


def detect_kind(filename: str | None, content_type: str | None) -> str | None:
    """Tipo pelo nome ou pelo content-type; None se não for PDF nem foto aceita."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower().split(";")[0].strip()
    if name.endswith(PDF_SUFFIXES) or ctype in PDF_TYPES:
        return "pdf"
    if name.endswith(IMAGE_SUFFIXES) or ctype in IMAGE_TYPES:
        return "image"
    return None


def _photo_bytes(path: Path) -> tuple[bytes, int, int]:
    """Foto pronta para embutir: orientação EXIF aplicada, sem transparência.

    JPEG já em pé é embutido sem recompressão (recomprimir borra a impressão matricial).
    """
    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("INVALID_IMAGE")
            orientation = image.getexif().get(EXIF_ORIENTATION, 1)
            if image.format == "JPEG" and orientation == 1 and image.mode in ("L", "RGB"):
                return path.read_bytes(), image.width, image.height
            upright = ImageOps.exif_transpose(image)
            if upright.mode not in ("L", "RGB"):
                background = Image.new("RGB", upright.size, (255, 255, 255))
                rgba = upright.convert("RGBA")
                background.paste(rgba, mask=rgba.getchannel("A"))
                upright = background
            buffer = io.BytesIO()
            upright.save(buffer, "JPEG", quality=PHOTO_JPEG_QUALITY)
            return buffer.getvalue(), upright.width, upright.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("INVALID_IMAGE") from exc


def _add_photo(document: fitz.Document, path: Path) -> None:
    data, width, height = _photo_bytes(path)
    scale = PHOTO_PAGE_LONG_SIDE / max(width, height, 1)
    page = document.new_page(width=width * scale, height=height * scale)
    page.insert_image(page.rect, stream=data)


def assemble_pdf(files: list[UploadedFile], target: Path) -> None:
    """Grava em `target` um PDF com as páginas de todos os arquivos, na ordem recebida.

    Levanta ValueError("INVALID_PDF") ou ValueError("INVALID_IMAGE") para arquivo ilegível.
    """
    document = fitz.open()
    try:
        for item in files:
            if item.kind == "image":
                _add_photo(document, item.path)
                continue
            try:
                source = fitz.open(item.path, filetype="pdf")
            except Exception as exc:
                raise ValueError("INVALID_PDF") from exc
            try:
                if source.is_encrypted or source.page_count == 0:
                    raise ValueError("INVALID_PDF")
                document.insert_pdf(source)
            finally:
                source.close()
        document.save(target, garbage=1, deflate=True)
    finally:
        document.close()
