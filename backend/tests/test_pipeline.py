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


def test_import_molit_csv(db, tmp_path):
    from app.services.csv_importer import import_csv_files

    lines = [
        "□ 본 서비스에서 제공하는 정보는 법적인 효력이 없으므로 참고용으로만 활용하시기 바랍니다.",
        "□ 검색조건",
        "",
        '"NO","시군구","번지","본번","부번","단지명","전용면적(㎡)","계약년월","계약일","거래금액(만원)","동","층","매수자","매도자","건축년도","도로명","해제사유발생일","거래유형","중개사소재지","등기일자"',
        '"1","서울특별시 강남구 개포동","12","0012","0000","개포테스트","84.99","202509","15","250,000","","10","개인","개인","2019","개포로 1","-","중개거래","서울 강남구","-"',
        '"2","서울특별시 강남구 개포동","12","0012","0000","개포테스트","84.99","202509","20","255,000","","12","개인","개인","2019","개포로 1","20251001","중개거래","서울 강남구","-"',
        '"3","서울특별시 마포구 아현동","1","0001","0000","아현테스트","59.9","202509","3","130,000","","5","개인","개인","2015","아현로 1","-","직거래","-","-"',
        '"4","경기도 성남시분당구 정자동","1","0001","0000","분당테스트","84.9","202509","3","150,000","","5","개인","개인","2015","정자로 1","-","직거래","-","-"',
    ]
    f = tmp_path / "apt.csv"
    f.write_bytes("\n".join(lines).encode("cp949"))
    result = import_csv_files(db, [f])
    # 서울 3행 중 해제 1건 제외 → 2건, 경기도는 건너뜀
    assert result == {"files": 1, "rows": 3, "inserted_rows": 2}
    assert import_csv_files(db, [f])["inserted_rows"] == 0  # 중복 없음
