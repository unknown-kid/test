import logging
import json
import re
from collections import Counter
from app.tasks.celery_app import celery_app
from app.services.llm_service import call_llm_sync, get_model_config_sync
from app.utils.websocket_manager import update_paper_status_sync
from app.utils.paper_payload import get_or_extract_paper_text
from app.utils.concurrency import get_step_limiter, get_worker_limiter
from sqlalchemy import create_engine, text
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

EN_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "into", "their", "than", "then", "when", "where", "which", "while",
    "using", "used", "use", "based", "study", "paper", "method", "results", "analysis",
}
CN_STOPWORDS = {
    "我们", "你们", "他们", "以及", "因此", "如果", "进行", "研究", "方法", "结果", "分析",
    "本文", "论文", "一种", "通过", "基于", "相关", "用于", "其中", "具有", "可以",
}


def _fallback_keywords(full_text: str, keyword_count: int) -> list[str]:
    english_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", full_text)
    chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,8}", full_text)

    counter: Counter[str] = Counter()
    for token in english_tokens:
        lowered = token.lower()
        if lowered in EN_STOPWORDS:
            continue
        counter[token] += 1
    for token in chinese_tokens:
        if token in CN_STOPWORDS:
            continue
        counter[token] += 1

    return [token for token, _ in counter.most_common(keyword_count)]


def _save_keywords_sync(paper_id: str, keywords: list[str]):
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE papers SET keywords = :kw WHERE id = :pid"),
                {"kw": json.dumps(keywords, ensure_ascii=False), "pid": paper_id},
            )
            conn.commit()
    finally:
        engine.dispose()


@celery_app.task(bind=True, max_retries=2)
def task_keyword_extraction(
    self,
    paper_id: str,
    full_text: str | None = None,
    user_id: str | None = None,
    object_key: str | None = None,
):
    """Step 4: Extract keywords via LLM."""
    step_limiter = None
    worker_limiter = None
    try:
        configs = get_model_config_sync()
        worker_total_limit = configs.get("worker_total_concurrency_limit", "18")
        worker_limiter = get_worker_limiter(worker_total_limit)
        worker_limiter.acquire_sync(wait=True)

        step_limit = configs.get("keywords_worker_limit", "6")
        step_limiter = get_step_limiter("keywords", step_limit)
        step_limiter.acquire_sync(wait=True)

        update_paper_status_sync(paper_id, "keywords", "processing", user_id)

        full_text = get_or_extract_paper_text(paper_id, full_text=full_text, object_key=object_key)
        keyword_chars = int(configs.get("keyword_extract_chars", "30000"))
        keyword_count = int(configs.get("keyword_count", "20"))
        model_limit = int(configs.get("llm_concurrency_limit", "64"))

        chat_url = configs.get("chat_api_url", "")
        chat_key = configs.get("chat_api_key", "")
        chat_model = configs.get("chat_model_name", "")

        if not chat_url or not chat_key:
            fallback_keywords = _fallback_keywords(full_text or "", keyword_count)
            if fallback_keywords:
                _save_keywords_sync(paper_id, fallback_keywords)
                logger.warning(f"Keyword fallback applied for {paper_id} because chat model is not configured")
            update_paper_status_sync(paper_id, "keywords", "completed", user_id)
            return

        prompt = (
            f"请从以下论文文本中提取{keyword_count}个关键词，"
            f"以JSON数组格式返回，例如：[\"keyword1\", \"keyword2\"]，不要其他内容：\n\n"
            f"{full_text[:keyword_chars]}"
        )
        result = call_llm_sync(
            chat_url, chat_key, chat_model, prompt,
            model_limit=model_limit, user_id=user_id,
        )

        # Parse keywords
        try:
            # Try to extract JSON array from response
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            keywords = json.loads(result)
            if not isinstance(keywords, list):
                keywords = [str(keywords)]
        except json.JSONDecodeError:
            keywords = [k.strip().strip('"').strip("'") for k in result.split(",") if k.strip()]

        keywords = keywords[:keyword_count]

        # Save to DB
        _save_keywords_sync(paper_id, keywords)

        update_paper_status_sync(paper_id, "keywords", "completed", user_id)
        logger.info(f"Keywords extracted for {paper_id}: {len(keywords)} keywords")
    except Exception as e:
        logger.error(f"Keyword extraction attempt failed for {paper_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=30)
        except self.MaxRetriesExceededError:
            logger.error(f"Keyword extraction failed after max retries for {paper_id}: {e}")
            fallback_keywords = _fallback_keywords(full_text or "", keyword_count)
            if fallback_keywords:
                _save_keywords_sync(paper_id, fallback_keywords)
                logger.warning(f"Keyword fallback applied for {paper_id} after model timeout/failure")
                update_paper_status_sync(paper_id, "keywords", "completed", user_id)
                return
            update_paper_status_sync(paper_id, "keywords", "failed", user_id)
            raise
    finally:
        if step_limiter:
            step_limiter.safe_release_sync()
        if worker_limiter:
            worker_limiter.safe_release_sync()
