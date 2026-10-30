"""API 요청/응답 스키마 (Pydantic)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lawd_cd: str
    sigungu: str


class TransactionOut(BaseModel):
    deal_date: date
    sigungu: str
    dong: str
    apartment: str
    area: float
    floor: int | None
    price: int
    price_per_pyeong: float


class MonthlyStat(BaseModel):
    month: str  # YYYY-MM
    sigungu: str
    deal_count: int
    avg_price: float
    avg_price_per_pyeong: float


class RegionSummary(BaseModel):
    sigungu: str
    deal_count: int
    avg_price: float
    avg_price_per_pyeong: float


class InsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sigungu: str | None
    period_start: date
    period_end: date
    summary_text: str
    source: str
    prompt_version: str
    created_at: datetime


class InsightRequest(BaseModel):
    lawd_cd: str | None = Field(default=None, description="없으면 서울 전체")
    months: int = Field(default=6, ge=2, le=36)


class CollectRequest(BaseModel):
    lawd_cds: list[str] | None = Field(default=None, description="없으면 서울 25개 구 전체")
    start_ym: str = Field(pattern=r"^\d{6}$", examples=["202501"])
    end_ym: str = Field(pattern=r"^\d{6}$", examples=["202506"])


class CollectResult(BaseModel):
    total_jobs: int
    success: int
    failed: int
    inserted_rows: int


class PipelineLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    lawd_cd: str
    deal_ym: str
    status: str
    fetched_rows: int
    inserted_rows: int
    error_msg: str | None
    run_at: datetime
