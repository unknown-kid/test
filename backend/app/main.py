import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import AsyncSessionLocal
from app.services.init_service import init_system
from pymilvus import connections
from app.services.milvus_service import ensure_milvus_collections

logger = logging.getLogger(__name__)


def init_milvus_collections():
    """Create Milvus collections if they don't exist.

    Avoid loading collections into memory during API startup. In unstable Milvus
    states this can block FastAPI lifespan and make the whole site appear down.
    """
    ensure_milvus_collections(load=False)


async def init_milvus_collections_background():
    """Run Milvus initialization off the main startup path."""
    try:
        await asyncio.to_thread(init_milvus_collections)
        logger.info("Milvus collections initialized")
    except Exception as e:
        logger.warning(f"Milvus init skipped (may not be ready): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up...")
    asyncio.create_task(init_milvus_collections_background())
    # Init admin user + default configs
    try:
        async with AsyncSessionLocal() as db:
            await init_system(db)
        logger.info("System initialized (admin + configs)")
    except Exception as e:
        logger.warning(f"System init error: {e}")
    yield
    # Shutdown
    try:
        connections.disconnect("default")
    except Exception:
        pass
    logger.info("Shutdown complete")


app = FastAPI(
    title="AI Paper Reading Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.routers import auth, files, papers, search, annotations, chat, translate, reports, admin, maintenance, model_test, notify
app.include_router(auth.router)
app.include_router(files.router)
app.include_router(papers.router)
app.include_router(search.router)
app.include_router(annotations.router)
app.include_router(chat.router)
app.include_router(translate.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(maintenance.router)
app.include_router(model_test.router)
app.include_router(notify.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
