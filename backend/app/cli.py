"""명령줄 실행 도구.

사용 예
  python -m app.cli collect --start 202501 --end 202506            # 서울 전체 수집
  python -m app.cli collect --start 202506 --end 202506 --lawd 11680 # 강남구만
  python -m app.cli insight --months 6                               # 서울 전체 + 25개 구 인사이트
  python -m app.cli run --months 12                                  # 수집+인사이트 한 번에 (스케줄러용)
  python -m app.cli seed-sample                                      # API 키 없이 UI 개발용 가짜 데이터
"""
import argparse
import json
import logging
import random
from datetime import date, timedelta

from app.core.logging_config import setup_logging
from app.core.regions import SEOUL_REGIONS
from app.database import SessionLocal, init_db
from app.services.cleaner import PYEONG_M2, CleanDeal
from app.services.insight_service import generate_insight
from app.services.loader import ensure_regions, load_deals
from app.services.pipeline import run_collect, run_full

logger = logging.getLogger("cli")


def seed_sample(months: int = 12, seed: int = 42) -> int:
    """⚠️ 실제 데이터가 아닌 '샘플단지' 가짜 거래. 화면 개발·시연 리허설용."""
    rnd = random.Random(seed)
    end = date.today().replace(day=1) - timedelta(days=1)
    start = (end.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    total = 0
    with SessionLocal() as db:
        ensure_regions(db)
        for i, code in enumerate(SEOUL_REGIONS):
            base_ppp = rnd.uniform(2500, 8000)  # 만원/평
            trend = rnd.uniform(-0.01, 0.02)    # 월 변화율
            deals = []
            d = start
            while d <= end:
                months_from_start = (d.year - start.year) * 12 + d.month - start.month
                ppp = base_ppp * (1 + trend) ** months_from_start
                for _ in range(rnd.randint(0, 2)):
                    area = rnd.choice([59.9, 84.9, 114.8])
                    price = int(ppp * rnd.uniform(0.85, 1.15) * area / PYEONG_M2)
                    deals.append(CleanDeal(
                        apartment=f"샘플단지{rnd.randint(1, 5)}", dong=f"샘플{i + 1}동", build_year=2005,
                        deal_date=d, price=price, area=area, floor=rnd.randint(1, 25),
                        price_per_pyeong=round(price / (area / PYEONG_M2), 1),
                    ))
                d += timedelta(days=1)
            total += load_deals(db, code, deals)
    return total


def main() -> None:
    setup_logging()
    init_db()
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("collect", help="실거래가 수집")
    p.add_argument("--start", required=True, help="YYYYMM")
    p.add_argument("--end", required=True, help="YYYYMM")
    p.add_argument("--lawd", nargs="*", help="법정동코드 5자리 (생략 시 서울 25개 구)")

    p = sub.add_parser("insight", help="인사이트 생성")
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--lawd", nargs="*", help="생략 시 서울 전체 + 25개 구")

    p = sub.add_parser("run", help="최근 N개월 수집 + 인사이트")
    p.add_argument("--months", type=int, default=12)

    sub.add_parser("seed-sample", help="가짜 샘플 데이터 적재 (UI 개발용)")

    args = parser.parse_args()
    with SessionLocal() as db:
        if args.cmd == "collect":
            result = run_collect(db, args.start, args.end, args.lawd)
        elif args.cmd == "insight":
            codes = args.lawd or [None, *SEOUL_REGIONS]
            result = {"generated": sum(1 for c in codes if generate_insight(db, args.months, c))}
        elif args.cmd == "run":
            result = run_full(db, args.months)
        else:
            result = {"inserted_rows": seed_sample()}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
