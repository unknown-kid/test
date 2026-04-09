import logging
import uuid
import litellm
from app.tasks.celery_app import celery_app
from app.services.llm_service import get_model_config_sync, get_user_chat_model
from app.utils.websocket_manager import update_paper_status_sync
from app.utils.concurrency import get_model_limiter, get_step_limiter, get_worker_limiter
from app.utils.http_clients import build_async_httpx_client, build_sync_httpx_client
from app.utils.paper_payload import get_or_extract_paper_text
from sqlalchemy import create_engine, text
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _configure_litellm_proxy_disabled() -> None:
    if litellm.client_session is None or getattr(litellm.client_session, "is_closed", False):
        litellm.client_session = build_sync_httpx_client(follow_redirects=True)
    if litellm.aclient_session is None or getattr(litellm.aclient_session, "is_closed", False):
        litellm.aclient_session = build_async_httpx_client(follow_redirects=True)


def _build_crewai_llm(api_url: str, api_key: str, model_name: str):
    """Build a CrewAI-compatible LLM instance using OpenAI-compatible API."""
    from crewai import LLM
    base_url = api_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]
    _configure_litellm_proxy_disabled()
    return LLM(
        model=f"openai/{model_name}",
        base_url=base_url,
        api_key=api_key,
    )


def _build_fallback_report(full_text: str, focus_points: str | None) -> str:
    preview_lines = []
    for raw_line in full_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        preview_lines.append(line)
        if sum(len(item) for item in preview_lines) >= 1500:
            break
    preview = "\n".join(preview_lines)[:1500].strip()
    focus = focus_points or "无特别关注点"
    return (
        "# 阅读报告（保底版本）\n\n"
        "模型服务在报告生成阶段超时，系统已生成保底报告，后续可再次重跑以获取完整智能分析。\n\n"
        "## 用户关注点\n\n"
        f"{focus}\n\n"
        "## 论文原文摘录\n\n"
        f"{preview or '原文内容暂不可用'}\n\n"
        "## 后续建议\n\n"
        "- 可在模型服务稳定后重新生成完整报告。\n"
        "- 当前论文的基础信息、摘要、关键词步骤仍可继续使用。\n"
    )


def _ensure_report_record(
    conn,
    paper_id: str,
    zone: str,
    user_id: str | None,
    focus_points: str | None,
    report_id: str | None,
    status: str,
) -> str:
    if report_id:
        conn.execute(
            text(
                "UPDATE reading_reports SET status = :status, focus_points = :fp WHERE id = :rid"
            ),
            {"rid": report_id, "status": status, "fp": focus_points},
        )
        return report_id

    report_id = str(uuid.uuid4())
    conn.execute(text("""
        INSERT INTO reading_reports (id, paper_id, user_id, report_type, status, focus_points)
        VALUES (:rid, :pid, :uid, :rtype, :status, :fp)
    """), {
        "rid": report_id,
        "pid": paper_id,
        "uid": None if zone == "shared" else user_id,
        "rtype": "system" if not user_id or zone == "shared" else "user",
        "status": status,
        "fp": focus_points,
    })
    return report_id


@celery_app.task(bind=True, max_retries=2)
def task_report_generation(
    self, paper_id: str, full_text: str | None = None,
    user_id: str | None = None, zone: str = "personal",
    focus_points: str | None = None, report_id: str | None = None,
    object_key: str | None = None,
):
    """Step 5: Generate reading report using CrewAI (Outline Agent → Detail Agent)."""
    step_limiter = None
    worker_limiter = None
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        configs = get_model_config_sync()
        worker_total_limit = configs.get("worker_total_concurrency_limit", "18")
        worker_limiter = get_worker_limiter(worker_total_limit)
        worker_limiter.acquire_sync(wait=True)

        step_limit = configs.get("report_worker_limit", "6")
        step_limiter = get_step_limiter("report", step_limit)
        step_limiter.acquire_sync(wait=True)

        update_paper_status_sync(paper_id, "report", "processing", user_id)

        full_text = get_or_extract_paper_text(paper_id, full_text=full_text, object_key=object_key)
        outline_chars = int(configs.get("report_outline_chars", "100000"))
        detail_chars = int(configs.get("report_detail_chars", "100000"))
        model_limit = int(configs.get("llm_concurrency_limit", "64"))

        # Model selection: user model > admin default
        api_url, api_key, model_name = "", "", ""
        if zone == "personal" and user_id:
            user_model = get_user_chat_model(user_id)
            if user_model:
                api_url, api_key, model_name = user_model
        if not api_url:
            api_url = configs.get("chat_api_url", "")
            api_key = configs.get("chat_api_key", "")
            model_name = configs.get("chat_model_name", "")

        if not api_url or not api_key:
            logger.warning("No chat model configured, fallback report will be generated")
            fallback_report = _build_fallback_report(full_text, focus_points)
            with engine.connect() as conn:
                report_id = _ensure_report_record(
                    conn, paper_id, zone, user_id, focus_points, report_id, "completed"
                )
                conn.execute(
                    text(
                        "UPDATE reading_reports SET content = :content, status = 'completed' WHERE id = :rid"
                    ),
                    {"content": fallback_report, "rid": report_id},
                )
                conn.commit()
            update_paper_status_sync(paper_id, "report", "completed", user_id)
            return

        # Create report record if not exists
        with engine.connect() as conn:
            report_id = _ensure_report_record(
                conn, paper_id, zone, user_id, focus_points, report_id, "generating"
            )
            conn.commit()

        # Acquire concurrency slot
        limiter = get_model_limiter(model_name, model_limit)
        limiter.acquire_sync(wait=True)
        try:
            report_content = _run_crewai_report(
                api_url, api_key, model_name,
                full_text, outline_chars, detail_chars, focus_points,
            )
        finally:
            limiter.safe_release_sync()

        # Save report
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE reading_reports SET content = :content, status = 'completed' WHERE id = :rid
            """), {"content": report_content, "rid": report_id})
            conn.commit()

        update_paper_status_sync(paper_id, "report", "completed", user_id)
        logger.info(f"Report generated for {paper_id}")
    except Exception as e:
        logger.error(f"Report generation attempt failed for {paper_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            logger.error(f"Report generation failed after max retries for {paper_id}: {e}")
            if report_id:
                fallback_report = _build_fallback_report(full_text or "", focus_points)
                with engine.connect() as conn:
                    conn.execute(
                        text(
                            "UPDATE reading_reports SET content = :content, status = 'completed' WHERE id = :rid"
                        ),
                        {"rid": report_id, "content": fallback_report},
                    )
                    conn.commit()
                logger.warning(f"Fallback report applied for {paper_id} after model timeout/failure")
                update_paper_status_sync(paper_id, "report", "completed", user_id)
                return
            update_paper_status_sync(paper_id, "report", "failed", user_id)
            raise
    finally:
        if step_limiter:
            step_limiter.safe_release_sync()
        if worker_limiter:
            worker_limiter.safe_release_sync()
        engine.dispose()


def _run_crewai_report(
    api_url: str, api_key: str, model_name: str,
    full_text: str, outline_chars: int, detail_chars: int,
    focus_points: str | None,
) -> str:
    """Run CrewAI crew with Outline Agent and Detail Agent."""
    from crewai import Agent, Task, Crew, Process

    llm = _build_crewai_llm(api_url, api_key, model_name)

    focus_text = f"用户特别关注：{focus_points}" if focus_points else "无特别关注点，请全面分析"

    # Agent 1: Outline Agent
    outline_agent = Agent(
        role="论文大纲分析师",
        goal="阅读论文内容，提取核心结构，生成详细的阅读报告大纲",
        backstory=(
            "你是一位资深的学术论文分析专家，擅长快速把握论文的核心结构、"
            "研究方法、主要贡献和创新点。你的大纲清晰、层次分明，能够为后续的详细报告撰写提供完美的框架。"
        ),
        llm=llm,
        verbose=False,
    )

    # Agent 2: Detail Agent
    detail_agent = Agent(
        role="论文报告撰写专家",
        goal="根据大纲和论文原文，撰写一份完整、详细的Markdown格式阅读报告",
        backstory=(
            "你是一位专业的学术写作专家，擅长将复杂的学术论文转化为结构清晰、"
            "内容详实的阅读报告。你的报告既保持学术严谨性，又具有良好的可读性。"
        ),
        llm=llm,
        verbose=False,
    )

    # Task 1: Generate outline
    outline_task = Task(
        description=(
            f"请仔细阅读以下论文内容，生成一份详细的阅读报告大纲。\n\n"
            f"{focus_text}\n\n"
            f"论文内容：\n{full_text[:outline_chars]}\n\n"
            f"要求：\n"
            f"1. 提取论文的研究背景、问题定义、方法论、实验设计、结果分析、结论\n"
            f"2. 标注每个部分的关键要点\n"
            f"3. 识别论文的创新点和局限性"
        ),
        expected_output="一份结构清晰的论文阅读报告大纲，包含各章节要点",
        agent=outline_agent,
    )

    # Task 2: Write detailed report based on outline
    detail_task = Task(
        description=(
            f"请根据上一步生成的大纲和论文原文，撰写一份完整的论文阅读报告（Markdown格式）。\n\n"
            f"{focus_text}\n\n"
            f"论文内容：\n{full_text[:detail_chars]}\n\n"
            f"要求：\n"
            f"1. 使用Markdown格式，包含标题、子标题、列表等\n"
            f"2. 每个部分都要有详细的分析和解读\n"
            f"3. 包含研究方法评价、结果解读、创新点总结、局限性分析\n"
            f"4. 语言准确、专业，适合学术阅读"
        ),
        expected_output="一份完整的Markdown格式论文阅读报告",
        agent=detail_agent,
    )

    # Create and run crew
    crew = Crew(
        agents=[outline_agent, detail_agent],
        tasks=[outline_task, detail_task],
        process=Process.sequential,
        verbose=False,
    )

    result = crew.kickoff()
    return str(result)
