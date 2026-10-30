"""FastAPI 진입점.  실행: uvicorn app.main:app --reload"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging_config import setup_logging
from app.database import SessionLocal, init_db
from app.routers import data, insights, pipeline
from app.services.loader import ensure_regions

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        ensure_regions(db)
    logger.info("서버 시작: DB 초기화 완료")
    yield


app = FastAPI(title="서울 아파트 시세 인사이트 API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """처리되지 않은 예외는 스택트레이스를 로그에 남기고 500으로 응답."""
    logger.exception("처리되지 않은 오류: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "서버 내부 오류가 발생했습니다."})


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


app.include_router(data.router)
app.include_router(insights.router)
app.include_router(pipeline.router)
