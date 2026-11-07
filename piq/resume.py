"""Resume file -> plain text. PDF, DOCX and TXT only; no OCR.

Hardened against hostile uploads: at most RESUME_MAX_BYTES; the file must be what its name
says (a PDF starts with %PDF-, a DOCX is a zip, a TXT holds no binary such as a renamed
executable); a DOCX may unpack to RESUME_MAX_DOCX_UNZIPPED at most (zip bomb); a PDF is read
page by page until RESUME_MAX_PDF_PAGES pages or RESUME_MAX_TEXT_CHARS characters (so a
decompression bomb stops early); a damaged file is a readable message, never a traceback."""

import zipfile
from io import BytesIO
from pathlib import PurePath

from piq.config import (
    RESUME_MAX_BYTES,
    RESUME_MAX_DOCX_UNZIPPED,
    RESUME_MAX_PDF_PAGES,
    RESUME_MAX_TEXT_CHARS,
)

MAX_BYTES = RESUME_MAX_BYTES
SUPPORTED = (".pdf", ".docx", ".txt")
# An encrypted Word file (and an old .doc) is an OLE compound document, not a zip.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PDF_MAGIC = b"%PDF-"  # the spec allows a little junk first: searched in the first 1 KB
_ZIP_MAGIC = b"PK\x03\x04"
_BINARY_MAGIC = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")  # exe, ELF, Mach-O


class ResumeError(ValueError):
    pass


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        try:  # a file locked only against editing opens with an empty password
            unlocked = reader.decrypt("")
        except Exception:  # e.g. AES without its optional crypto library: still locked
            unlocked = 0
        if not unlocked:
            raise ResumeError(
                "This PDF is password-protected. Save a copy without the password, or upload "
                "a DOCX or TXT."
            )
    parts, size = [], 0
    for page in reader.pages[:RESUME_MAX_PDF_PAGES]:
        text = page.extract_text() or ""
        parts.append(text[: RESUME_MAX_TEXT_CHARS - size])
        size += len(text)
        if size >= RESUME_MAX_TEXT_CHARS:  # far beyond any resume: stop unpacking streams
            break
    return "\n".join(parts)


def _docx_text(data: bytes) -> str:
    if data.startswith(_OLE_MAGIC):
        raise ResumeError(
            "This file is password-protected or in the old .doc format. Save it as an "
            "unprotected DOCX, or upload a PDF or TXT."
        )
    with zipfile.ZipFile(BytesIO(data)) as z:  # the declared sizes bound what is unpacked
        unpacked = sum(i.file_size for i in z.infolist())
    if unpacked > RESUME_MAX_DOCX_UNZIPPED:
        mb = RESUME_MAX_DOCX_UNZIPPED // (1024 * 1024)
        raise ResumeError(
            f"This DOCX unpacks to more than {mb} MB, too much for a resume. Save it without "
            "large images, or upload a PDF or TXT."
        )
    from docx import Document

    doc = Document(BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    parts += [c.text for t in doc.tables for row in t.rows for c in row.cells]
    return "\n".join(parts)


def _check_kind(ext: str, data: bytes) -> None:
    """The bytes must be the type the name claims, before any parser sees them."""
    if ext == ".pdf" and _PDF_MAGIC not in data[:1024]:
        raise ResumeError("This file is not a real PDF. Export the resume as PDF again.")
    if ext == ".docx" and not (data.startswith(_ZIP_MAGIC) or data.startswith(_OLE_MAGIC)):
        raise ResumeError("This file is not a real DOCX. Save the resume as DOCX again.")
    if ext == ".txt" and (data.startswith(_BINARY_MAGIC) or b"\x00" in data[:8192]):
        raise ResumeError("This file is not plain text. Upload a TXT, PDF or DOCX resume.")


def _parse(ext: str, data: bytes) -> str:
    if ext == ".pdf":
        return _pdf_text(data)
    if ext == ".docx":
        return _docx_text(data)
    return data.decode("utf-8", errors="replace")[:RESUME_MAX_TEXT_CHARS]


def extract_text(filename: str, data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ResumeError("Resume is larger than 5 MB.")
    ext = PurePath(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise ResumeError(f"Unsupported file type {ext!r}; upload PDF, DOCX or TXT.")
    _check_kind(ext, data)
    try:
        text = _parse(ext, data)
    except ResumeError:
        raise
    except Exception as e:  # parsers raise many types on damaged files; never show a traceback
        kind = ext.lstrip(".").upper()
        raise ResumeError(
            f"Could not open this {kind} file; it looks damaged. Export it again or upload a TXT."
        ) from e
    text = "\n".join(ln.rstrip() for ln in text.splitlines() if ln.strip())
    if len(text) < 50:
        raise ResumeError("Could not read text from the resume (scanned PDFs are not supported).")
    return text
