import logging

from .config import get_settings


def setup_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    # 외부 라이브러리 로그는 조용히
    for noisy in ("httpx", "urllib3", "apscheduler", "alembic", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # yfinance 는 대체 소스로만 쓰여 실패가 정상일 수 있다 (요약은 issue_stream 로그에 남김)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
