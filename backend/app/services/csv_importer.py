"""인증키 없이 실제 데이터 넣기 — 국토부 실거래가 공개시스템 CSV 가져오기.

rt.molit.go.kr 에서 '아파트 매매' CSV를 내려받으면 앞부분에 안내 문구가 여러 줄 있고,
그 아래에 시군구 / 단지명 / 전용면적 / 계약년월 / 계약일 / 거래금액 / 층 / 건축년도 /
해제사유발생일 ... 같은 열이 이어집니다. 인코딩은 보통 CP949(EUC-KR)입니다.

CSV 한 행을 API 응답과 같은 키(aptNm, dealAmount ...)로 바꾼 뒤
기존 정제(cleaner)·적재(loader) 코드를 그대로 재사용합니다.
"""
import csv
import io
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions import CleanError
from app.core.regions import SEOUL_REGIONS
from app.services.cleaner import clean_items
from app.services.loader import ensure_regions, load_deals

logger = logging.getLogger(__name__)

_GU_TO_CODE = {name: code for code, name in SEOUL_REGIONS.items()}

# 열 이름에 들어 있는 핵심 단어 → 내부 키 (열 이름이 조금 달라도 찾을 수 있게)
_COLUMN_KEYWORDS = {
    "sigungu": ["시군구"],
    "apt": ["단지명"],
    "area": ["전용면적"],
    "ym": ["계약년월"],
    "day": ["계약일"],
    "price": ["거래금액"],
    "floor": ["층"],
    "build_year": ["건축년도"],
    "cancel": ["해제사유발생일", "해제여부"],
}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CleanError(f"{path.name}: 인코딩을 알 수 없습니다 (UTF-8/CP949 아님)")


def _find_columns(header: list[str]) -> dict[str, int]:
    cols: dict[str, int] = {}
    for key, words in _COLUMN_KEYWORDS.items():
        for i, h in enumerate(header):
            name = h.replace(" ", "")
            if any(w in name for w in words):
                # '층'은 '건축년도' 등과 겹치지 않도록 정확히 일치하는 열 우선
                if key == "floor" and name != "층":
                    continue
                cols[key] = i
                break
    return cols


def parse_molit_csv(path: Path) -> dict[str, list[dict]]:
    """CSV → {lawd_cd: [API 형식 item, ...]}. 서울 이외 지역은 건너뜁니다."""
    text = _read_text(path)
    rows = list(csv.reader(io.StringIO(text)))

    header_idx = next(
        (i for i, r in enumerate(rows) if any("단지명" in c for c in r) and any("거래금액" in c for c in r)),
        None,
    )
    if header_idx is None:
        raise CleanError(f"{path.name}: '단지명'과 '거래금액' 열이 있는 헤더를 찾지 못했습니다")
    cols = _find_columns(rows[header_idx])
    missing = [k for k in ("sigungu", "apt", "area", "ym", "day", "price") if k not in cols]
    if missing:
        raise CleanError(f"{path.name}: 필수 열을 찾지 못했습니다 {missing} / 헤더={rows[header_idx]}")

    def cell(r: list[str], key: str) -> str:
        i = cols.get(key)
        return r[i].strip() if i is not None and i < len(r) else ""

    grouped: dict[str, list[dict]] = defaultdict(list)
    skipped_region = 0
    for r in rows[header_idx + 1:]:
        if not r or not cell(r, "apt"):
            continue
        parts = cell(r, "sigungu").split()  # 예: "서울특별시 강남구 개포동"
        if len(parts) < 3 or parts[1] not in _GU_TO_CODE:
            skipped_region += 1
            continue
        ym = cell(r, "ym")  # 예: 202509
        cancel = cell(r, "cancel")
        grouped[_GU_TO_CODE[parts[1]]].append({
            "aptNm": cell(r, "apt"),
            "umdNm": parts[2],
            "excluUseAr": cell(r, "area"),
            "dealYear": ym[:4],
            "dealMonth": ym[4:6],
            "dealDay": cell(r, "day"),
            "dealAmount": cell(r, "price"),
            "floor": cell(r, "floor"),
            "buildYear": cell(r, "build_year"),
            # 해제사유발생일이 채워져 있으면 취소된 거래
            "cdealType": "O" if cancel and cancel != "-" else "",
        })
    if skipped_region:
        logger.info("%s: 서울 25개 구가 아닌 %d행 건너뜀", path.name, skipped_region)
    return grouped


def import_csv_files(db: Session, paths: list[Path]) -> dict:
    ensure_regions(db)
    result = {"files": 0, "rows": 0, "inserted_rows": 0}
    for path in paths:
        grouped = parse_molit_csv(path)
        for code, items in grouped.items():
            result["rows"] += len(items)
            result["inserted_rows"] += load_deals(db, code, clean_items(items))
        result["files"] += 1
        logger.info("CSV 가져오기 완료: %s", path.name)
    return result
