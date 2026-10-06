# API + 수집 스케줄러 (Railway 배포용). 웹은 web/ 에서 별도 서비스로 띄운다 → docs/DEPLOY_RAILWAY.md
#
# 경로 규칙: 소스를 /app 에 두고 editable 설치하므로 ROOT_DIR=/app 이 된다.
#   설정  /app/config/*.yaml
#   DB    /app/data/issue_stream.db  ← Railway Volume 을 /app/data 에 붙여 재배포 후에도 유지
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Seoul

# 휴장일·장중 판단과 로그 시각이 한국 시간 기준이 되도록 tzdata 설치
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY config ./config

# PostgreSQL 로 옮길 때를 대비해 드라이버까지 설치 (SQLite 만 쓰면 사용되지 않음)
RUN pip install -e ".[postgres]"

RUN mkdir -p /app/data

# Railway 가 PORT 를 넣어준다. "::" 는 IPv4·IPv6 모두 받는다 (Railway 내부망은 IPv6 사용).
# serve 는 시작 시 DB 마이그레이션을 먼저 실행한다.
CMD ["sh", "-c", "exec issue-stream serve --host :: --port ${PORT:-8000}"]
