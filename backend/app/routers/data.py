"""조회용 API: 지역, 거래, 통계."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Apartment, Region, Transaction
from app.schemas import MonthlyStat, RegionOut, RegionSummary, TransactionOut
from app.services import aggregator

router = APIRouter(tags=["data"])


@router.get("/regions", response_model=list[RegionOut])
def list_regions(db: Session = Depends(get_db)):
    return db.scalars(select(Region).order_by(Region.sigungu)).all()


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    lawd_cd: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Transaction, Apartment, Region)
        .join(Apartment, Transaction.apartment_id == Apartment.id)
        .join(Region, Apartment.region_id == Region.id)
        .order_by(Transaction.deal_date.desc(), Transaction.id.desc())
        .limit(limit).offset(offset)
    )
    if lawd_cd:
        stmt = stmt.where(Region.lawd_cd == lawd_cd)
    return [
        TransactionOut(
            deal_date=t.deal_date, sigungu=r.sigungu, dong=a.dong, apartment=a.name,
            area=t.area, floor=t.floor, price=t.price, price_per_pyeong=t.price_per_pyeong,
        )
        for t, a, r in db.execute(stmt)
    ]


@router.get("/stats/monthly", response_model=list[MonthlyStat])
def monthly_stats(lawd_cd: str | None = None, months: int = Query(12, ge=1, le=36),
                  db: Session = Depends(get_db)):
    return aggregator.monthly_stats(db, months, lawd_cd)


@router.get("/stats/regions", response_model=list[RegionSummary])
def region_summary(months: int = Query(3, ge=1, le=36), db: Session = Depends(get_db)):
    return aggregator.region_summary(db, months)
