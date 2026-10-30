import os
import sys
from pathlib import Path

# 테스트는 인메모리 대신 임시 SQLite 파일 사용 (설정 로드 전에 지정)
_TMP_DB = Path(__file__).parent / "_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["DATA_GO_KR_SERVICE_KEY"] = "test-key"
os.environ["LLM_BASE_URL"] = ""
os.environ["LOG_FILE"] = str(Path(__file__).parent / "_test.log")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        yield session


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    for p in (_TMP_DB, Path(os.environ["LOG_FILE"])):
        p.unlink(missing_ok=True)
