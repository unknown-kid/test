import logging
import fitz  # PyMuPDF
import pdfplumber

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF using PyMuPDF + pdfplumber fallback."""
    text = ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            text += page.get_text()
        doc.close()
    except Exception as e:
        logger.warning(f"PyMuPDF extraction failed: {e}")

    if not text.strip():
        try:
            import io
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")

    return text.strip()


def extract_metadata_title(pdf_bytes: bytes) -> str | None:
    """Try to extract title from PDF metadata."""
    # Try PyMuPDF
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        meta = doc.metadata
        doc.close()
        if meta and meta.get("title", "").strip():
            return meta["title"].strip()
    except Exception:
        pass

    # Try pdfplumber
    try:
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            meta = pdf.metadata
            if meta and meta.get("Title", "").strip():
                return meta["Title"].strip()
    except Exception:
        pass

    return None


def is_scanned_pdf(text: str) -> bool:
    """Check if PDF is scanned (no extractable text)."""
    return len(text.strip()) == 0
