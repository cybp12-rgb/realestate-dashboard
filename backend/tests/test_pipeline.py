from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import CollectError
from app.services.cleaner import clean_items
from app.services.collector import AptTradeCollector, parse_response
from app.services.insight_service import generate_insight
from app.services.loader import ensure_regions, load_deals
from app.services.pipeline import month_range, run_collect

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_response.xml").read_text(encoding="utf-8")


def test_parse_and_clean():
    items, total = parse_response(FIXTURE)
    assert total == 4 and len(items) == 4
    deals = clean_items(items)
    # 해제거래 1건 + 단지명 결측 1건 제외
    assert len(deals) == 2
    d = deals[0]
    assert d.price == 185000 and d.area == 84.97 and d.dong == "역삼동"
    assert d.price_per_pyeong == pytest.approx(185000 / (84.97 / 3.3058), rel=1e-3)


def test_error_response():
    err = ("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR"
           "</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>")
    with pytest.raises(CollectError, match="SERVICE_KEY"):
        parse_response(err)


def test_month_range():
    assert month_range("202411", "202502") == ["202411", "202412", "202501", "202502"]


def test_load_is_idempotent(db):
    ensure_regions(db)
    deals = clean_items(parse_response(FIXTURE)[0])
    assert load_deals(db, "11680", deals) == 2
    assert load_deals(db, "11680", deals) == 0  # 재적재 시 중복 없음


def test_run_collect_with_mock_api(db):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["LAWD_CD"] == "11110":
            return httpx.Response(200, text="<broken")
        return httpx.Response(200, text=FIXTURE)

    collector = AptTradeCollector(client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = run_collect(db, "202503", "202503", ["11680", "11110"], collector=collector)
    assert result == {"total_jobs": 2, "success": 1, "failed": 1, "inserted_rows": 2}


def test_insight_fallback_and_api(db):
    ensure_regions(db)
    load_deals(db, "11680", clean_items(parse_response(FIXTURE)[0]))
    ins = generate_insight(db, months=3, lawd_cd="11680")
    assert ins is not None and ins.source == "fallback" and "강남구" in ins.summary_text

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert len(client.get("/transactions", params={"lawd_cd": "11680"}).json()) == 2
        stats = client.get("/stats/monthly", params={"lawd_cd": "11680"}).json()
        assert stats[0]["month"] == "2025-03" and stats[0]["deal_count"] == 2
        latest = client.get("/insights/latest", params={"lawd_cd": "11680"}).json()
        assert latest["sigungu"] == "강남구"
        r = client.post("/insights/generate", json={"months": 3})
        assert r.status_code == 200 and r.json()["sigungu"] is None
    app.dependency_overrides.clear()


def test_insight_with_mock_llm(db, monkeypatch):
    from app.core.config import get_settings
    from app.services.llm_client import LLMClient

    ensure_regions(db)
    load_deals(db, "11680", clean_items(parse_response(FIXTURE)[0]))
    s = get_settings()
    monkeypatch.setattr(s, "llm_base_url", "http://llm.test/v1")
    monkeypatch.setattr(s, "llm_model", "test-model")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "- 테스트 인사이트"}}]})

    llm = LLMClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    ins = generate_insight(db, months=3, lawd_cd="11680", llm=llm)
    assert ins.source == "llm" and ins.summary_text == "- 테스트 인사이트" and ins.prompt_version == "v1"
