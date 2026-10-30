"""1단계: 수집 — 국토교통부 아파트 매매 실거래가 상세 자료 API 호출.

요청 파라미터
- serviceKey : 인증키 (Decoding 키)
- LAWD_CD    : 법정동코드 앞 5자리 (예: 11680 = 강남구)
- DEAL_YMD   : 계약년월 6자리 (예: 202501)
- pageNo / numOfRows : 페이지네이션
"""
import logging
import time
import xml.etree.ElementTree as ET

import httpx

from app.core.config import get_settings
from app.core.exceptions import CollectError

logger = logging.getLogger(__name__)

# 정상 응답 코드 (API 버전에 따라 "00" 또는 "000")
_OK_CODES = {"00", "000"}


def parse_response(xml_text: str) -> tuple[list[dict], int]:
    """XML 응답 → (item 딕셔너리 목록, totalCount). 오류 응답이면 CollectError."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise CollectError(f"XML 파싱 실패: {e} / 응답 앞부분: {xml_text[:200]!r}") from e

    # 인증키 오류 등은 <OpenAPI_ServiceResponse> 형식으로 내려옵니다.
    if root.tag == "OpenAPI_ServiceResponse":
        msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "알 수 없는 오류"
        raise CollectError(f"공공데이터포털 오류: {msg}")

    code = (root.findtext("./header/resultCode") or "").strip()
    if code not in _OK_CODES:
        msg = root.findtext("./header/resultMsg")
        raise CollectError(f"API 오류 응답 resultCode={code!r}, resultMsg={msg!r}")

    items = [
        {child.tag: (child.text or "").strip() for child in item}
        for item in root.findall("./body/items/item")
    ]
    total = int(root.findtext("./body/totalCount") or 0)
    return items, total


class AptTradeCollector:
    def __init__(self, client: httpx.Client | None = None):
        self.settings = get_settings()
        if not self.settings.data_go_kr_service_key:
            raise CollectError("DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다 (.env 확인)")
        self.client = client or httpx.Client(timeout=self.settings.api_timeout_sec)

    def _request(self, params: dict) -> str:
        """재시도(지수 백오프) 포함 단일 요청."""
        last_err: Exception | None = None
        for attempt in range(1, self.settings.api_max_retries + 1):
            try:
                resp = self.client.get(self.settings.apt_trade_api_url, params=params)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("서버 오류", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.text
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_err = e
                wait = 2 ** (attempt - 1)
                logger.warning("API 요청 실패 (%d/%d): %s → %ds 후 재시도",
                               attempt, self.settings.api_max_retries, e, wait)
                time.sleep(wait)
        raise CollectError(f"API 요청 최종 실패: {last_err}")

    def fetch_month(self, lawd_cd: str, deal_ym: str) -> list[dict]:
        """한 지역·한 달치 거래를 모든 페이지에 걸쳐 수집."""
        page, size = 1, self.settings.api_page_size
        results: list[dict] = []
        while True:
            params = {
                "serviceKey": self.settings.data_go_kr_service_key,
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": deal_ym,
                "pageNo": page,
                "numOfRows": size,
            }
            items, total = parse_response(self._request(params))
            results.extend(items)
            if not items or len(results) >= total:
                break
            page += 1
        logger.info("수집 완료 lawd_cd=%s deal_ym=%s rows=%d", lawd_cd, deal_ym, len(results))
        return results
