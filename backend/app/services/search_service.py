import logging
import re
from sqlalchemy import select, func, or_, and_, cast, Text
from sqlalchemy.ext.asyncio import AsyncSession
from pymilvus import Collection
from app.models.paper import Paper
from app.services.file_service import get_descendant_paper_ids
from app.services.embedding_service import get_embedding_config_sync
from app.services.milvus_service import ensure_milvus_collections

logger = logging.getLogger(__name__)


async def get_scope_paper_ids(db: AsyncSession, folder_id: str | None, zone: str, owner_id: str | None) -> list[str] | None:
    """Get paper IDs in scope (folder + descendants). Returns None for no filter."""
    if folder_id:
        return await get_descendant_paper_ids(db, folder_id)
    # All papers in zone
    query = select(Paper.id).where(Paper.zone == zone)
    if zone == "personal" and owner_id:
        query = query.where(Paper.uploaded_by == owner_id)
    result = await db.execute(query)
    return [r[0] for r in result.fetchall()]


def _build_keyword_conditions(keywords_str: str):
    keyword_list = [k.strip() for k in keywords_str.split(";") if k.strip()]
    conditions = []
    for kw in keyword_list:
        # Treat user input as literal text while using regex engine for partial match
        pattern = re.escape(kw)
        conditions.append(or_(
            Paper.title.op("~*")(pattern),
            cast(Paper.keywords, Text).op("~*")(pattern),
        ))
    return conditions


async def keyword_search(
    db: AsyncSession, keywords_str: str, scope_ids: list[str],
    page: int = 1, page_size: int = 20,
) -> tuple[list, int]:
    """Keyword search: regex match on title + keywords, AND logic."""
    conditions = _build_keyword_conditions(keywords_str)
    if not conditions or not scope_ids:
        return [], 0

    base = select(Paper).where(Paper.id.in_(scope_ids), and_(*conditions))

    # Count
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    items_q = base.order_by(Paper.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(items_q)
    return result.scalars().all(), total


async def keyword_match_ids(
    db: AsyncSession, keywords_str: str, scope_ids: list[str],
) -> set[str]:
    """Get all paper IDs matching keywords in scope, no pagination."""
    conditions = _build_keyword_conditions(keywords_str)
    if not conditions or not scope_ids:
        return set()

    id_q = select(Paper.id).where(Paper.id.in_(scope_ids), and_(*conditions))
    result = await db.execute(id_q)
    return {r[0] for r in result.fetchall()}


def rag_search_sync(
    query_text: str, scope_ids: list[str],
    threshold: float = 0.5, limit: int = 200,
    user_id: str | None = None,
) -> list[tuple[str, float]]:
    """RAG semantic search against paper_abstracts. Returns [(paper_id, score)]."""
    if not scope_ids:
        return []

    from app.services.embedding_service import embed_text_sync
    emb_url, emb_key, emb_model = get_embedding_config_sync()
    if not emb_url or not emb_key:
        return []

    # Embed query
    query_vector = embed_text_sync(emb_url, emb_key, emb_model, query_text, user_id=user_id)

    # Search Milvus
    try:
        ensure_milvus_collections(load=True)
    except Exception as e:
        logger.warning(f"Milvus unavailable in rag_search_sync, skip semantic search: {e}")
        return []
    col = Collection("paper_abstracts")

    # Build filter expression for paper_id scope
    if len(scope_ids) > 1000:
        # For large scopes, search without filter and post-filter
        results = col.search(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"nprobe": 16}},
            limit=limit,
            output_fields=["paper_id"],
        )
        scope_set = set(scope_ids)
        matches = []
        for hits in results:
            for hit in hits:
                if hit.entity.get("paper_id") in scope_set and hit.score >= threshold:
                    matches.append((hit.entity.get("paper_id"), float(hit.score)))
    else:
        id_list = '", "'.join(scope_ids)
        expr = f'paper_id in ["{id_list}"]'
        results = col.search(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"nprobe": 16}},
            limit=limit,
            expr=expr,
            output_fields=["paper_id"],
        )
        matches = []
        for hits in results:
            for hit in hits:
                if hit.score >= threshold:
                    matches.append((hit.entity.get("paper_id"), float(hit.score)))

    # Sort by score descending
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


async def _build_scored_page(
    db: AsyncSession, matches: list[tuple[str, float]],
    page: int, page_size: int,
) -> tuple[list, int]:
    """Convert ranked [(paper_id, score)] to ordered Paper rows with similarity_score."""
    total = len(matches)
    start = (page - 1) * page_size
    page_matches = matches[start:start + page_size]
    page_ids = [m[0] for m in page_matches]
    score_map = {pid: score for pid, score in page_matches}

    if not page_ids:
        return [], total

    result = await db.execute(select(Paper).where(Paper.id.in_(page_ids)))
    papers = result.scalars().all()
    paper_map = {p.id: p for p in papers}

    ordered = []
    for pid in page_ids:
        paper = paper_map.get(pid)
        if not paper:
            continue
        setattr(paper, "similarity_score", score_map.get(pid))
        ordered.append(paper)
    return ordered, total


async def rag_search(
    db: AsyncSession, query_text: str, scope_ids: list[str],
    threshold: float = 0.5, page: int = 1, page_size: int = 20,
    user_id: str | None = None,
) -> tuple[list, int]:
    """RAG search with pagination from DB."""
    import asyncio
    loop = asyncio.get_event_loop()
    matches = await loop.run_in_executor(None, rag_search_sync, query_text, scope_ids, threshold, 200, user_id)
    return await _build_scored_page(db, matches, page, page_size)


async def cascade_search(
    db: AsyncSession, keywords_str: str | None, rag_query: str | None,
    scope_ids: list[str], order: str, threshold: float = 0.5,
    page: int = 1, page_size: int = 20,
    user_id: str | None = None,
) -> tuple[list, int]:
    """Cascade search: first search narrows scope, second search filters within."""
    if order == "keyword_first" and keywords_str and rag_query:
        # Step 1: keyword search (get all results, no pagination)
        kw_papers, _ = await keyword_search(db, keywords_str, scope_ids, page=1, page_size=10000)
        kw_ids = [p.id for p in kw_papers]
        if not kw_ids:
            return [], 0
        # Step 2: RAG within keyword results
        return await rag_search(db, rag_query, kw_ids, threshold, page, page_size, user_id=user_id)

    elif order == "rag_first" and rag_query and keywords_str:
        # Step 1: RAG search (get all results)
        import asyncio
        loop = asyncio.get_event_loop()
        matches = await loop.run_in_executor(None, rag_search_sync, rag_query, scope_ids, threshold, 200, user_id)
        if not matches:
            return [], 0
        rag_ids = [m[0] for m in matches]
        # Step 2: keyword filter within RAG results, keep RAG similarity order
        kw_id_set = await keyword_match_ids(db, keywords_str, rag_ids)
        filtered_matches = [m for m in matches if m[0] in kw_id_set]
        return await _build_scored_page(db, filtered_matches, page, page_size)

    elif keywords_str:
        return await keyword_search(db, keywords_str, scope_ids, page, page_size)
    elif rag_query:
        return await rag_search(db, rag_query, scope_ids, threshold, page, page_size, user_id=user_id)
    else:
        return [], 0
