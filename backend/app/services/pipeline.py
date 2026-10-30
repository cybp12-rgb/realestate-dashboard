"""전체 파이프라인: 수집 → 정제 → 적재 → (인사이트 생성).

지역·월 단위 작업 하나가 실패해도 나머지는 계속 진행하고,
결과는 pipeline_log 테이블과 로그 파일에 남깁니다.
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import PipelineError
from app.core.regions import SEOUL_REGIONS
from app.models import PipelineLog
from app.services.cleaner import clean_items
from app.services.collector import AptTradeCollector
from app.services.insight_service import generate_insight
from app.services.loader import ensure_regions, load_deals

logger = logging.getLogger(__name__)


def month_range(start_ym: str, end_ym: str) -> list[str]:
    """'202501', '202503' → ['202501', '202502', '202503']"""
    y, m = int(start_ym[:4]), int(start_ym[4:])
    ey, em = int(end_ym[:4]), int(end_ym[4:])
    if (y, m) > (ey, em):
        raise ValueError("start_ym이 end_ym보다 늦습니다")
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def recent_months(n: int, today: date | None = None) -> tuple[str, str]:
    """오늘 기준 최근 n개월 (start_ym, end_ym)."""
    today = today or date.today()
    y, m = today.year, today.month - (n - 1)
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}{m:02d}", f"{today.year:04d}{today.month:02d}"


def run_collect(db: Session, start_ym: str, end_ym: str,
                lawd_cds: list[str] | None = None,
                collector: AptTradeCollector | None = None) -> dict:
    ensure_regions(db)
    collector = collector or AptTradeCollector()
    lawd_cds = lawd_cds or list(SEOUL_REGIONS)
    months = month_range(start_ym, end_ym)

    result = {"total_jobs": 0, "success": 0, "failed": 0, "inserted_rows": 0}
    for code in lawd_cds:
        for ym in months:
            result["total_jobs"] += 1
            log = PipelineLog(lawd_cd=code, deal_ym=ym, status="fail")
            try:
                raw = collector.fetch_month(code, ym)
                deals = clean_items(raw)
                inserted = load_deals(db, code, deals)
                log.status, log.fetched_rows, log.inserted_rows = "success", len(raw), inserted
                result["success"] += 1
                result["inserted_rows"] += inserted
            except PipelineError as e:
                db.rollback()
                log.error_msg = str(e)
                result["failed"] += 1
                logger.error("작업 실패 lawd_cd=%s deal_ym=%s: %s", code, ym, e)
            except Exception as e:  # 예상 못 한 오류도 기록하고 다음 작업 진행
                db.rollback()
                log.error_msg = f"{type(e).__name__}: {e}"
                result["failed"] += 1
                logger.exception("예상치 못한 오류 lawd_cd=%s deal_ym=%s", code, ym)
            db.add(log)
            db.commit()

    logger.info("수집 파이프라인 종료: %s", result)
    return result


def run_full(db: Session, months: int = 12, insight_months: int = 6) -> dict:
    """최근 N개월 수집 + 서울 전체/구별 인사이트 생성. (스케줄러·CLI용)"""
    start_ym, end_ym = recent_months(months)
    result = run_collect(db, start_ym, end_ym)
    generated = 0
    for code in [None, *SEOUL_REGIONS]:
        if generate_insight(db, insight_months, code):
            generated += 1
    result["insights"] = generated
    return result
