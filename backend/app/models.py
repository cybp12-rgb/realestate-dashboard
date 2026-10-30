"""ORM 모델 = ERD.

region 1 ── N apartment 1 ── N transaction
region 1 ── N insight          (region_id NULL = 서울 전체)
pipeline_log                   (수집 이력, 독립)
"""
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Region(Base):
    __tablename__ = "region"

    id: Mapped[int] = mapped_column(primary_key=True)
    lawd_cd: Mapped[str] = mapped_column(String(5), unique=True, index=True)
    sido: Mapped[str] = mapped_column(String(20), default="서울특별시")
    sigungu: Mapped[str] = mapped_column(String(20))

    apartments: Mapped[list["Apartment"]] = relationship(back_populates="region")


class Apartment(Base):
    __tablename__ = "apartment"
    __table_args__ = (UniqueConstraint("region_id", "name", "dong", name="uq_apartment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("region.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    dong: Mapped[str] = mapped_column(String(50))  # 법정동 (예: 역삼동)
    build_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    region: Mapped[Region] = relationship(back_populates="apartments")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="apartment")


class Transaction(Base):
    __tablename__ = "transaction"
    # 같은 거래가 재수집돼도 중복 적재되지 않도록 자연키에 UNIQUE
    __table_args__ = (
        UniqueConstraint("apartment_id", "deal_date", "area", "floor", "price", name="uq_transaction"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    apartment_id: Mapped[int] = mapped_column(ForeignKey("apartment.id"), index=True)
    deal_date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[int] = mapped_column(Integer)  # 만원
    area: Mapped[float] = mapped_column(Float)   # 전용면적 ㎡
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_per_pyeong: Mapped[float] = mapped_column(Float)  # 만원/평 (가공 컬럼)

    apartment: Mapped[Apartment] = relationship(back_populates="transactions")


class Insight(Base):
    __tablename__ = "insight"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region.id"), nullable=True, index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    summary_text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))  # "llm" | "fallback"
    prompt_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    region: Mapped[Region | None] = relationship()


class PipelineLog(Base):
    __tablename__ = "pipeline_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    lawd_cd: Mapped[str] = mapped_column(String(5))
    deal_ym: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(10))  # success | fail
    fetched_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
