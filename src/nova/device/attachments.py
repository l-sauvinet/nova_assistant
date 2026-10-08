"""Prepares files the user attaches (photos, PDF, Word, Excel, PowerPoint, text...) so the model can use them.

Runs on the user's machine: pictures are resized to what vision models accept, documents are turned into text,
and scanned PDFs (no text layer) are rendered as page pictures.
"""

import mimetypes
from pathlib import Path

from nova.core.messages import Attachment
from nova.security.exposure import describe_findings
from nova.security.injection import scan

MAX_IMAGE_EDGE = 1568
MAX_TEXT_CHARS = 100_000
MAX_SCANNED_PAGES = 10
MAX_SHEET_ROWS = 500
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
TEXT_PROBE_BYTES = 2_000_000


def prepare_attachment(path: Path, cache_dir: Path | None = None) -> Attachment:
    """`cache_dir` receives derived pictures (resized photo, scanned pages); never the user's own folder."""
    cache_dir = cache_dir or path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return prepare_image(path, media_type, cache_dir)
    extractors = {".docx": extract_docx, ".xlsx": extract_xlsx, ".xlsm": extract_xlsx, ".pptx": extract_pptx}
    try:
        if suffix == ".pdf":
            text, images = extract_pdf(path, cache_dir)
        elif suffix in extractors:
            text, images = extractors[suffix](path)
        else:
            text, images = extract_plain_text(path), []
    except Exception as error:  # a damaged or protected file must not break the conversation
        return Attachment(path=str(path), name=path.name, media_type=media_type, kind="document", note=f"Contenu illisible ({error}).")
    note = ""
    if len(text) > MAX_TEXT_CHARS:
        text, note = text[:MAX_TEXT_CHARS], f"Contenu tronqué aux {MAX_TEXT_CHARS} premiers caractères."
    if not text and not images:
        note = note or "Fichier binaire : contenu non lisible directement, mais son chemin est utilisable par les outils."
    findings = scan(text)
    warning = describe_findings(path.name, findings) if findings else ""
    return Attachment(path=str(path), name=path.name, media_type=media_type, kind="document", text=text, images=images, note=note, warning=warning)


def prepare_image(path: Path, media_type: str, cache_dir: Path) -> Attachment:
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            ready = cache_dir / f"{path.stem}.vision.jpg"
            image.convert("RGB").save(ready, "JPEG", quality=85)
    except OSError as error:
        return Attachment(path=str(path), name=path.name, media_type=media_type, kind="image", note=f"Image illisible ({error}).")
    return Attachment(path=str(path), name=path.name, media_type=media_type, kind="image", images=[str(ready)])


def extract_pdf(path: Path, cache_dir: Path) -> tuple[str, list[str]]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(f"--- Page {number} ---\n{content}" for number, content in enumerate(pages, start=1) if content)
    has_text_layer = sum(len(content) for content in pages) >= 40 * max(1, len(pages))
    if has_text_layer:
        return text, []
    return text, render_pdf_pages(path, cache_dir)


def render_pdf_pages(path: Path, cache_dir: Path) -> list[str]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(path)
    images = []
    for index in range(min(len(document), MAX_SCANNED_PAGES)):
        picture = document[index].render(scale=1.5).to_pil()
        picture.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
        output = cache_dir / f"{path.stem}.page{index + 1}.jpg"
        picture.convert("RGB").save(output, "JPEG", quality=80)
        images.append(str(output))
    return images


def extract_docx(path: Path) -> tuple[str, list[str]]:
    import docx

    document = docx.Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        parts.append("\n".join(" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows))
    return "\n".join(parts), []


def extract_xlsx(path: Path) -> tuple[str, list[str]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    parts = []
    for sheet in workbook.worksheets:
        rows = []
        for row in sheet.iter_rows(values_only=True):
            if len(rows) >= MAX_SHEET_ROWS:
                rows.append(f"... (feuille tronquée à {MAX_SHEET_ROWS} lignes)")
                break
            if any(cell is not None for cell in row):
                rows.append("\t".join("" if cell is None else str(cell) for cell in row))
        parts.append(f"--- Feuille « {sheet.title} » ---\n" + "\n".join(rows))
    workbook.close()
    return "\n\n".join(parts), []


def extract_pptx(path: Path) -> tuple[str, list[str]]:
    from pptx import Presentation

    parts = []
    for number, slide in enumerate(Presentation(path).slides, start=1):
        texts = [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.strip()]
        parts.append(f"--- Diapositive {number} ---\n" + "\n".join(texts))
    return "\n\n".join(parts), []


def extract_plain_text(path: Path) -> str:
    data = path.read_bytes()[:TEXT_PROBE_BYTES]
    if b"\x00" in data[:8000]:
        return ""
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""
