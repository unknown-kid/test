import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.report import ReadingReport
from app.services.paper_service import get_accessible_paper_for_user

logger = logging.getLogger(__name__)


async def get_reports(db: AsyncSession, paper_id: str, user_id: str | None = None) -> list[ReadingReport]:
    """Get all reports for a paper: system report + user's personal report."""
    if user_id:
        await get_accessible_paper_for_user(db, paper_id, user_id)

    conditions = [ReadingReport.paper_id == paper_id]
    # System reports (user_id is null) + current user's reports
    from sqlalchemy import or_
    if user_id:
        conditions.append(or_(ReadingReport.user_id.is_(None), ReadingReport.user_id == user_id))
    else:
        conditions.append(ReadingReport.user_id.is_(None))

    result = await db.execute(
        select(ReadingReport).where(and_(*conditions)).order_by(ReadingReport.created_at.desc())
    )
    return list(result.scalars().all())


async def get_report_by_id(db: AsyncSession, report_id: str) -> ReadingReport | None:
    result = await db.execute(select(ReadingReport).where(ReadingReport.id == report_id))
    return result.scalar_one_or_none()


async def generate_user_report(
    db: AsyncSession, paper_id: str, user_id: str, focus_points: str | None = None
) -> ReadingReport:
    """Create or regenerate a user's personal report without deleting existing data first."""
    paper = await get_accessible_paper_for_user(db, paper_id, user_id)

    # Check if user already has a report for this paper
    result = await db.execute(
        select(ReadingReport).where(
            and_(
                ReadingReport.paper_id == paper_id,
                ReadingReport.user_id == user_id,
                ReadingReport.report_type == "user",
            )
        )
    )
    existing = result.scalar_one_or_none()

    # If existing report is already generating, don't start another
    if existing and existing.status == "generating":
        return existing

    if not paper.minio_object_key:
        raise ValueError("论文PDF文件缺失，无法生成报告")

    if existing:
        existing.focus_points = focus_points
        existing.status = "pending"
        await db.commit()
        await db.refresh(existing)

        from app.tasks.report_generation import task_report_generation
        task_report_generation.delay(
            paper_id, None, user_id=user_id, zone="personal",
            focus_points=focus_points, report_id=existing.id,
            object_key=paper.minio_object_key,
        )
        return existing

    report = ReadingReport(
            id=str(uuid.uuid4()),
            paper_id=paper_id,
            user_id=user_id,
            report_type="user",
            focus_points=focus_points,
            status="pending",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    from app.tasks.report_generation import task_report_generation
    task_report_generation.delay(
        paper_id, None, user_id=user_id, zone="personal",
        focus_points=focus_points, report_id=report.id,
        object_key=paper.minio_object_key,
    )
    return report


async def delete_report(db: AsyncSession, report_id: str, user_id: str):
    """Delete a user's personal report."""
    result = await db.execute(
        select(ReadingReport).where(
            and_(ReadingReport.id == report_id, ReadingReport.user_id == user_id)
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise ValueError("报告不存在")
    if report.report_type == "system":
        raise ValueError("不能删除系统报告")
    await db.delete(report)
    await db.commit()
