"""파이프라인 실행/이력 API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import CollectError
from app.database import get_db
from app.models import PipelineLog
from app.schemas import CollectRequest, CollectResult, PipelineLogOut
from app.services.pipeline import run_collect

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/collect", response_model=CollectResult)
def collect(req: CollectRequest, db: Session = Depends(get_db)):
    """지정 기간 데이터 수집. (지역·기간이 크면 오래 걸리니 CLI 사용을 권장)"""
    try:
        return run_collect(db, req.start_ym, req.end_ym, req.lawd_cds)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except CollectError as e:  # 인증키 미설정 등
        raise HTTPException(503, str(e)) from e


@router.get("/logs", response_model=list[PipelineLogOut])
def logs(limit: int = 50, only_failed: bool = False, db: Session = Depends(get_db)):
    stmt = select(PipelineLog).order_by(PipelineLog.id.desc()).limit(limit)
    if only_failed:
        stmt = stmt.where(PipelineLog.status == "fail")
    return db.scalars(stmt).all()
