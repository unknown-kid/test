import logging
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.folder import Folder
from app.models.paper import Paper

logger = logging.getLogger(__name__)


async def get_folder_or_raise(db: AsyncSession, folder_id: str) -> Folder:
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise ValueError("文件夹不存在")
    return folder


async def check_folder_permission(folder: Folder, user_id: str, role: str):
    """Check if user has access to this folder."""
    if role == "admin":
        if folder.zone != "shared":
            raise PermissionError("管理员只能操作共享区")
    else:
        if folder.zone == "personal" and folder.owner_id != user_id:
            raise PermissionError("无权访问此文件夹")


async def folder_name_exists(
    db: AsyncSession,
    name: str,
    zone: str,
    owner_id: str | None,
    parent_id: str | None,
    exclude_folder_id: str | None = None,
) -> bool:
    """Check whether sibling folder name already exists (case-insensitive)."""
    query = select(Folder.id).where(Folder.zone == zone)
    if parent_id is None:
        query = query.where(Folder.parent_id.is_(None))
    else:
        query = query.where(Folder.parent_id == parent_id)

    if zone == "personal":
        query = query.where(Folder.owner_id == owner_id)
    else:
        query = query.where(Folder.owner_id.is_(None))

    query = query.where(func.lower(Folder.name) == name.lower())
    if exclude_folder_id:
        query = query.where(Folder.id != exclude_folder_id)

    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def create_folder(
    db: AsyncSession, name: str, zone: str, owner_id: str | None,
    parent_id: str | None = None,
) -> Folder:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("文件夹名称不能为空")

    depth = 1
    if parent_id:
        parent = await get_folder_or_raise(db, parent_id)
        depth = parent.depth + 1
        if depth > 10:
            raise ValueError("文件夹嵌套深度不能超过10层")
        # Ensure same zone
        if parent.zone != zone:
            raise ValueError("不能跨区域创建文件夹")
        if zone == "personal" and parent.owner_id != owner_id:
            raise PermissionError("无权在此文件夹下创建")

    if await folder_name_exists(db, clean_name, zone, owner_id, parent_id):
        raise ValueError("同级目录下已存在同名文件夹")

    folder = Folder(
        name=clean_name, parent_id=parent_id, zone=zone,
        owner_id=owner_id, depth=depth,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


async def rename_folder(db: AsyncSession, folder_id: str, name: str) -> Folder:
    folder = await get_folder_or_raise(db, folder_id)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("文件夹名称不能为空")

    if await folder_name_exists(
        db,
        clean_name,
        folder.zone,
        folder.owner_id,
        folder.parent_id,
        exclude_folder_id=folder.id,
    ):
        raise ValueError("同级目录下已存在同名文件夹")

    folder.name = clean_name
    await db.commit()
    await db.refresh(folder)
    return folder


async def delete_folder(db: AsyncSession, folder_id: str):
    """Delete folder and all contents. Papers must be deleted separately (3-storage)."""
    folder = await get_folder_or_raise(db, folder_id)
    # Get all descendant paper ids for cleanup
    paper_ids = await get_descendant_paper_ids(db, folder_id)
    await db.delete(folder)
    await db.commit()
    return paper_ids


async def get_descendant_paper_ids(db: AsyncSession, folder_id: str) -> list[str]:
    """Get all paper IDs in folder and all descendants using recursive CTE."""
    cte_query = text("""
        WITH RECURSIVE folder_tree AS (
            SELECT id FROM folders WHERE id = :folder_id
            UNION ALL
            SELECT f.id FROM folders f JOIN folder_tree ft ON f.parent_id = ft.id
        )
        SELECT p.id FROM papers p WHERE p.folder_id IN (SELECT id FROM folder_tree)
    """)
    result = await db.execute(cte_query, {"folder_id": folder_id})
    return [row[0] for row in result.fetchall()]


async def get_folder_children(db: AsyncSession, parent_id: str | None, zone: str, owner_id: str | None = None):
    """Get direct child folders."""
    query = select(Folder).where(Folder.parent_id == parent_id, Folder.zone == zone)
    if zone == "personal" and owner_id:
        query = query.where(Folder.owner_id == owner_id)
    query = query.order_by(Folder.name)
    result = await db.execute(query)
    return result.scalars().all()


async def get_folder_papers(
    db: AsyncSession, folder_id: str | None, zone: str,
    owner_id: str | None, page: int, page_size: int,
):
    """Get papers in a specific folder with pagination."""
    base = select(Paper).where(Paper.zone == zone)
    if folder_id:
        base = base.where(Paper.folder_id == folder_id)
    else:
        base = base.where(Paper.folder_id.is_(None))
    if zone == "personal" and owner_id:
        base = base.where(Paper.uploaded_by == owner_id)

    # Count
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Items
    items_q = base.order_by(Paper.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(items_q)
    items = result.scalars().all()

    return items, total


async def update_ancestor_paper_counts(db: AsyncSession, folder_id: str | None, delta: int):
    """Recursively update paper_count for folder and all ancestors."""
    if not folder_id or delta == 0:
        return
    try:
        await apply_ancestor_paper_count_delta(db, folder_id, delta)
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to update paper counts: {e}")
        await db.rollback()


async def apply_ancestor_paper_count_delta(db: AsyncSession, folder_id: str | None, delta: int):
    """Apply folder paper_count delta within the caller's transaction."""
    if not folder_id or delta == 0:
        return

    await db.execute(text("""
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_id FROM folders WHERE id = :folder_id
            UNION ALL
            SELECT f.id, f.parent_id FROM folders f JOIN ancestors a ON f.id = a.parent_id
        )
        UPDATE folders
        SET paper_count = GREATEST(paper_count + :delta, 0)
        WHERE id IN (SELECT id FROM ancestors)
    """), {"folder_id": folder_id, "delta": delta})


async def get_breadcrumbs(db: AsyncSession, folder_id: str | None) -> list[dict]:
    """Get breadcrumb path from root to current folder."""
    if not folder_id:
        return []
    result = await db.execute(text("""
        WITH RECURSIVE path AS (
            SELECT id, name, parent_id FROM folders WHERE id = :folder_id
            UNION ALL
            SELECT f.id, f.name, f.parent_id FROM folders f JOIN path p ON f.id = p.parent_id
        )
        SELECT id, name FROM path
    """), {"folder_id": folder_id})
    rows = result.fetchall()
    return [{"id": r[0], "name": r[1]} for r in reversed(rows)]


async def get_folder_tree(db: AsyncSession, zone: str, owner_id: str | None = None) -> list[dict]:
    """Get full folder tree for a zone."""
    query = select(Folder).where(Folder.zone == zone)
    if zone == "personal" and owner_id:
        query = query.where(Folder.owner_id == owner_id)
    query = query.order_by(Folder.depth, Folder.name)
    result = await db.execute(query)
    folders = result.scalars().all()

    # Build tree
    folder_map = {}
    roots = []
    for f in folders:
        node = {"id": f.id, "name": f.name, "children": [], "paper_count": f.paper_count}
        folder_map[f.id] = node
        if f.parent_id and f.parent_id in folder_map:
            folder_map[f.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots
