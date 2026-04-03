import logging
import math
from app.tasks.celery_app import celery_app
from app.services.milvus_service import delete_paper_vectors, ensure_milvus_collections
from app.services.embedding_service import embed_texts_batch_sync, embed_text_sync, get_embedding_config_sync
from app.utils.text_extraction import extract_text_from_pdf
from app.utils.chunking import chunk_text
from app.services.minio_service import get_pdf
from app.services.llm_service import get_model_config_sync
from app.utils.websocket_manager import publish_notification_sync
from pymilvus import Collection
from sqlalchemy import create_engine, text
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(bind=True)
def task_vector_rebuild(self, admin_user_id: str):
    """Full vector rebuild for all papers after embedding model change."""
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        configs = get_model_config_sync()
        chunk_size = int(configs.get("chunk_size", "3000"))
        overlap_ratio = float(configs.get("chunk_overlap_ratio", "0.2"))
        model_limit = int(configs.get("llm_concurrency_limit", "64"))
        emb_url, emb_key, emb_model = get_embedding_config_sync()

        if not emb_url or not emb_key:
            publish_notification_sync(admin_user_id, {
                "type": "rebuild_failed",
                "content": "嵌入模型未配置，无法重建向量",
            })
            return

        # Get all papers
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, minio_object_key, abstract FROM papers")).fetchall()

        total = len(rows)
        ensure_milvus_collections(load=False)
        progress_interval = max(10, math.ceil(total / 10)) if total > 0 else 10

        for idx, row in enumerate(rows):
            paper_id, object_key, abstract = row[0], row[1], row[2]
            try:
                # Delete old vectors
                delete_paper_vectors(paper_id)

                # Re-chunk and vectorize
                pdf_bytes = get_pdf(object_key)
                full_text = extract_text_from_pdf(pdf_bytes)
                if not full_text:
                    continue

                chunks = chunk_text(full_text, chunk_size, overlap_ratio)
                if chunks:
                    batch_size = 20
                    all_vectors = []
                    for i in range(0, len(chunks), batch_size):
                        batch = chunks[i:i + batch_size]
                        vectors = embed_texts_batch_sync(
                            emb_url, emb_key, emb_model, batch,
                            model_limit, user_id=admin_user_id,
                        )
                        all_vectors.extend(vectors)

                    col = Collection("paper_chunks")
                    col.insert([
                        [paper_id] * len(chunks),
                        list(range(len(chunks))),
                        chunks,
                        all_vectors,
                    ])
                    col.flush()

                # Re-vectorize abstract
                if abstract:
                    vector = embed_text_sync(
                        emb_url, emb_key, emb_model, abstract,
                        model_limit, user_id=admin_user_id,
                    )
                    col = Collection("paper_abstracts")
                    col.insert([[paper_id], [abstract[:65000]], [vector]])
                    col.flush()

                if (idx + 1) % progress_interval == 0 or idx + 1 == total:
                    publish_notification_sync(admin_user_id, {
                        "type": "rebuild_progress",
                        "content": f"向量重建进度：{idx + 1}/{total}",
                    })

            except Exception as e:
                logger.error(f"Vector rebuild failed for {paper_id}: {e}")
                continue

        publish_notification_sync(admin_user_id, {
            "type": "rebuild_complete",
            "content": f"全量向量重建完成，共处理 {total} 篇论文",
        })
        logger.info(f"Vector rebuild completed: {total} papers")
    finally:
        engine.dispose()
