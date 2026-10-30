"""인사이트 API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Insight, Region
from app.schemas import InsightOut, InsightRequest
from app.services.insight_service import generate_insight

router = APIRouter(prefix="/insights", tags=["insights"])


def _to_out(i: Insight) -> InsightOut:
    return InsightOut(
        id=i.id, sigungu=i.region.sigungu if i.region else None,
        period_start=i.period_start, period_end=i.period_end,
        summary_text=i.summary_text, source=i.source,
        prompt_version=i.prompt_version, created_at=i.created_at,
    )


@router.get("/latest", response_model=InsightOut)
def latest_insight(lawd_cd: str | None = None, db: Session = Depends(get_db)):
    """지역(또는 서울 전체)의 가장 최근 인사이트."""
    stmt = select(Insight).order_by(Insight.created_at.desc(), Insight.id.desc()).limit(1)
    if lawd_cd:
        stmt = stmt.join(Region).where(Region.lawd_cd == lawd_cd)
    else:
        stmt = stmt.where(Insight.region_id.is_(None))
    insight = db.scalar(stmt)
    if insight is None:
        raise HTTPException(404, "생성된 인사이트가 없습니다. POST /insights/generate 를 먼저 호출하세요.")
    return _to_out(insight)


@router.get("", response_model=list[InsightOut])
def list_insights(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.scalars(select(Insight).order_by(Insight.id.desc()).limit(limit)).all()
    return [_to_out(i) for i in rows]


@router.post("/generate", response_model=InsightOut)
def create_insight(req: InsightRequest, db: Session = Depends(get_db)):
    insight = generate_insight(db, req.months, req.lawd_cd)
    if insight is None:
        raise HTTPException(404, "해당 조건의 거래 데이터가 없습니다. 먼저 수집을 실행하세요.")
    return _to_out(insight)
