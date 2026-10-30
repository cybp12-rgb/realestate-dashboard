"""로깅 설정: 콘솔 + 파일(회전) 동시 기록."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import get_settings

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    if root.handlers:  # 중복 설정 방지 (uvicorn reload 등)
        return
    root.setLevel(settings.log_level.upper())

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)
