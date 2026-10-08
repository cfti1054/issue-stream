# issue-stream

주식 시세·공시·뉴스를 자동 수집해 **이슈 단위로 묶고 요약**하는 개인용 투자 정보 대시보드.

> **현재 구성: 전부 무료, API 키·Docker·로그인 없이 동작.** DB 는 프로젝트 폴더의 SQLite 파일 하나다.
> 유료 API(Claude, OpenAI 등)는 교체형으로 들어 있지만 꺼져 있다 → [docs/PAID_UPGRADES.md](docs/PAID_UPGRADES.md)

## 무엇이 어떻게 동작하나

```
수집 ──▶ 정규화·중복제거 ──▶ 종목 태깅·감성 ──▶ 이슈 클러스터링 ──▶ 중요도·요약 ──▶ 저장 ──▶ API / 알림
RSS       제목 정규화          사전(긴 이름 우선)    임베딩 + 온라인        계산식 점수       SQLite       FastAPI
구글뉴스   SimHash             어휘 감성            클러스터링(48h)       이슈당 1회 요약    (또는 PG)    텔레그램
DART(선택)                                         공시는 종목 기준 편입
```

| 단계 | 무료 기본값 (지금) | 무료 고급 옵션 | 유료 옵션 (나중에 선택) |
|---|---|---|---|
| 임베딩 | `hashing` 글자 n-gram, 설치 불필요 | `local` 다국어 e5 모델 | `openai` text-embedding-3-small |
| 요약 | `extractive` LLM 없이 문장 선택 | `ollama` 로컬 LLM | `anthropic` Claude Haiku/Sonnet |
| 감성 | `lexicon` 금융 어휘 사전 | `hf_local` KR-FinBert-SC | 요약 LLM 판단 사용 |
| 시세 | 네이버 모바일 → 야후 → FDR (키 불필요) | KIS 실시간 (계좌 필요, 무료) | - |
| 업종 | 업종 ETF 등락률 (국내 KODEX·TIGER, 미국 섹터 SPDR 등) | - | - |
| 공시 | - | OPEN DART (무료 키) | - |
| 거시 | - | ECOS, FRED (무료 키) | - |
| 뉴스 | 언론사 RSS + 구글 뉴스 RSS (키 불필요) | 네이버 검색 API (무료 키) | 빅카인즈 (기관 계약) |
| 미국 시장 뉴스 | 구글 뉴스 '뉴욕증시' 등(한국어) + CNBC·Nasdaq.com RSS·구글 뉴스 미국판·야후 종목별(영어) | - | - |
| DB | SQLite 파일 (설치 불필요) | PostgreSQL | - |
| 호스팅 | 내 PC | Oracle Cloud Free Tier | 소형 VPS |

> **KRX 관련 참고**: KRX 정보데이터시스템은 2024-12 부터 로그인이 필요해져 pykrx 와
> FinanceDataReader 의 KRX 기반 기능이 막혔다(FDR 지수 캐시는 2026-09-17 이후 갱신 중단).
> 그래서 시세는 네이버 모바일 API → 야후 → FDR 순으로 시도하고, **10일 넘게 갱신이 없는 소스는 쓰지 않는다**.

## 실행 (Windows) — 더블클릭 한 번

준비물: Python 3.11+, Node.js 20+ (Docker·API 키 불필요)

1. **`doctor.cmd`** 더블클릭 → 무료 데이터 소스(뉴스 RSS·구글 뉴스·네이버·야후)가 이 PC 에서 응답하는지 점검.
   `[실패]` 인 RSS 는 `config/sources.yaml` 에서 `enabled: false` 로 끈다.
2. **`start-dashboard.cmd`** 더블클릭 → 패키지 설치(처음 한 번) → 수집기+API 창, 웹 창이 뜨고 브라우저가 열린다.
   처음에는 과거 시세·뉴스를 채우는 데 1~2분 걸리며, 화면 상단에 진행 상태가 표시된다.

수집이 막혀도 화면을 먼저 보고 싶으면 `start-dashboard.cmd -Demo` (가상 데이터, `issue-stream seed-demo --clear` 로 삭제).

- **마켓 대시보드** `/` : 지수 스트립 → AI 요약 → 관심종목·가격 차트 → 주요 뉴스·업종 히트맵
  (AI 요약·주요 뉴스·관심종목·히트맵은 **국내 / 미국** 탭. 미국 종목은 NASDAQ·NYSE·AMEX, 시세는 네이버 해외주식 → 야후)
- 기사마다 국내/미국을 판정해(`pipeline/region.py`) 이슈도 지역별로 묶어 요약한다. 영어 기사는 영어 감성 사전으로 분류한다.
- **이슈 브리핑** `/issues` : 이슈 카드(요약·출처·종목 태그·보도량 추이·근거 기사 펼치기), 기간·감성·종목 필터
- **환율** `/fx` : 원화 환율(달러·엔·유로·위안·파운드, 하나은행 고시 매매기준율)과 달러 인덱스·교차 환율,
  통화별 차트·환율 계산기. 평일 10분마다 갱신, 통화 목록은 `config/sources.yaml` 의 `fx_rates`
- **관심종목은 계정별**이다. 로그인한 뒤 대시보드의 검색창이나 차트 제목 옆 ☆ 를 눌러 등록하면
  그 종목의 과거 시세를 바로 채우고 뉴스 수집 대상에도 넣는다. 로그인하지 않아도 지수·AI 요약·이슈 브리핑은 볼 수 있다.
- 계정은 `/signup` 가입 화면에서 만든다. `.env` 로 가입을 닫거나(`SIGNUP_ENABLED=false`)
  초대 코드를 아는 사람만 받을 수 있다(`SIGNUP_INVITE_CODE`). 관리자는 CLI 로도 관리한다:

  ```bash
  issue-stream user add myid --name 나   # 비밀번호를 물어본다 (아이디: 영문 소문자로 시작 4~20자)
  issue-stream user list | passwd | disable | enable | delete
  ```

- `config/watchlist.yaml` 은 계정과 무관하게 항상 수집하는 기본 종목이자, 새 계정의 초기 관심종목이다.
- 화면 설명은 [web/README.md](web/README.md)

## 빠른 시작 (단계별)

```bash
# 0. 준비물: Python 3.11+, Node.js 20+
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env            # macOS/Linux: cp .env.example .env  (그대로 두면 전부 무료 구성)

# 1. 점검
issue-stream doctor               # 무료 데이터 소스 응답 점검
issue-stream check                # 무료/유료 구성, 키 입력 상태, DB 위치

# 2. 수집만 해보기 (DB 저장 안 함)
issue-stream collect --dry-run

# 3. 실행: API + 수집 스케줄러 한 번에 (DB 자동 생성, 첫 실행 시 과거 시세·뉴스 자동 채움)
issue-stream serve                # http://127.0.0.1:8000/docs
cd web && npm install && npm run dev   # 대시보드 http://localhost:3000 (별도 터미널)

# 4. 품질 검수 (로드맵 2·3단계)
issue-stream issues -v
issue-stream tune-threshold       # 클러스터 임계값 조정용 유사도 분포
pytest                            # 테스트 (SQLite 전체 흐름 포함)
```

## 폴더 구조

```
issue-stream/
├── config/
│   ├── sources.yaml          # 뉴스 RSS·구글 뉴스·지수 스트립·업종 ETF(국내·미국) (무료 소스 on/off)
│   └── watchlist.yaml        # 기본 수집 종목·별칭·보유 여부 (새 계정의 초기 관심종목)
├── src/issue_stream/
│   ├── core/
│   │   ├── config.py         # .env 설정 + 유료 API 안전장치 (ALLOW_PAID_APIS)
│   │   ├── schemas.py        # RawDoc / IssueSummary (단계 간 계약)
│   │   ├── market_calendar.py# KRX 개장일·장중 판단 (휴장일·연말·수능)
│   │   ├── http.py           # 재시도·타임아웃·무료 API 일일 쿼터 집계
│   │   └── logging.py
│   ├── collectors/           # fetch(since) -> list[RawDoc] 로 통일
│   │   ├── rss.py  google_news.py               # 뉴스 (키 불필요)
│   │   ├── naver_news.py  dart.py               # 뉴스 검색·공시 (무료 키, 선택)
│   │   ├── quotes.py         # 시세: 네이버 → 야후 → FDR 체인, 멈춘 소스 걸러냄
│   │   └── macro.py          # ECOS·FRED
│   ├── providers/            # ★ 교체형 구성요소 (무료 ↔ 유료)
│   │   ├── embedding.py      # hashing / local / openai
│   │   ├── summarizer.py     # extractive / ollama / anthropic (+ 실패 시 자동 대체)
│   │   └── sentiment.py      # lexicon / hf_local
│   ├── pipeline/
│   │   ├── normalize.py  dedupe.py  tagging.py
│   │   ├── cluster.py        # 온라인 클러스터링 + 공시 편입 규칙
│   │   ├── importance.py     # 가중합 중요도 점수 (0~100)
│   │   ├── briefing.py       # 대시보드 상단 "AI 요약" (무료: 지수 + 상위 이슈 조립)
│   │   └── run.py            # 단계 오케스트레이션 (DB 연동)
│   ├── jobs/
│   │   ├── tasks.py          # 작업 단위 + job_runs 기록 + 실패 알림 + 보존 정책
│   │   └── scheduler.py      # APScheduler 주기 정의
│   ├── api/main.py           # /dashboard, /issues, /market/*, /macro/*, /health
│   ├── db/                   # 모델·SQLite/PG 공통 타입·upsert
│   ├── doctor.py             # 무료 소스 점검 (issue-stream doctor)
│   ├── demo.py               # 화면 확인용 가상 데이터 (seed-demo)
│   ├── notify/telegram.py    # 중요 이슈·작업 실패 알림 (무료)
│   └── cli.py
├── migrations/               # Alembic 스키마 버전 관리
├── tests/
├── web/                      # Next.js 대시보드 (마켓 대시보드·이슈 브리핑) → web/README.md
├── start-dashboard.cmd       # Windows: 더블클릭으로 수집+API+웹 실행 (start-dashboard.ps1 호출)
├── doctor.cmd                # Windows: 더블클릭으로 무료 소스 점검
├── data/                     # SQLite DB 파일 (자동 생성, git 제외)
└── docs/
    ├── PAID_UPGRADES.md      # 유료 기능 켜는 법·비용·전환 절차
    └── OPERATIONS.md         # 운영: 모니터링·백업·보존·휴장일·쿼터
```

## 기획서 대비 보완한 항목

| 항목 | 내용 | 위치 |
|---|---|---|
| **유료 API 안전장치** | provider가 유료여도 `ALLOW_PAID_APIS=true` 없이는 실행 거부 | `core/config.py` |
| **LLM 없는 요약** | 무료로도 카드가 채워지도록 추출 요약 기본값, LLM 실패 시 자동 대체 | `providers/summarizer.py` |
| **휴장일 캘린더** | KRX 개장일·장중 판단, 휴장일 시세 작업 건너뜀 | `core/market_calendar.py` |
| **모니터링** | 작업별 성공/실패·건수 기록(`job_runs`), `/health`, 실패 시 텔레그램 | `jobs/tasks.py`, `api/main.py` |
| **API 쿼터 관리** | 무료 API 일일 호출 수 집계·한도 전 차단, 재시작 후 복원 | `core/http.py`, `api_usage` |
| **재시도** | 일시 오류(429/5xx/네트워크) 지수 백오프 재시도, 한 소스 실패가 전체를 멈추지 않음 | `core/http.py`, `pipeline/run.py` |
| **스키마 마이그레이션** | Alembic (SQLite·PG 공통) | `migrations/` |
| **DB 구조 (ERD)** | `models.py` 에서 자동 생성. 모델을 바꾸면 `issue-stream erd` 후 함께 커밋 (어긋나면 pytest 실패) | [docs/ERD.md](docs/ERD.md) |
| **설치 없는 DB** | 기본 SQLite, 예전 Docker PG 주소면 연결 실패 시 자동 대체 | `db/session.py` |
| **KRX 차단 대응** | 시세 소스 체인 + 10일 넘게 멈춘 소스 자동 배제, 업종은 ETF 로 대체 | `collectors/quotes.py` |
| **수집 상태 표시** | 첫 실행·수집 실패를 대시보드 상단 배너로 안내 | `/dashboard` `collection` |
| **소스 점검 도구** | 무료 소스별 응답·데이터 날짜 확인 | `issue-stream doctor` |
| **저작권 보존 정책** | 본문 기본 미수집, 수집 시 TTL 후 자동 삭제, 기사 메타 180일 보존 | `job_retention` |
| **마스터 데이터 동기화** | 종목 목록(DART 키 또는 네이버)·관심종목 주 1회 갱신 | `job_sync_*` |
| **중요도 공식 수정** | 곱셈식 → 가중합 (한 항목이 0이어도 전체가 0이 되지 않음) | `pipeline/importance.py` |
| **공시-뉴스 연결** | 글자가 안 겹치는 공시를 같은 종목 이슈에 편입 | `pipeline/cluster.py` |
| **중복 기사 반영** | 받아쓰기 기사는 요약에서 빼되 보도량·매체 수에는 반영 | `pipeline/run.py` |
| **요약 이력** | provider별 요약을 모두 남겨 무료/유료 품질 비교 가능 | `issue_summaries` |
| **임계값 튜닝 도구** | 임베딩별 기본값 + 유사도 분포 출력 | `issue-stream tune-threshold` |
| **임베딩 교체 절차** | 모델 변경 시 재임베딩·재클러스터링 | `issue-stream reembed` |
| **백업** | SQLite 파일 복사 / pg_dump 절차 | `docs/OPERATIONS.md` |
| **테스트** | 정규화·중복·태깅·클러스터·중요도·요약·설정·캘린더 | `tests/` |

## 로드맵

| 단계 | 할 일 | 명령 / 확인 |
|---|---|---|
| 1 | 무료 소스 수집·적재 | `doctor` → `collect --dry-run` → `serve` |
| 2 | 중복 제거·종목 태깅 품질 확인 | `issues -v` 로 태깅 오류·중복 확인, `watchlist.yaml` 별칭 보강 |
| 3 | 클러스터링 임계값 튜닝 | `tune-threshold`, 필요 시 `EMBEDDING_PROVIDER=local` + `reembed` |
| 4 | 요약 품질 개선 | 무료: `SUMMARIZER_PROVIDER=ollama` / 유료: `anthropic` |
| 5 | 마켓 대시보드 화면 | ✅ `web/app/page.tsx` |
| 6 | 이슈 브리핑 화면 | ✅ `web/app/issues/page.tsx` |
| 7 | 알림·개인화·백테스트 | 텔레그램 봇, KIS 실시간 |

## 저작권 원칙

- 기사 **본문은 기본적으로 가져오지 않는다** (`FETCH_ARTICLE_BODY=false`). RSS·검색 API가 공개한 제목과 짧은 요약문만 쓴다.
- 본문을 켜더라도 요약 생성에만 쓰고 `ARTICLE_BODY_TTL_HOURS` 뒤 자동 삭제한다. API는 본문을 절대 내보내지 않는다.
- 화면에는 제목·매체명·시각·원문 링크·직접 만든 요약만 노출한다.
- 본문 크롤링을 켜기 전에 해당 매체의 이용약관·robots.txt를 확인할 것.
- 개인 열람 용도를 넘어 외부에 제공하려면 빅카인즈 등 정식 라이선스와 증권사 API 시세 재배포 약관을 검토할 것.
