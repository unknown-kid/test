import os
import logging
from sqlalchemy import create_engine, text
from app.config import get_settings
from app.services.minio_service import get_pdf
from app.utils.text_extraction import extract_text_from_pdf

logger = logging.getLogger(__name__)
settings = get_settings()

_CACHE_DIR = "/tmp/paper_text_cache"


def _cache_path(paper_id: str) -> str:
    safe_id = paper_id.replace("/", "_")
    return os.path.join(_CACHE_DIR, f"{safe_id}.txt")


def cache_paper_text(paper_id: str, full_text: str) -> None:
    if not full_text:
        return
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(paper_id), "w", encoding="utf-8") as f:
            f.write(full_text)
    except Exception as e:
        logger.warning(f"cache_paper_text failed for {paper_id}: {e}")


def load_cached_paper_text(paper_id: str) -> str | None:
    path = _cache_path(paper_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return content if content else None
    except Exception as e:
        logger.warning(f"load_cached_paper_text failed for {paper_id}: {e}")
        return None


def clear_cached_paper_text(paper_id: str) -> None:
    path = _cache_path(paper_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.warning(f"clear_cached_paper_text failed for {paper_id}: {e}")


def resolve_object_key(paper_id: str, object_key: str | None = None) -> str:
    if object_key:
        return object_key

    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT minio_object_key FROM papers WHERE id = :pid"),
                {"pid": paper_id},
            ).fetchone()
            if row and row[0]:
                return row[0]
    finally:
        engine.dispose()

    raise ValueError(f"paper object key not found: {paper_id}")


def get_pdf_bytes_for_paper(paper_id: str, object_key: str | None = None) -> tuple[bytes, str]:
    resolved_key = resolve_object_key(paper_id, object_key)
    return get_pdf(resolved_key), resolved_key


def get_or_extract_paper_text(
    paper_id: str,
    full_text: str | None = None,
    object_key: str | None = None,
) -> str:
    if full_text:
        cache_paper_text(paper_id, full_text)
        return full_text

    cached = load_cached_paper_text(paper_id)
    if cached:
        return cached

    pdf_bytes, _ = get_pdf_bytes_for_paper(paper_id, object_key)
    extracted = extract_text_from_pdf(pdf_bytes)
    cache_paper_text(paper_id, extracted)
    return extracted
