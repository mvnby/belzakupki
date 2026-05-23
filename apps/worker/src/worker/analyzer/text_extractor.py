from __future__ import annotations

import os
from loguru import logger

def extract_text_from_pdf(file_path: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text_parts = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.warning(f"Failed to extract text from PDF {file_path}: {e}")
        return ""

def extract_text_from_docx(file_path: str) -> str:
    try:
        import docx
        doc = docx.Document(file_path)
        text_parts = [p.text for p in doc.paragraphs]
        # Include tables if any
        for table in doc.tables:
            for row in table.rows:
                row_text = [cell.text for cell in row.cells]
                text_parts.append(" | ".join(row_text))
        return "\n".join(text_parts)
    except Exception as e:
        logger.warning(f"Failed to extract text from DOCX {file_path}: {e}")
        return ""

def extract_text_from_xlsx(file_path: str) -> str:
    try:
        from openpyxl import load_workbook  # type: ignore[import]
        wb = load_workbook(file_path, read_only=True, data_only=True)
        text_parts: list[str] = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                row_text = " | ".join(
                    str(cell) for cell in row if cell is not None and str(cell).strip()
                )
                if row_text:
                    text_parts.append(row_text)
        wb.close()
        return "\n".join(text_parts)
    except ImportError:
        logger.warning(
            "openpyxl is not installed — .xlsx files will be skipped. "
            "Run `pip install openpyxl` to enable Excel extraction."
        )
        return ""
    except Exception as e:
        logger.warning(f"Failed to extract text from XLSX {file_path}: {e}")
        return ""


def extract_text_from_file(file_path: str) -> str:
    _, ext = os.path.splitext(file_path.lower())
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".docx", ".doc"):
        # python-docx does not support .doc binary format, but some .doc are actually xml/docx renamed
        # Let's try parsing docx, and if it fails, it will log a warning and return empty
        return extract_text_from_docx(file_path)
    elif ext in (".xlsx", ".xls"):
        return extract_text_from_xlsx(file_path)
    else:
        logger.warning(f"Unsupported file extension {ext} for {file_path}")
        return ""
