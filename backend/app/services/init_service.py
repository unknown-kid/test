import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.config import SystemConfig
from app.services.auth_service import hash_password
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_CONFIGS = {
    "access_token_expire_minutes": ("1440", "Access Token过期时间(分钟)"),
    "llm_concurrency_limit": ("64", "单模型最大并发请求数"),
    "paper_concurrency_limit": ("10", "论文级并发上限"),
    "celery_worker_node_count": ("6", "Celery在线Worker节点目标数"),
    "worker_total_concurrency_limit": ("18", "全局Worker并发槽位上限(等效在线Worker数)"),
    "chunking_worker_limit": ("6", "分块向量化步骤Worker数"),
    "title_worker_limit": ("6", "标题提取步骤Worker数"),
    "abstract_worker_limit": ("6", "摘要提取步骤Worker数"),
    "keywords_worker_limit": ("6", "关键词提取步骤Worker数"),
    "report_worker_limit": ("6", "阅读报告步骤Worker数"),
    "chunk_size": ("3000", "分块大小(字符)"),
    "chunk_overlap_ratio": ("0.2", "分块重叠比例"),
    "title_extract_chars": ("2000", "标题提取字符数"),
    "abstract_extract_chars": ("10000", "摘要提取字符数"),
    "keyword_extract_chars": ("30000", "关键词提取字符数"),
    "keyword_count": ("20", "关键词提取数量"),
    "report_outline_chars": ("100000", "阅读报告粗读字符数"),
    "report_detail_chars": ("100000", "阅读报告精读字符数"),
    "ask_ai_rerank_top_k": ("10", "划词问AI Rerank Top-K"),
    "chat_fixed_chunks": ("5", "AI对话固定上下文块数"),
    "chat_rerank_chunks": ("5", "AI对话Rerank上下文块数"),
    "chat_context_limit": ("100000", "AI对话上下文窗口上限(字符)"),
    "rag_similarity_threshold": ("0.5", "RAG语义搜索相似度阈值"),
    "session_title_length": ("30", "Session标题截取长度"),
    # Model configs
    "chat_api_url": ("", "对话模型API地址"),
    "chat_api_key": ("", "对话模型API密钥"),
    "chat_model_name": ("", "对话模型名称"),
    "embedding_api_url": ("", "嵌入模型API地址"),
    "embedding_api_key": ("", "嵌入模型API密钥"),
    "embedding_model_name": ("", "嵌入模型名称"),
    "translate_type": ("openai", "翻译类型(openai/deepl)"),
    "translate_api_url": ("", "翻译模型API地址"),
    "translate_api_key": ("", "翻译模型API密钥"),
    "translate_model_name": ("", "翻译模型名称"),
    "embedding_dim": ("4096", "嵌入向量维度"),
}


async def init_admin_user(db: AsyncSession):
    """Create preset admin account if not exists."""
    result = await db.execute(select(User).where(User.username == settings.ADMIN_USERNAME))
    if result.scalar_one_or_none():
        return
    admin = User(
        username=settings.ADMIN_USERNAME,
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        role="admin",
        status="approved",
    )
    db.add(admin)
    await db.commit()
    logger.info(f"Preset admin account created: {settings.ADMIN_USERNAME}")


async def init_default_configs(db: AsyncSession):
    """Insert default system configs if not exists."""
    for key, (value, desc) in DEFAULT_CONFIGS.items():
        result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
        if not result.scalar_one_or_none():
            db.add(SystemConfig(key=key, value=value, description=desc))
    await db.commit()
    logger.info("Default system configs initialized")


async def init_system(db: AsyncSession):
    await init_admin_user(db)
    await init_default_configs(db)
