"""2단계: 정제 — API 원본(item dict) → 적재 가능한 레코드.

처리 내용
- 거래금액 "82,500" → 82500 (만원)
- 계약일 년/월/일 → date
- 전용면적 문자열 → float, 평당가 계산
- 해제(취소)된 거래 제외 (cdealType == "O")
- 필수값 누락/형식 오류 행은 버리고 개수만 로그
"""
import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)

PYEONG_M2 = 3.3058


@dataclass(frozen=True)
class CleanDeal:
    apartment: str
    dong: str
    build_year: int | None
    deal_date: date
    price: int
    area: float
    floor: int | None
    price_per_pyeong: float


def _to_int(v: str | None) -> int | None:
    if v is None:
        return None
    v = v.replace(",", "").strip()
    return int(v) if v.lstrip("-").isdigit() else None


def clean_item(item: dict) -> CleanDeal | None:
    """정상 행이면 CleanDeal, 버려야 할 행이면 None."""
    if (item.get("cdealType") or "").strip().upper() == "O":
        return None  # 해제된 거래

    name = (item.get("aptNm") or "").strip()
    dong = (item.get("umdNm") or "").strip()
    price = _to_int(item.get("dealAmount"))
    year, month, day = (_to_int(item.get(k)) for k in ("dealYear", "dealMonth", "dealDay"))
    try:
        area = float((item.get("excluUseAr") or "").strip())
    except ValueError:
        area = 0.0

    if not name or not dong or not price or price <= 0 or area <= 0 or not (year and month and day):
        return None
    try:
        deal_date = date(year, month, day)
    except ValueError:
        return None

    return CleanDeal(
        apartment=name,
        dong=dong,
        build_year=_to_int(item.get("buildYear")),
        deal_date=deal_date,
        price=price,
        area=round(area, 2),
        floor=_to_int(item.get("floor")),
        price_per_pyeong=round(price / (area / PYEONG_M2), 1),
    )


def clean_items(items: list[dict]) -> list[CleanDeal]:
    cleaned = [d for d in (clean_item(i) for i in items) if d is not None]
    dropped = len(items) - len(cleaned)
    if dropped:
        logger.info("정제: %d건 중 %d건 제외 (해제거래/결측/형식오류)", len(items), dropped)
    return cleaned
