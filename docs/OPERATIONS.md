# 운영 가이드

## 실행 구조

`issue-stream serve` 한 프로세스가 API 서버와 수집 스케줄러를 함께 돌린다 (Windows 는 `start-dashboard.cmd`).
시작할 때마다 `watchlist.yaml` 과 계정별 관심종목(합집합)을 수집 대상으로 반영하고, 시세가 없는 관심종목은 과거 130거래일을 자동으로 채운 뒤 뉴스를 한 번 수집한다.

## 스케줄

| 작업 | 주기 | 조건 |
|---|---|---|
| `job_news_pipeline` 뉴스 → 중복 제거 → 클러스터링 → 요약 | 10분 | 항상 |
| `job_intraday_prices` 관심종목·지수 현재가 | 평일 09~15시 5분 | 개장일·장중만 (아니면 skipped) |
| `job_daily_close` 확정 일봉 + 지수 + 업종 ETF 히트맵 | 평일 16:10 | 개장일만 |
| `job_backfill_prices(days=5)` 해외 지수 마감치 보정 | 화~토 07:10 | |
| `job_macro` ECOS·FRED | 매일 07:30 | 키가 있을 때만 (선택) |
| `job_sync_tickers` 종목 목록(태깅 사전) + watchlist | 매주 월 06:00 | |
| `job_sync_dart_corp_codes` DART 고유번호 | 매주 월 06:20 | DART 키가 있을 때만 (선택) |
| `job_retention` 본문 TTL 삭제·오래된 기사 삭제·이슈 종료 | 매일 03:00 | |

`watchlist.yaml` 을 고친 뒤에는 수집기(`serve`)를 다시 시작하면 바로 반영되고 과거 시세도 채워진다.
화면에서 ☆ 로 등록한 종목은 재시작 없이 바로 수집 대상이 되고 과거 시세도 즉시 채운다.
아무 계정도 보지 않는(★ 해제된) 종목은 수집 대상에서 빠진다 (yaml 종목 제외).

## 무료 데이터 소스와 대체 순서

| 데이터 | 1순위 | 2순위 | 3순위 |
|---|---|---|---|
| 국내 종목·ETF 일봉 | 네이버 증권 모바일 API | 야후 (`005930.KS`) | FinanceDataReader |
| 코스피·코스닥 | 네이버 증권 모바일 API | 야후 (`^KS11`) | FDR (2026-09-17 이후 멈춤 → 자동 배제) |
| S&P 500·나스닥 | 야후 (`^GSPC`, `^IXIC`) | FDR | |
| 원/달러 | 네이버 환율 | 야후 (`KRW=X`) | FDR |
| 뉴스 | 언론사 RSS 5곳 | 구글 뉴스 RSS (관심종목·키워드 검색) | |

- 마지막 데이터가 **10일보다 오래된 소스는 쓰지 않는다** (`collectors/quotes.py` 의 `MAX_AGE_DAYS`).
- 화면에서 4일 넘게 갱신되지 않은 값은 "9/17 기준"처럼 날짜가 함께 표시된다.
- 순서는 `config/sources.yaml` 의 `index_strip[].sources` 로 바꿀 수 있다.
- 어떤 소스가 되는지는 `issue-stream doctor` (또는 `doctor.cmd`) 로 확인한다.

## 모니터링

- `GET /health`: 작업별 마지막 실행 상태·시각·처리 건수, 오늘 API 호출 수, 현재 provider 구성.
- `job_runs` 테이블: 작업 이력 (30일 보관).

  ```sql
  SELECT job, status, count(*) FROM job_runs
  WHERE started_at > now() - interval '1 day' GROUP BY 1, 2 ORDER BY 1;
  ```

- 작업이 실패하면 텔레그램으로 알림이 간다 (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 설정 시).
- 중요도가 `ALERT_IMPORTANCE_THRESHOLD`(기본 70) 이상인 이슈는 이슈당 1회 알림이 간다.

## 무료 API 쿼터

| 소스 | 공식 한도 | 코드상 차단 기준 | 비고 |
|---|---|---|---|
| OPEN DART | 일 20,000건 | 18,000 | 10분 주기면 하루 150~300건 수준 |
| 네이버 검색 | 일 25,000건 | 24,000 | 종목 수 × (하루 144회) 로 계산해 종목 수 조절 |
| ECOS / FRED | 넉넉함 | 5,000 | 1일 1회 |

호출 수는 `api_usage` 테이블에 저장되며, 스케줄러 재시작 시 오늘 사용량을 다시 불러온다.
공식 한도는 바뀔 수 있으니 각 서비스 콘솔에서 확인할 것.

## 휴장일

`exchange_calendars` 의 XKRX 캘린더로 주말·공휴일·연말 휴장을 판단한다.
라이브러리 데이터가 늦게 갱신되는 임시 공휴일이나 수능일 지연 개장은 틀릴 수 있다. 이 경우 시세 작업이 헛돌거나 한 번 건너뛸 뿐 데이터가 망가지지는 않는다.
`pip install -U exchange-calendars` 로 주기적으로 갱신할 것.

## 데이터 보존

| 데이터 | 보존 | 설정 |
|---|---|---|
| 기사 본문 (켰을 때만) | 24시간 | `ARTICLE_BODY_TTL_HOURS` |
| 기사 메타데이터 (제목·링크·요약문·임베딩) | 180일 | `ARTICLE_RETENTION_DAYS` |
| 이슈 | 마지막 기사 후 48시간이 지나면 `closed` (삭제하지 않음) | `CLUSTER_WINDOW_HOURS` |
| 작업 이력 | 30일 | `job_retention` |

## 백업

기본 DB 는 `data/issue_stream.db` 파일 하나다. 수집기를 끈 상태에서 `data` 폴더를 통째로 복사하면 된다
(`issue_stream.db-wal`, `-shm` 파일도 함께). 켜 둔 채 백업하려면:

```bash
python -c "import sqlite3; s=sqlite3.connect('data/issue_stream.db'); d=sqlite3.connect('backup.db'); s.backup(d)"
```

PostgreSQL 을 쓰는 경우: `pg_dump -Fc issue_stream > backup.dump` / `pg_restore -d issue_stream --clean backup.dump`.

## 배포 (무료)

**1) 내 PC**: `start-dashboard.cmd` (또는 `issue-stream serve` + `web` 에서 `npm run dev`). PC가 꺼지면 수집도 멈추고,
다시 켜면 빠진 시세는 자동으로 채워진다.

**2) Oracle Cloud Free Tier**: Always Free ARM 인스턴스(최대 4 OCPU·24GB RAM)면 로컬 임베딩·Ollama 7B까지 돌릴 수 있다.

```bash
git clone <repo> && cd issue-stream
cp .env.example .env
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
issue-stream doctor
# systemd 서비스로 `issue-stream serve` 와 web 의 `npm run build && npm start` 를 상시 실행
```

## 문제 해결

| 증상 | 확인 |
|---|---|
| 같은 사건이 여러 이슈로 쪼개짐 | `tune-threshold` 로 분포 확인 후 `CLUSTER_SIM_THRESHOLD` 를 낮춤, 또는 `EMBEDDING_PROVIDER=local` |
| 다른 사건이 한 이슈로 합쳐짐 | 임계값을 높임 |
| 종목이 잘못 태깅됨 | `watchlist.yaml` 별칭 점검. 짧은 별칭(2글자)은 오탐이 많음 |
| 공시가 뉴스 이슈에 안 붙음 | 공시가 먼저 들어와 따로 이슈가 생긴 경우. 이후 뉴스는 뉴스끼리 묶임 (알려진 한계, 5단계에서 개선) |
| RSS 수집 0건 / 대시보드에 "뉴스 수집" 경고 | `issue-stream doctor` 로 실패한 피드 확인 후 `sources.yaml` 에서 `enabled: false` |
| 지수·시세가 비어 있음 / 오래된 날짜 | `doctor` 의 시세 항목 확인. 회사망·VPN 이 네이버·야후를 막는 경우가 있음 |
| 업종 히트맵 이름이 이상함 | `doctor` 가 보여주는 ETF 와 `sector_etfs` 의 code 가 맞는지 확인 |
| 시작 시 "Postgres에 연결할 수 없어 SQLite…" 경고 | 정상 동작. `.env` 의 예전 `DATABASE_URL` 줄을 지우면 사라짐 |
| `database is locked` | `serve` 를 두 번 띄웠는지 확인 (한 PC 에서 하나만) |
| `PaidApiDisabledError` | 의도한 동작. 유료를 쓰려면 `ALLOW_PAID_APIS=true` |
