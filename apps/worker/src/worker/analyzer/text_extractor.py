from __future__ import annotations

import os
import subprocess
import tempfile
import io
import stat
import threading
import zipfile
from pathlib import PurePosixPath
from itertools import islice
from loguru import logger
from worker.resource_limits import positive_int_env


OCR_MAX_PAGES = positive_int_env("WORKER_OCR_MAX_PAGES", 12)
PDF_TEXT_MAX_PAGES = positive_int_env("WORKER_PDF_TEXT_MAX_PAGES", 100)
EXTRACTED_TEXT_MAX_CHARS = positive_int_env("WORKER_EXTRACTED_TEXT_MAX_CHARS", 120_000)

ARCHIVE_MAX_MEMBERS = positive_int_env("WORKER_ARCHIVE_MAX_MEMBERS", 100)
ARCHIVE_MAX_BYTES = positive_int_env("WORKER_ARCHIVE_MAX_BYTES", 50 * 1024 * 1024)
SPREADSHEET_MAX_ROWS = positive_int_env("WORKER_SPREADSHEET_MAX_ROWS", 10_000)
SPREADSHEET_MAX_COLUMNS = positive_int_env("WORKER_SPREADSHEET_MAX_COLUMNS", 256)


def _join_bounded(parts, separator="\n") -> str:
    result = []
    remaining = EXTRACTED_TEXT_MAX_CHARS
    for part in parts:
        if result:
            sep = separator[:remaining]
            result.append(sep)
            remaining -= len(sep)
        result.append(part[:remaining])
        remaining -= min(len(part), remaining)
        if remaining <= 0:
            break
    return "".join(result)


def _validate_members(members, *, rar=False):
    if len(members) > ARCHIVE_MAX_MEMBERS:
        raise ValueError("archive member count exceeds limit")
    total = 0
    for member in members:
        name = member.filename
        path = PurePosixPath(name.replace("\\", "/"))
        if not name or path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
            raise ValueError("unsafe archive member path")
        if rar:
            # RAR5 redirection includes symlinks and hardlinks. Fail closed for
            # rarfile versions that cannot expose this metadata.
            if not hasattr(member, "is_symlink") or member.is_symlink() or getattr(member, "file_redir", None):
                raise ValueError("unsupported archive link metadata")
        else:
            kind = stat.S_IFMT(member.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("archive member is not a regular file")
        if member.file_size < 0:
            raise ValueError("invalid archive member size")
        total += member.file_size
        if total > ARCHIVE_MAX_BYTES:
            raise ValueError("archive expanded size exceeds limit")


def _validate_office_zip(file_path):
    # Office parsers expand ZIP packages internally, before text collection.
    with zipfile.ZipFile(file_path) as archive:
        _validate_members(archive.infolist())


def _bounded_text(text: str) -> str:
    if len(text) <= EXTRACTED_TEXT_MAX_CHARS:
        return text
    logger.warning(
        "Extracted text exceeded {} characters and was truncated",
        EXTRACTED_TEXT_MAX_CHARS,
    )
    return text[:EXTRACTED_TEXT_MAX_CHARS]

def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text_parts = []
        remaining = EXTRACTED_TEXT_MAX_CHARS
        for i, page in enumerate(reader.pages):
            if i >= PDF_TEXT_MAX_PAGES:
                logger.warning(
                    "PDF {} text extraction is capped at {} pages",
                    file_path,
                    PDF_TEXT_MAX_PAGES,
                )
                break
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text[:remaining])
                remaining -= min(len(page_text) + 1, remaining)
                if remaining <= 0:
                    break
        text = _join_bounded(text_parts)
    except Exception as e:
        logger.warning(f"Failed to extract text from PDF {file_path}: {e}")

    # OCR Fallback if text is empty or very short
    if len(text.strip()) < 150:
        logger.info(f"PDF {file_path} text content is too short ({len(text)} chars). Trying Tesseract OCR...")
        try:
            import fitz  # PyMuPDF
            import pytesseract
            from PIL import Image

            try:
                pytesseract.get_tesseract_version()
            except Exception:
                logger.warning("Tesseract OCR is not installed or not in PATH — skipping OCR.")
                return text

            ocr_text_parts = []
            remaining = EXTRACTED_TEXT_MAX_CHARS
            with fitz.open(file_path) as doc:
                page_count = min(len(doc), OCR_MAX_PAGES)
                if len(doc) > page_count:
                    logger.warning(
                        "PDF {} has {} pages; OCR is capped at {} pages",
                        file_path,
                        len(doc),
                        page_count,
                    )
                for i in range(page_count):
                    page = doc.load_page(i)
                    mat = fitz.Matrix(2.0, 2.0)
                    pix = page.get_pixmap(matrix=mat)
                    img_data = pix.tobytes("png")
                    with Image.open(io.BytesIO(img_data)) as img:
                        page_ocr = pytesseract.image_to_string(
                            img,
                            lang="rus+bel+eng",
                        )
                    del img_data, pix, page
                    if page_ocr.strip():
                        ocr_text_parts.append(page_ocr[:remaining])
                        remaining -= min(len(page_ocr) + 1, remaining)
                        if remaining <= 0:
                            break

            if ocr_text_parts:
                logger.info(f"OCR successfully extracted {len(ocr_text_parts)} pages from PDF {file_path}")
                return _join_bounded(ocr_text_parts)
        except Exception as ocr_err:
            logger.warning(f"OCR failed for {file_path}: {ocr_err}")

    return text

def extract_text_from_docx(file_path: str) -> str:
    try:
        import docx
        _validate_office_zip(file_path)
        doc = docx.Document(file_path)
        def parts():
            for paragraph in doc.paragraphs:
                yield paragraph.text
            for table in doc.tables:
                for row in table.rows:
                    yield _join_bounded((cell.text for cell in row.cells), " | ")
        return _join_bounded(parts())
    except Exception as e:
        logger.warning(f"Failed to extract text from DOCX {file_path}: {e}")
        return ""

def extract_text_from_doc(file_path: str) -> str:
    try:
        # Try antiword first (handles real binary .doc)
        with subprocess.Popen(
            ["antiword", file_path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ) as process:
            timer = threading.Timer(10, process.kill)
            timer.start()
            try:
                output = process.stdout.read(EXTRACTED_TEXT_MAX_CHARS * 4)
                if process.poll() is None:
                    process.kill()
                process.wait()
                if not output:
                    raise ValueError("antiword returned no text")
                return _bounded_text(output.decode("utf-8", errors="replace"))
            finally:
                timer.cancel()
    except Exception as e:
        logger.warning(f"antiword failed to parse {file_path}, falling back to docx parser: {e}")
        # Fallback to python-docx in case it is a renamed docx/xml
        return extract_text_from_docx(file_path)

def extract_text_from_xlsx(file_path: str) -> str:
    try:
        from openpyxl import load_workbook
        _validate_office_zip(file_path)
        wb = load_workbook(file_path, read_only=True, data_only=True)
        try:
            def parts():
                rows_left = SPREADSHEET_MAX_ROWS
                for sheet in wb.worksheets:
                    for row in islice(sheet.iter_rows(values_only=True, max_col=SPREADSHEET_MAX_COLUMNS), rows_left):
                        rows_left -= 1
                        yield _join_bounded((str(cell) for cell in row if cell is not None), " | ")
                    if rows_left <= 0:
                        break
            return _join_bounded(parts())
        finally:
            wb.close()
    except Exception as e:
        logger.warning(f"Failed to extract text from XLSX {file_path}: {e}")
        return ""

def extract_text_from_xls(file_path: str) -> str:
    try:
        import xlrd
        wb = xlrd.open_workbook(file_path)
        def parts():
            rows_left = SPREADSHEET_MAX_ROWS
            for sheet in wb.sheets():
                for row_idx in range(min(sheet.nrows, rows_left)):
                    rows_left -= 1
                    yield _join_bounded((str(val) for val in sheet.row_values(row_idx, end_colx=SPREADSHEET_MAX_COLUMNS) if val is not None), " | ")
                if rows_left <= 0:
                    break
        return _join_bounded(parts())
    except Exception as e:
        logger.warning(f"Failed to extract text from XLS {file_path}: {e}")
        return ""

def extract_text_from_archive(file_path: str) -> str:
    ext = os.path.splitext(file_path.lower())[1]
    try:
        if ext == ".zip":
            archive = zipfile.ZipFile(file_path)
        elif ext == ".rar":
            import rarfile
            archive = rarfile.RarFile(file_path)
        else:
            # py7zr APIs differ by version and can inflate solid archives before
            # exposing bytes. Do not run unbounded extraction on shared hosts.
            logger.warning("Archive format {} is disabled: bounded streaming unavailable", ext)
            return ""
        with archive, tempfile.TemporaryDirectory() as temp_dir:
            members = archive.infolist()
            _validate_members(members, rar=ext == ".rar")
            total = 0
            text_parts = []
            remaining = EXTRACTED_TEXT_MAX_CHARS
            for index, member in enumerate(members):
                suffix = os.path.splitext(member.filename.lower())[1]
                if suffix not in (".pdf", ".docx", ".doc", ".xlsx", ".xls"):
                    continue
                # Never use archive paths for writes, even after validation.
                member_dir = os.path.join(temp_dir, str(index))
                os.mkdir(member_dir)
                target = os.path.join(member_dir, PurePosixPath(member.filename).name)
                written = 0
                with archive.open(member) as source, open(target, "wb") as output:
                    while True:
                        chunk = source.read(min(64 * 1024, ARCHIVE_MAX_BYTES - total + 1))
                        if not chunk:
                            break
                        total += len(chunk)
                        written += len(chunk)
                        if total > ARCHIVE_MAX_BYTES or written > member.file_size:
                            raise ValueError("archive stream exceeds declared size or byte limit")
                        output.write(chunk)
                sub_text = extract_text_from_file(target)
                if sub_text.strip():
                    part = f"--- Extracted from {PurePosixPath(member.filename).name} ---\n{sub_text}"
                    text_parts.append(part[:remaining])
                    remaining -= min(len(part) + 2, remaining)
                    if remaining <= 0:
                        break
            return _join_bounded(text_parts, "\n\n")
    except Exception as exc:
        logger.warning("Failed to extract archive {}: {}", file_path, exc)
        return ""

def extract_text_from_file(file_path: str) -> str:
    _, ext = os.path.splitext(file_path.lower())
    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
    elif ext == ".docx":
        text = extract_text_from_docx(file_path)
    elif ext == ".doc":
        text = extract_text_from_doc(file_path)
    elif ext == ".xlsx":
        text = extract_text_from_xlsx(file_path)
    elif ext == ".xls":
        text = extract_text_from_xls(file_path)
    elif ext in (".zip", ".rar", ".7z"):
        text = extract_text_from_archive(file_path)
    else:
        logger.warning(f"Unsupported file extension {ext} for {file_path}")
        text = ""
    return _bounded_text(text)
