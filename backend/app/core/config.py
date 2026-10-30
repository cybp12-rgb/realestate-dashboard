"""환경 변수 기반 설정.

.env 파일 또는 OS 환경 변수에서 값을 읽습니다. (.env.example 참고)
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"),env_file_encoding="utf-8", extra="ignore")

    # --- DB ---
    # 로컬 개발: SQLite / Docker: PostgreSQL
    database_url: str = "sqlite:///./realestate.db"

    # --- 공공데이터포털 ---
    # 공공데이터포털 마이페이지의 "일반 인증키(Decoding)" 값을 넣으세요.
    data_go_kr_service_key: str = ""
    apt_trade_api_url: str = (
        "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
    )
    api_timeout_sec: float = 10.0
    api_max_retries: int = 3
    api_page_size: int = 1000

    # --- LLM (제공된 LLM API, OpenAI 호환 형식 가정) ---
    llm_base_url: str = ""          # 예: https://<제공된-서버>/v1
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_sec: float = 60.0

    # --- 기타 ---
    log_level: str = "INFO"
    log_file: str = "logs/app.log"


@lru_cache
def get_settings() -> Settings:
    return Settings()
