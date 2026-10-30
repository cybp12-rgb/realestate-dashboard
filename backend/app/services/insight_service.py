"""5단계: 인사이트 생성 — 집계값 → LLM → insight 테이블 저장.

LLM이 설정되지 않았거나 호출에 실패하면 규칙 기반 문장(fallback)으로 대체해
대시보드가 비지 않도록 합니다. source 컬럼으로 어느 쪽인지 구분됩니다.
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import LLMError
from app.models import Insight, Region
from app.services.aggregator import build_insight_input
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

# 프롬프트를 바꿀 때마다 버전을 올리면 결과 비교(선택 구현: 프롬프트 실험)에 활용할 수 있습니다.
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """너는 한국 아파트 매매 시장을 분석하는 데이터 애널리스트다.
규칙:
- 사용자가 제공한 JSON 숫자만 근거로 작성한다. 제공되지 않은 수치·뉴스·정책은 지어내지 않는다.
- 한국어로, 4~5개의 짧은 bullet(- 로 시작)로 작성한다.
- 1) 가격 추세 2) 거래량 변화 3) 주목할 단지/지역 4) 해석 시 유의점 순서로 쓴다.
- 금액은 '억/만원' 단위로 읽기 쉽게 바꾼다. (예: 125000만원 → 12억 5,000만원)
- 투자 권유나 단정적 전망은 하지 않는다."""


def _format_manwon(v: float) -> str:
    v = int(round(v))
    eok, man = divmod(v, 10000)
    if eok and man:
        return f"{eok}억 {man:,}만원"
    return f"{eok}억원" if eok else f"{man:,}만원"


def fallback_summary(data: dict) -> str:
    """LLM 없이 만드는 규칙 기반 요약."""
    m = data["monthly"]
    chg = data["price_per_pyeong_change_pct"]
    trend = "상승" if chg > 0 else "하락" if chg < 0 else "보합"
    lines = [
        f"- {data['region']} 평당 평균가는 {m[0]['month']} {m[0]['avg_price_per_pyeong']:,.0f}만원에서 "
        f"{m[-1]['month']} {m[-1]['avg_price_per_pyeong']:,.0f}만원으로 {abs(chg)}% {trend}했습니다.",
        f"- 거래량은 {data['deal_count_first_month']:,}건 → {data['deal_count_last_month']:,}건입니다.",
    ]
    if data.get("top_apartments_by_deals"):
        t = data["top_apartments_by_deals"][0]
        lines.append(f"- 거래가 가장 많은 단지는 {t['dong']} {t['name']}({t['deal_count']}건, "
                     f"평균 {_format_manwon(t['avg_price'])})입니다.")
    lines.append("- 마지막 달은 신고 기한(계약 후 30일) 때문에 거래량이 적게 집계될 수 있습니다.")
    return "\n".join(lines)


def generate_insight(db: Session, months: int = 6, lawd_cd: str | None = None,
                     llm: LLMClient | None = None) -> Insight | None:
    payload = build_insight_input(db, months, lawd_cd)
    if payload is None:
        logger.warning("인사이트 생성 불가: 데이터 없음 (lawd_cd=%s)", lawd_cd)
        return None
    data = payload["data"]

    llm = llm or LLMClient()
    try:
        user_prompt = "다음 집계 데이터를 분석해 줘.\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"
        text, source = llm.chat(SYSTEM_PROMPT, user_prompt), "llm"
    except LLMError as e:
        logger.warning("LLM 사용 불가 → fallback 요약 사용: %s", e)
        text, source = fallback_summary(data), "fallback"

    region_id = None
    if lawd_cd:
        region_id = db.scalar(select(Region.id).where(Region.lawd_cd == lawd_cd))

    insight = Insight(
        region_id=region_id,
        period_start=payload["period_start"],
        period_end=payload["period_end"],
        summary_text=text,
        source=source,
        prompt_version=PROMPT_VERSION if source == "llm" else "rule",
    )
    db.add(insight)
    db.commit()
    db.refresh(insight)
    logger.info("인사이트 저장 id=%d region=%s source=%s", insight.id, data["region"], source)
    return insight
