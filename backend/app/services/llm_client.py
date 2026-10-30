"""LLM API 클라이언트.

과정에서 '제공된 LLM API'의 형식이 OpenAI 호환(/v1/chat/completions)이라고 가정했습니다.
형식이 다르면 이 파일의 `chat()`만 수정하면 나머지 코드는 그대로 동작합니다.
"""
import logging

import httpx

from app.core.config import get_settings
from app.core.exceptions import LLMError

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, client: httpx.Client | None = None):
        self.settings = get_settings()
        self.client = client or httpx.Client(timeout=self.settings.llm_timeout_sec)

    @property
    def configured(self) -> bool:
        s = self.settings
        return bool(s.llm_base_url and s.llm_model)

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        if not self.configured:
            raise LLMError("LLM_BASE_URL / LLM_MODEL이 설정되지 않았습니다")

        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        try:
            resp = self.client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise LLMError(f"LLM HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except (httpx.TransportError, KeyError, IndexError, ValueError) as e:
            raise LLMError(f"LLM 호출/응답 파싱 실패: {e}") from e

        if not content or not content.strip():
            raise LLMError("LLM 응답이 비어 있습니다")
        return content.strip()
