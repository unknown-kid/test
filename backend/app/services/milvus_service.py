import logging
import time
from pymilvus import (
    connections,
    Collection,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
)
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_connection():
    ensure_milvus_connection()


def _get_embedding_dim() -> int:
    """Read embedding dim from DB config, fallback to 4096."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.SYNC_DATABASE_URL)
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT value FROM system_config WHERE key = 'embedding_dim'"
            )).fetchone()
        engine.dispose()
        if row and row[0]:
            return int(row[0])
    except Exception as e:
        logger.warning(f"Read embedding_dim failed, fallback to 4096: {e}")
    return 4096


def ensure_milvus_connection(max_attempts: int = 6, base_delay: float = 1.0):
    """Connect to Milvus with retry."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
            )
            return
        except Exception as e:
            last_error = e
            if attempt == max_attempts:
                break
            sleep_s = min(base_delay * (2 ** (attempt - 1)), 8.0)
            logger.warning(
                f"Milvus connect failed (attempt {attempt}/{max_attempts}): {e}; retry in {sleep_s:.1f}s"
            )
            time.sleep(sleep_s)
    if last_error is not None:
        raise last_error


def _ensure_collection(
    name: str,
    fields: list[FieldSchema],
    description: str,
    index_params: dict,
) -> Collection:
    """Create collection if missing (safe under concurrent workers)."""
    if utility.has_collection(name):
        return Collection(name)

    try:
        schema = CollectionSchema(fields, description=description)
        col = Collection(name, schema)
        col.create_index("vector", index_params)
        logger.info(f"Created Milvus collection: {name}")
        return col
    except Exception as e:
        if utility.has_collection(name):
            logger.info(f"Milvus collection already exists due to concurrent init: {name}")
            return Collection(name)
        raise RuntimeError(f"Create Milvus collection failed: {name}") from e


def ensure_milvus_collections(load: bool = False):
    """Ensure required Milvus collections exist, optionally load to memory."""
    ensure_milvus_connection()
    dim = _get_embedding_dim()

    chunk_col = _ensure_collection(
        "paper_chunks",
        [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="paper_id", dtype=DataType.VARCHAR, max_length=36),
            FieldSchema(name="chunk_index", dtype=DataType.INT32),
            FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ],
        "Paper chunk vectors for RAG",
        {"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 1024}},
    )

    abstract_col = _ensure_collection(
        "paper_abstracts",
        [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="paper_id", dtype=DataType.VARCHAR, max_length=36),
            FieldSchema(name="abstract_text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ],
        "Paper abstract vectors for semantic search",
        {"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 256}},
    )

    if load:
        chunk_col.load()
        abstract_col.load()


def delete_paper_vectors(paper_id: str):
    """Delete all vectors for a paper from both collections."""
    ensure_milvus_collections(load=False)
    for col_name in ["paper_chunks", "paper_abstracts"]:
        if utility.has_collection(col_name):
            col = Collection(col_name)
            col.delete(f'paper_id == "{paper_id}"')
            logger.info(f"Deleted vectors for paper {paper_id} from {col_name}")


def copy_paper_vectors(old_paper_id: str, new_paper_id: str):
    """Copy vectors from one paper_id to another (for deep copy)."""
    ensure_milvus_collections(load=True)

    # Copy chunks
    if utility.has_collection("paper_chunks"):
        col = Collection("paper_chunks")
        col.load()
        results = col.query(
            expr=f'paper_id == "{old_paper_id}"',
            output_fields=["chunk_index", "chunk_text", "vector"],
        )
        if results:
            col.insert([
                [new_paper_id] * len(results),
                [r["chunk_index"] for r in results],
                [r["chunk_text"] for r in results],
                [r["vector"] for r in results],
            ])

    # Copy abstracts
    if utility.has_collection("paper_abstracts"):
        col = Collection("paper_abstracts")
        col.load()
        results = col.query(
            expr=f'paper_id == "{old_paper_id}"',
            output_fields=["abstract_text", "vector"],
        )
        if results:
            col.insert([
                [new_paper_id] * len(results),
                [r["abstract_text"] for r in results],
                [r["vector"] for r in results],
            ])
