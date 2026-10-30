"""3단계: 적재 — ORM으로 region / apartment / transaction 저장 (중복 방지)."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.regions import SEOUL_REGIONS
from app.models import Apartment, Region, Transaction
from app.services.cleaner import CleanDeal

logger = logging.getLogger(__name__)


def ensure_regions(db: Session) -> None:
    """서울 25개 구를 region 테이블에 등록 (이미 있으면 건너뜀)."""
    existing = set(db.scalars(select(Region.lawd_cd)))
    for code, name in SEOUL_REGIONS.items():
        if code not in existing:
            db.add(Region(lawd_cd=code, sigungu=name))
    db.commit()


def get_region(db: Session, lawd_cd: str) -> Region:
    region = db.scalar(select(Region).where(Region.lawd_cd == lawd_cd))
    if region is None:
        name = SEOUL_REGIONS.get(lawd_cd, lawd_cd)
        region = Region(lawd_cd=lawd_cd, sigungu=name)
        db.add(region)
        db.flush()
    return region


def load_deals(db: Session, lawd_cd: str, deals: list[CleanDeal]) -> int:
    """정제된 거래를 적재하고 새로 들어간 건수를 반환."""
    if not deals:
        return 0
    region = get_region(db, lawd_cd)

    # 단지 캐시: (name, dong) → Apartment
    apts = {
        (a.name, a.dong): a
        for a in db.scalars(select(Apartment).where(Apartment.region_id == region.id))
    }

    # 기존 거래 키 (해당 기간만 조회해서 비교)
    d_min = min(d.deal_date for d in deals)
    d_max = max(d.deal_date for d in deals)
    existing_keys = set(
        db.execute(
            select(Transaction.apartment_id, Transaction.deal_date, Transaction.area,
                   Transaction.floor, Transaction.price)
            .join(Apartment)
            .where(Apartment.region_id == region.id,
                   Transaction.deal_date.between(d_min, d_max))
        ).all()
    )

    inserted = 0
    for d in deals:
        apt = apts.get((d.apartment, d.dong))
        if apt is None:
            apt = Apartment(region_id=region.id, name=d.apartment, dong=d.dong, build_year=d.build_year)
            db.add(apt)
            db.flush()  # id 확보
            apts[(d.apartment, d.dong)] = apt

        key = (apt.id, d.deal_date, d.area, d.floor, d.price)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        db.add(Transaction(
            apartment_id=apt.id, deal_date=d.deal_date, price=d.price,
            area=d.area, floor=d.floor, price_per_pyeong=d.price_per_pyeong,
        ))
        inserted += 1

    db.commit()
    logger.info("적재 lawd_cd=%s 신규=%d / 입력=%d", lawd_cd, inserted, len(deals))
    return inserted
