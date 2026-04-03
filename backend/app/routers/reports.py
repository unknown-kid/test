from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.dependencies import require_user
from app.models.user import User
from app.schemas.report import ReportInfo, ReportGenerateRequest
from app.services.report_service import get_reports, generate_user_report, delete_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{paper_id}", response_model=list[ReportInfo])
async def list_reports(
    paper_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_reports(db, paper_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{paper_id}/generate", response_model=ReportInfo)
async def generate_report(
    paper_id: str,
    req: ReportGenerateRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await generate_user_report(db, paper_id, user.id, req.focus_points)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/{report_id}")
async def remove_report(
    report_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_report(db, report_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "报告已删除"}
