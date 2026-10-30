"""Streamlit 대시보드 — FastAPI 백엔드를 호출해 데이터와 인사이트를 시각화.

실행: streamlit run app.py   (API_BASE_URL 환경 변수로 백엔드 주소 지정)
"""
import os

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="서울 아파트 시세 인사이트", page_icon="🏠", layout="wide")


@st.cache_data(ttl=300)
def get(path: str, **params):
    try:
        r = httpx.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"백엔드 요청 실패: {path} ({e})")
        return None


def fmt_eok(manwon: float) -> str:
    return f"{manwon / 10000:,.2f}억"


# ---------------- 사이드바 ----------------
st.sidebar.title("🏠 필터")
regions = get("/regions") or []
options = {"서울 전체": None} | {r["sigungu"]: r["lawd_cd"] for r in regions}
region_name = st.sidebar.selectbox("지역", list(options))
lawd_cd = options[region_name]
months = st.sidebar.slider("조회 기간 (개월)", 3, 24, 12)

if st.sidebar.button("🔄 인사이트 새로 생성"):
    with st.spinner("LLM이 분석 중..."):
        r = httpx.post(f"{API}/insights/generate", json={"lawd_cd": lawd_cd, "months": min(months, 12)}, timeout=120)
    if r.status_code == 200:
        st.cache_data.clear()
        st.sidebar.success("생성 완료")
    else:
        st.sidebar.error(r.json().get("detail", "생성 실패"))

# ---------------- 본문 ----------------
st.title(f"{region_name} 아파트 매매 시세")

monthly = pd.DataFrame(get("/stats/monthly", lawd_cd=lawd_cd, months=months) or [])
if monthly.empty:
    st.info("데이터가 없습니다. 백엔드에서 `python -m app.cli collect ...` 또는 `seed-sample`을 먼저 실행하세요.")
    st.stop()

# 서울 전체면 월별로 가중 평균
monthly["ppp_x_cnt"] = monthly["avg_price_per_pyeong"] * monthly["deal_count"]
monthly["price_x_cnt"] = monthly["avg_price"] * monthly["deal_count"]
agg = monthly.groupby("month", as_index=False)[["deal_count", "ppp_x_cnt", "price_x_cnt"]].sum()
agg["avg_ppp"] = agg["ppp_x_cnt"] / agg["deal_count"]
agg["avg_price"] = agg["price_x_cnt"] / agg["deal_count"]

# KPI
last, first = agg.iloc[-1], agg.iloc[0]
c1, c2, c3, c4 = st.columns(4)
c1.metric("최근월 평균 거래가", fmt_eok(last["avg_price"]))
c2.metric("최근월 평당가", f"{last['avg_ppp']:,.0f}만원",
          f"{(last['avg_ppp'] / first['avg_ppp'] - 1) * 100:+.1f}% (기간 대비)")
c3.metric("최근월 거래량", f"{int(last['deal_count']):,}건")
c4.metric("기간 총 거래량", f"{int(agg['deal_count'].sum()):,}건")

# 인사이트
st.subheader("🤖 AI 인사이트")
insight = get("/insights/latest", lawd_cd=lawd_cd)
if insight:
    badge = "LLM 생성" if insight["source"] == "llm" else "규칙 기반 (LLM 미연결)"
    st.caption(f"{insight['period_start']} ~ {insight['period_end']} · {badge} · 프롬프트 {insight['prompt_version']} "
               f"· 생성 {insight['created_at'][:16].replace('T', ' ')}")
    st.markdown(insight["summary_text"])
else:
    st.info("아직 인사이트가 없습니다. 사이드바의 '인사이트 새로 생성'을 눌러 주세요.")

# 차트
left, right = st.columns(2)
with left:
    st.subheader("월별 평당가 추이")
    fig = px.line(agg, x="month", y="avg_ppp", markers=True, labels={"month": "", "avg_ppp": "만원/평"})
    st.plotly_chart(fig, use_container_width=True)
with right:
    st.subheader("월별 거래량")
    fig = px.bar(agg, x="month", y="deal_count", labels={"month": "", "deal_count": "건"})
    st.plotly_chart(fig, use_container_width=True)

if lawd_cd is None:
    st.subheader("구별 평당가 비교 (최근 3개월)")
    summary = pd.DataFrame(get("/stats/regions", months=3) or [])
    if not summary.empty:
        fig = px.bar(summary.sort_values("avg_price_per_pyeong"), x="avg_price_per_pyeong", y="sigungu",
                     orientation="h", labels={"avg_price_per_pyeong": "만원/평", "sigungu": ""}, height=650)
        st.plotly_chart(fig, use_container_width=True)

st.subheader("최근 거래")
tx = pd.DataFrame(get("/transactions", lawd_cd=lawd_cd, limit=100) or [])
if not tx.empty:
    tx = tx.rename(columns={"deal_date": "계약일", "sigungu": "구", "dong": "동", "apartment": "단지",
                            "area": "전용(㎡)", "floor": "층", "price": "거래가(만원)", "price_per_pyeong": "평당가(만원)"})
    st.dataframe(tx, use_container_width=True, hide_index=True)

st.caption("출처: 국토교통부 아파트 매매 실거래가 상세 자료 (공공데이터포털)")
