"""환경 설정. 모든 값은 .env 또는 환경변수에서 읽는다.

유료 구성요소는 두 겹으로 막는다.
  1) provider 값이 유료(openai, anthropic)여야 하고
  2) ALLOW_PAID_APIS=true 여야 한다.
둘 중 하나라도 아니면 require_paid()가 예외를 던져 실수로 과금되는 일을 막는다.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "config"

PAID_PROVIDERS = {"openai", "anthropic"}

# 기본 DB: 프로젝트 폴더 안의 SQLite 파일 (설치·Docker 불필요)
DEFAULT_SQLITE_PATH = ROOT_DIR / "data" / "issue_stream.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
# 예전 .env.example 의 Docker Postgres 주소. 이 주소로 연결이 안 되면 SQLite 로 자동 대체한다.
LEGACY_DOCKER_PG_URL = "postgresql+psycopg://issue:issue@localhost:5432/issue_stream"

# 임베딩 provider별 클러스터 임계값 시작점 (같은 사건 제목쌍 vs 다른 사건 제목쌍 측정 기준)
DEFAULT_THRESHOLDS = {"hashing": 0.35, "local": 0.86, "openai": 0.60}


class PaidApiDisabledError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL

    allow_paid_apis: bool = False

    embedding_provider: Literal["hashing", "local", "openai"] = "hashing"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384

    summarizer_provider: Literal["extractive", "ollama", "anthropic"] = "extractive"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    anthropic_model: str = "claude-haiku-4-5"

    sentiment_provider: Literal["lexicon", "hf_local", "summarizer"] = "lexicon"

    dart_api_key: str = ""
    ecos_api_key: str = ""
    fred_api_key: str = ""
    kosis_api_key: str = ""
    naver_client_id: str = ""
    naver_client_secret: str = ""
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_type: Literal["paper", "real"] = "paper"

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_importance_threshold: float = 70.0

    cluster_sim_threshold: float | None = None   # 비우면 임베딩 provider별 기본값
    cluster_window_hours: int = 48
    dedupe_hamming_threshold: int = 3
    resummarize_growth_ratio: float = 0.3

    fetch_article_body: bool = False
    article_body_ttl_hours: int = 24
    article_retention_days: int = 180

    session_days: int = 30          # 로그인 유지 기간
    signup_enabled: bool = True     # false 면 가입 화면을 닫고 CLI(issue-stream user add)로만 계정 생성
    signup_invite_code: str = ""    # 값이 있으면 이 코드를 아는 사람만 가입
    max_watchlist_per_user: int = 50  # 계정별 관심종목 상한 (수집 대상·외부 요청 수가 무한히 늘지 않도록)

    log_level: str = "INFO"
    tz: str = "Asia/Seoul"

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url_is_sqlite(cls, v: object) -> object:
        if v in ("", None):
            return DEFAULT_DATABASE_URL
        # Railway·Heroku 등이 주는 postgres(ql):// 주소는 psycopg2 를 찾으므로 설치된 psycopg(3)로 바꾼다
        if isinstance(v, str):
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("cluster_sim_threshold", mode="before")
    @classmethod
    def empty_cluster_threshold_is_none(cls, v: object) -> object:
        if v == "" or v is None:
            return None
        return v

    def effective_cluster_threshold(self) -> float:
        """임베딩 모델마다 유사도 값대가 달라 기본 임계값도 다르다. 실제 값은 tune-threshold 로 조정."""
        if self.cluster_sim_threshold is not None:
            return self.cluster_sim_threshold
        return DEFAULT_THRESHOLDS[self.embedding_provider]

    def require_paid(self, component: str, provider: str) -> None:
        """유료 provider를 쓰려 할 때 호출. 허용되지 않았으면 예외."""
        if provider in PAID_PROVIDERS and not self.allow_paid_apis:
            raise PaidApiDisabledError(
                f"{component}={provider} 는 유료 API입니다. "
                "사용하려면 .env 에서 ALLOW_PAID_APIS=true 로 바꾸세요 (docs/PAID_UPGRADES.md)."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
