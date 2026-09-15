import os
import tempfile
import zipfile
import pytest
from unittest.mock import MagicMock, patch

from worker.analyzer.text_extractor import (
    extract_text_from_xls,
    extract_text_from_doc,
    extract_text_from_archive,
    extract_text_from_pdf,
)

def test_extract_text_from_archive_zip():
    # Create a real ZIP archive on the fly
    with tempfile.TemporaryDirectory() as temp_dir:
        archive_path = os.path.join(temp_dir, "test.zip")
        
        # Write dummy docx/pdf names inside zip
        with zipfile.ZipFile(archive_path, "w") as z:
            z.writestr("info.docx", "This is document content inside zip")
            z.writestr("unsupported.txt", "Plain text is ignored")
            
        # Patch the individual extractors so they don't depend on complex libraries for docx
        with patch("worker.analyzer.text_extractor.extract_text_from_file") as mock_extract:
            mock_extract.side_effect = lambda path: (
                "Parsed DOCX Content" if path.endswith("info.docx") else ""
            )
            
            res = extract_text_from_archive(archive_path)
            
            assert "--- Extracted from info.docx ---" in res
            assert "Parsed DOCX Content" in res
            assert "unsupported.txt" not in res

@patch("subprocess.run")
def test_extract_text_from_doc_binary(mock_run):
    mock_run.return_value = MagicMock(stdout="Binary Word Document Content", returncode=0)
    
    res = extract_text_from_doc("test.doc")
    assert res == "Binary Word Document Content"
    mock_run.assert_called_once()

@patch("xlrd.open_workbook")
def test_extract_text_from_xls_binary(mock_open):
    # Mock xlrd sheet and rows
    mock_sheet = MagicMock()
    mock_sheet.nrows = 2
    mock_sheet.row_values.side_effect = [
        ["Header 1", "Header 2"],
        ["Val 1", "Val 2"],
    ]
    
    mock_wb = MagicMock()
    mock_wb.sheets.return_value = [mock_sheet]
    mock_open.return_value = mock_wb
    
    res = extract_text_from_xls("test.xls")
    assert "Header 1 | Header 2" in res
    assert "Val 1 | Val 2" in res

@patch("pypdf.PdfReader")
@patch("fitz.open")
@patch("pytesseract.image_to_string")
@patch("pytesseract.get_tesseract_version")
@patch("PIL.Image.open")
def test_pdf_ocr_fallback(mock_img_open, mock_tess_ver, mock_image_to_string, mock_fitz_open, mock_pdf_reader):
    # Setup PdfReader to return empty text (scanned PDF)
    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""
    mock_pdf_reader.return_value.pages = [mock_page]
    
    # Setup Tesseract mock version check
    mock_tess_ver.return_value = "5.0.0"
    
    # Setup fitz (PyMuPDF) mock rendering
    mock_fitz_page = MagicMock()
    mock_fitz_page.get_pixmap.return_value.tobytes.return_value = b"fake_png_data"
    mock_fitz_doc = MagicMock()
    mock_fitz_doc.__len__.return_value = 1
    mock_fitz_doc.load_page.return_value = mock_fitz_page
    mock_fitz_open.return_value.__enter__.return_value = mock_fitz_doc
    mock_fitz_open.return_value.__exit__.return_value = False
    
    # Mock PIL Image open
    mock_img_open.return_value = MagicMock()
    
    # Setup Tesseract mock OCR output
    mock_image_to_string.return_value = "OCR Decoded Text Content"
    
    res = extract_text_from_pdf("scanned.pdf")
    assert "OCR Decoded Text Content" in res


@patch("worker.analyzer.text_extractor.OCR_MAX_PAGES", 2)
@patch("pypdf.PdfReader")
@patch("fitz.open")
@patch("pytesseract.image_to_string")
@patch("pytesseract.get_tesseract_version")
@patch("PIL.Image.open")
def test_pdf_ocr_respects_page_cap(
    mock_img_open,
    mock_tess_ver,
    mock_image_to_string,
    mock_fitz_open,
    mock_pdf_reader,
):
    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""
    mock_pdf_reader.return_value.pages = [mock_page]
    mock_tess_ver.return_value = "5.0.0"

    mock_fitz_doc = MagicMock()
    mock_fitz_doc.__len__.return_value = 100
    mock_fitz_page = MagicMock()
    mock_fitz_page.get_pixmap.return_value.tobytes.return_value = b"png"
    mock_fitz_doc.load_page.return_value = mock_fitz_page
    mock_fitz_open.return_value.__enter__.return_value = mock_fitz_doc
    mock_image_to_string.return_value = "page"

    extract_text_from_pdf("large-scan.pdf")

    assert mock_fitz_doc.load_page.call_count == 2
    assert mock_image_to_string.call_count == 2
