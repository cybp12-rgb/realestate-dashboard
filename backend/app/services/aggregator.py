"""4단계: 집계 — 대시보드 차트와 LLM 입력에 쓰는 통계."""
from datetime import date

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.models import Apartment, Region, Transaction


def _month_start_ago(ref: date, months: int) -> date:
    """ref가 속한 달을 포함해 months개월 전의 1일."""
    y, m = ref.year, ref.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def latest_deal_date(db: Session) -> date | None:
    return db.scalar(select(func.max(Transaction.deal_date)))


def period_for(db: Session, months: int) -> tuple[date, date] | None:
    """데이터의 가장 최근 거래일 기준 최근 months개월 구간."""
    end = latest_deal_date(db)
    if end is None:
        return None
    return _month_start_ago(end, months), end


def monthly_stats(db: Session, months: int = 12, lawd_cd: str | None = None) -> list[dict]:
    period = period_for(db, months)
    if period is None:
        return []
    start, end = period
    y = extract("year", Transaction.deal_date)
    m = extract("month", Transaction.deal_date)
    stmt = (
        select(
            y.label("y"), m.label("m"), Region.sigungu,
            func.count(Transaction.id).label("deal_count"),
            func.avg(Transaction.price).label("avg_price"),
            func.avg(Transaction.price_per_pyeong).label("avg_ppp"),
        )
        .join(Apartment, Transaction.apartment_id == Apartment.id)
        .join(Region, Apartment.region_id == Region.id)
        .where(Transaction.deal_date.between(start, end))
        .group_by(y, m, Region.sigungu)
        .order_by(y, m)
    )
    if lawd_cd:
        stmt = stmt.where(Region.lawd_cd == lawd_cd)
    return [
        {
            "month": f"{int(r.y):04d}-{int(r.m):02d}",
            "sigungu": r.sigungu,
            "deal_count": r.deal_count,
            "avg_price": round(float(r.avg_price), 1),
            "avg_price_per_pyeong": round(float(r.avg_ppp), 1),
        }
        for r in db.execute(stmt)
    ]


def region_summary(db: Session, months: int = 3) -> list[dict]:
    period = period_for(db, months)
    if period is None:
        return []
    start, end = period
    stmt = (
        select(
            Region.sigungu,
            func.count(Transaction.id).label("deal_count"),
            func.avg(Transaction.price).label("avg_price"),
            func.avg(Transaction.price_per_pyeong).label("avg_ppp"),
        )
        .join(Apartment, Transaction.apartment_id == Apartment.id)
        .join(Region, Apartment.region_id == Region.id)
        .where(Transaction.deal_date.between(start, end))
        .group_by(Region.sigungu)
        .order_by(func.avg(Transaction.price_per_pyeong).desc())
    )
    return [
        {
            "sigungu": r.sigungu,
            "deal_count": r.deal_count,
            "avg_price": round(float(r.avg_price), 1),
            "avg_price_per_pyeong": round(float(r.avg_ppp), 1),
        }
        for r in db.execute(stmt)
    ]


def build_insight_input(db: Session, months: int, lawd_cd: str | None) -> dict | None:
    """LLM에 넘길 '숫자 요약'. LLM은 이 값만 근거로 문장을 만듭니다."""
    period = period_for(db, months)
    if period is None:
        return None
    start, end = period

    rows = monthly_stats(db, months, lawd_cd)
    # 지역별 월 통계를 월 단위로 합산 (서울 전체일 때)
    by_month: dict[str, dict] = {}
    for r in rows:
        b = by_month.setdefault(r["month"], {"deal_count": 0, "_ppp_sum": 0.0})
        b["deal_count"] += r["deal_count"]
        b["_ppp_sum"] += r["avg_price_per_pyeong"] * r["deal_count"]
    monthly = [
        {"month": k, "deal_count": v["deal_count"],
         "avg_price_per_pyeong": round(v["_ppp_sum"] / v["deal_count"], 1)}
        for k, v in sorted(by_month.items())
    ]
    if not monthly:
        return None

    first, last = monthly[0], monthly[-1]
    change_pct = round((last["avg_price_per_pyeong"] / first["avg_price_per_pyeong"] - 1) * 100, 1)

    # 거래가 많은 단지 Top 3
    top_stmt = (
        select(Apartment.name, Apartment.dong, func.count(Transaction.id).label("cnt"),
               func.avg(Transaction.price).label("avg_price"))
        .join(Transaction).join(Region)
        .where(Transaction.deal_date.between(start, end))
        .group_by(Apartment.id, Apartment.name, Apartment.dong)
        .order_by(func.count(Transaction.id).desc())
        .limit(3)
    )
    if lawd_cd:
        top_stmt = top_stmt.where(Region.lawd_cd == lawd_cd)
    top_apts = [
        {"name": r.name, "dong": r.dong, "deal_count": r.cnt, "avg_price": round(float(r.avg_price))}
        for r in db.execute(top_stmt)
    ]

    region_name = "서울 전체"
    if lawd_cd:
        region_name = db.scalar(select(Region.sigungu).where(Region.lawd_cd == lawd_cd)) or lawd_cd

    data = {
        "region": region_name,
        "period": f"{start.isoformat()} ~ {end.isoformat()}",
        "unit": {"price": "만원", "price_per_pyeong": "만원/평"},
        "monthly": monthly,
        "price_per_pyeong_change_pct": change_pct,
        "deal_count_first_month": first["deal_count"],
        "deal_count_last_month": last["deal_count"],
        "top_apartments_by_deals": top_apts,
    }
    if not lawd_cd:
        summary = region_summary(db, months)
        data["top3_expensive_gu"] = summary[:3]
        data["bottom3_gu"] = summary[-3:]
    return {"period_start": start, "period_end": end, "data": data}
