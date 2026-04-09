import logging
import json
import re
import httpx
from typing import AsyncGenerator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pymilvus import Collection
from app.database import AsyncSessionLocal
from app.models.chat import ChatSession, ChatMessage
from app.services.embedding_service import get_embedding_config_sync
from app.services.llm_service import get_model_config_sync, get_user_chat_model
from app.services.milvus_service import ensure_milvus_collections
from app.services.paper_service import get_accessible_paper_for_user
from app.config import get_settings
from app.utils.model_monitor import record_model_request
from app.utils.chunking import chunk_text
from app.utils.http_clients import build_async_httpx_client
from app.utils.paper_payload import get_or_extract_paper_text

logger = logging.getLogger(__name__)
settings = get_settings()


def _extract_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_text(v) for v in value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), str):
            return value["content"]
        if isinstance(value.get("content"), list):
            return "".join(_extract_text(v) for v in value["content"])
    return ""


def _extract_stream_content(data: dict) -> str:
    if not isinstance(data, dict):
        return ""

    if "content" in data:
        return _extract_text(data.get("content"))

    choices = data.get("choices") or []
    if choices:
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        if "content" in delta:
            return _extract_text(delta.get("content"))

        message = choice.get("message") or {}
        if "content" in message:
            return _extract_text(message.get("content"))

        if "text" in choice:
            return _extract_text(choice.get("text"))

    if "text" in data:
        return _extract_text(data.get("text"))

    return ""


def _extract_error_message(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "上游模型接口返回空错误信息"

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                msg = error.get("message") or error.get("detail")
                if msg:
                    return str(msg)
            if data.get("message"):
                return str(data["message"])
            if data.get("detail"):
                return str(data["detail"])
    except json.JSONDecodeError:
        pass
    return text[:400]


def _sanitize_stream_text(text: str) -> str:
    return text or ""


def _dedupe_stream_chunk(existing_text: str, incoming_text: str) -> str:
    if not incoming_text:
        return ""
    if not existing_text:
        return incoming_text
    if incoming_text.startswith(existing_text):
        return incoming_text[len(existing_text):]
    if existing_text.endswith(incoming_text):
        return ""

    max_overlap = min(len(existing_text), len(incoming_text), 4000)
    for overlap in range(max_overlap, 0, -1):
        if existing_text.endswith(incoming_text[:overlap]):
            return incoming_text[overlap:]
    return incoming_text


def _iter_sse_payloads(raw_chunk: str) -> tuple[list[str], str]:
    payloads: list[str] = []
    events = raw_chunk.split("\n\n")
    remainder = events.pop() if raw_chunk and not raw_chunk.endswith("\n\n") else ""

    for event in events:
        data_lines: list[str] = []
        for raw_line in event.splitlines():
            line = raw_line.rstrip("\r")
            if not line:
                continue
            if line.startswith(":"):
                continue
            if line.lower().startswith("event:"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[6:] if line.startswith("data: ") else line[5:])
            else:
                data_lines.append(line)
        payload = "\n".join(part for part in data_lines if part)
        if payload:
            payloads.append(payload)

    return payloads, remainder


def _decode_stream_payload(payload: str, full_response: str) -> str:
    try:
        chunk_data = json.loads(payload)
        content = _sanitize_stream_text(_extract_stream_content(chunk_data))
    except json.JSONDecodeError:
        content = _sanitize_stream_text(payload)
    return _dedupe_stream_chunk(full_response, content)


def _get_local_chunks(paper_id: str) -> list[str]:
    configs = get_model_config_sync()
    chunk_size = int(configs.get("chunk_size", "3000"))
    overlap_ratio = float(configs.get("chunk_overlap_ratio", "0.2"))
    full_text = get_or_extract_paper_text(paper_id)
    return chunk_text(full_text, chunk_size, overlap_ratio)


def _score_chunk_for_query(chunk: str, query: str) -> tuple[int, int]:
    query_terms = [term for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower()) if term]
    if not query_terms:
        return (0, 0)
    lowered_chunk = chunk.lower()
    matched_terms = sum(1 for term in set(query_terms) if term in lowered_chunk)
    term_hits = sum(lowered_chunk.count(term) for term in query_terms)
    return (matched_terms, term_hits)


async def create_session(
    db: AsyncSession, paper_id: str, user_id: str,
    source_type: str = "normal", source_text: str | None = None,
) -> ChatSession:
    await get_accessible_paper_for_user(db, paper_id, user_id)
    session = ChatSession(
        paper_id=paper_id, user_id=user_id,
        source_type=source_type, source_text=source_text,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_sessions(db: AsyncSession, paper_id: str, user_id: str) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.paper_id == paper_id, ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
    )
    return result.scalars().all()


async def get_messages(db: AsyncSession, session_id: str, user_id: str) -> list[ChatMessage]:
    session_result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise ValueError("会话不存在")

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return result.scalars().all()


async def delete_session(db: AsyncSession, session_id: str, user_id: str):
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("会话不存在")
    await db.delete(session)
    await db.commit()


async def delete_sessions_by_paper(db: AsyncSession, paper_id: str, user_id: str) -> int:
    result = await db.execute(
        select(ChatSession).where(ChatSession.paper_id == paper_id, ChatSession.user_id == user_id)
    )
    sessions = result.scalars().all()
    deleted = len(sessions)
    if deleted == 0:
        return 0

    for session in sessions:
        await db.delete(session)
    await db.commit()
    return deleted


def get_fixed_chunks(
    paper_id: str,
    count: int = 5,
    user_id: str | None = None,
) -> tuple[list[str], str]:
    """Get first N chunks by index for fixed context."""
    try:
        ensure_milvus_collections(load=True)
        col = Collection("paper_chunks")
        results = col.query(
            expr=f'paper_id == "{paper_id}"',
            output_fields=["chunk_index", "chunk_text"],
            limit=max(count, 1),
        )
        results.sort(key=lambda x: x["chunk_index"])
        chunks = [r["chunk_text"] for r in results[:count] if r.get("chunk_text")]
        if chunks:
            return chunks, "milvus"
    except Exception as e:
        logger.warning(f"Milvus fixed chunk lookup failed for {paper_id}, fallback to local chunks: {e}")

    return _get_local_chunks(paper_id)[:count], "local"


def rerank_chunks(
    paper_id: str,
    query: str,
    top_k: int = 5,
    user_id: str | None = None,
) -> tuple[list[str], str]:
    """Vector search + rerank to get top-K relevant chunks."""
    from app.services.embedding_service import embed_text_sync
    emb_url, emb_key, emb_model = get_embedding_config_sync()
    if emb_url and emb_key:
        try:
            query_vector = embed_text_sync(emb_url, emb_key, emb_model, query, user_id=user_id)

            ensure_milvus_collections(load=True)
            col = Collection("paper_chunks")

            results = col.search(
                data=[query_vector],
                anns_field="vector",
                param={"metric_type": "COSINE", "params": {"nprobe": 16}},
                limit=top_k,
                expr=f'paper_id == "{paper_id}"',
                output_fields=["chunk_text"],
            )

            chunks = []
            for hits in results:
                for hit in hits:
                    chunk_text_value = hit.entity.get("chunk_text")
                    if chunk_text_value:
                        chunks.append(chunk_text_value)
            if chunks:
                return chunks, "milvus"
        except Exception as e:
            logger.warning(f"Milvus rerank failed for {paper_id}, fallback to lexical rerank: {e}")

    local_chunks = _get_local_chunks(paper_id)
    scored_chunks = []
    for index, chunk in enumerate(local_chunks):
        matched_terms, term_hits = _score_chunk_for_query(chunk, query)
        if matched_terms <= 0 and term_hits <= 0:
            continue
        scored_chunks.append((matched_terms, term_hits, -index, chunk))

    if scored_chunks:
        scored_chunks.sort(reverse=True)
        return [chunk for _, _, _, chunk in scored_chunks[:top_k]], "local_lexical"

    return local_chunks[:top_k], "local_head"


def build_context(
    paper_id: str, query: str, fixed_count: int = 5,
    rerank_count: int = 5, context_limit: int = 100000,
    include_report: bool = False, user_id: str | None = None,
) -> tuple[str, dict]:
    """Build RAG context: fixed chunks + reranked chunks + optional report."""
    try:
        fixed, fixed_source = get_fixed_chunks(paper_id, fixed_count, user_id=user_id)
    except Exception as e:
        logger.warning(f"Get fixed chunks failed: {e}")
        fixed = []
        fixed_source = "error"

    try:
        reranked, rerank_source = rerank_chunks(paper_id, query, rerank_count, user_id=user_id)
    except Exception as e:
        logger.warning(f"Rerank chunks failed: {e}")
        reranked = []
        rerank_source = "error"

    # Deduplicate
    seen = set()
    all_chunks = []
    for c in fixed + reranked:
        if c not in seen:
            seen.add(c)
            all_chunks.append(c)

    # Optional report
    report_text = ""
    if include_report:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.SYNC_DATABASE_URL)
        try:
            with engine.connect() as conn:
                # Prefer user report, fallback to system
                row = conn.execute(text("""
                    SELECT content FROM reading_reports
                    WHERE paper_id = :pid AND status = 'completed'
                    ORDER BY CASE WHEN user_id = :uid THEN 0 ELSE 1 END
                    LIMIT 1
                """), {"pid": paper_id, "uid": user_id}).fetchone()
                if row and row[0]:
                    report_text = row[0]
        except Exception as e:
            logger.warning(f"Load report context failed: {e}")
        finally:
            engine.dispose()

    # Build context string with truncation
    context_parts = []
    total_len = 0

    if report_text:
        context_parts.append(f"[阅读报告]\n{report_text}")
        total_len += len(report_text)

    for i, chunk in enumerate(all_chunks):
        if total_len + len(chunk) > context_limit:
            break
        context_parts.append(f"[文档片段 {i + 1}]\n{chunk}")
        total_len += len(chunk)

    context = "\n\n".join(context_parts)
    meta = {
        "fixed_count": len(fixed),
        "rerank_count": len(reranked),
        "total_length": total_len,
        "fixed_source": fixed_source,
        "rerank_source": rerank_source,
    }
    return context, meta


async def stream_chat(
    session_id: str, user_id: str,
    user_message: str, paper_id: str,
    include_report: bool = False,
) -> AsyncGenerator[str, None]:
    """Stream chat response via SSE.

    Keep DB sessions short-lived so a long-running SSE response does not pin a
    pooled database connection for the whole stream duration.
    """
    import asyncio

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        )
        session = result.scalar_one_or_none()
    if not session:
        yield "data: [ERROR] 会话不存在或无权限\n\n"
        return
    if session.paper_id != paper_id:
        yield "data: [ERROR] 会话与论文不匹配\n\n"
        return

    # Get configs
    configs = get_model_config_sync()
    fixed_count = int(configs.get("chat_fixed_chunks", "5"))
    rerank_count = int(configs.get("chat_rerank_chunks", "5"))
    context_limit = int(configs.get("chat_context_limit", "100000"))
    session_title_len = int(configs.get("session_title_length", "30"))

    # Get model config (user > admin)
    user_model = get_user_chat_model(user_id)
    if user_model:
        api_url, api_key, model_name = user_model
    else:
        api_url = configs.get("chat_api_url", "")
        api_key = configs.get("chat_api_key", "")
        model_name = configs.get("chat_model_name", "")

    if not api_url or not api_key:
        yield "data: [ERROR] 对话模型未配置\n\n"
        return

    async with AsyncSessionLocal() as db:
        user_msg = ChatMessage(session_id=session_id, role="user", content=user_message)
        db.add(user_msg)
        await db.commit()

        if session and not session.title:
            managed_session = await db.get(ChatSession, session_id)
            if managed_session and not managed_session.title:
                managed_session.title = user_message[:session_title_len]
                await db.commit()

    # Build context (run in executor since it's sync)
    loop = asyncio.get_event_loop()
    try:
        context, meta = await loop.run_in_executor(
            None, build_context, paper_id, user_message,
            fixed_count, rerank_count, context_limit, include_report, user_id,
        )
    except Exception as e:
        logger.error(f"Build context failed: {e}")
        context = ""
        meta = {"fixed_count": 0, "rerank_count": 0, "total_length": 0, "context_error": str(e)}
        yield "data: [WARNING] 上下文构建失败，已降级为无RAG上下文\n\n"

    async with AsyncSessionLocal() as db:
        messages_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
        )
        history = messages_result.scalars().all()

    # Check history length warning
    total_history_len = sum(len(m.content) for m in history)
    if total_history_len > 60000:
        yield f"data: [WARNING] 对话历史已超过60000字符，建议新建会话\n\n"

    # Build messages for LLM
    llm_messages = [
        {"role": "system", "content": f"你是一个学术论文阅读助手。以下是论文的相关内容，请基于这些内容回答用户的问题。\n\n{context}"},
    ]
    for m in history:
        llm_messages.append({"role": m.role, "content": m.content})

    # Stream from LLM
    url = api_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    full_response = ""
    request_recorded = False
    try:
        async with build_async_httpx_client(timeout=120) as http_client:
            async with http_client.stream(
                "POST", url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model_name, "messages": llm_messages, "stream": True, "max_tokens": 4096},
            ) as response:
                if response.status_code >= 400:
                    raw = (await response.aread()).decode("utf-8", errors="ignore")
                    err_msg = _extract_error_message(raw)
                    await record_model_request("chat", model_name, user_id=user_id, success=False)
                    request_recorded = True
                    yield f"data: [ERROR] 上游模型接口错误({response.status_code}): {err_msg}\n\n"
                    return

                done_sent = False
                sse_buffer = ""
                async for raw_chunk in response.aiter_text():
                    if not raw_chunk:
                        continue
                    sse_buffer += raw_chunk
                    payloads, sse_buffer = _iter_sse_payloads(sse_buffer)
                    for payload in payloads:
                        control_payload = payload.strip()
                        if not control_payload:
                            continue

                        if control_payload == "[DONE]":
                            yield "data: [DONE]\n\n"
                            done_sent = True
                            break

                        if control_payload.startswith("[ERROR]"):
                            yield f"data: {control_payload}\n\n"
                            return

                        if control_payload.startswith("[WARNING]"):
                            yield f"data: {control_payload}\n\n"
                            continue

                        content = _decode_stream_payload(payload, full_response)
                        if content:
                            full_response += content
                            yield f"data: {json.dumps({'content': content})}\n\n"

                    if done_sent:
                        break

                if sse_buffer and not done_sent:
                    payloads, _ = _iter_sse_payloads(sse_buffer + "\n\n")
                    for payload in payloads:
                        control_payload = payload.strip()
                        if not control_payload:
                            continue

                        if control_payload == "[DONE]":
                            yield "data: [DONE]\n\n"
                            done_sent = True
                            break

                        if control_payload.startswith("[ERROR]"):
                            yield f"data: {control_payload}\n\n"
                            return

                        if control_payload.startswith("[WARNING]"):
                            yield f"data: {control_payload}\n\n"
                            continue

                        content = _decode_stream_payload(payload, full_response)
                        if content:
                            full_response += content
                            yield f"data: {json.dumps({'content': content})}\n\n"

                if not done_sent:
                    yield "data: [DONE]\n\n"
                await record_model_request("chat", model_name, user_id=user_id, success=True)
                request_recorded = True
    except Exception as e:
        logger.error(f"Chat stream error: {e}")
        if not request_recorded:
            await record_model_request("chat", model_name, user_id=user_id, success=False)
        yield f"data: [ERROR] {str(e)}\n\n"

    # Save assistant message
    if full_response:
        full_response = _sanitize_stream_text(full_response)
        async with AsyncSessionLocal() as db:
            assistant_msg = ChatMessage(
                session_id=session_id, role="assistant",
                content=full_response, context_chunks=meta,
            )
            db.add(assistant_msg)
            await db.commit()
