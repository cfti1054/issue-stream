# Railway 배포

GitHub 저장소 하나에서 서비스 두 개를 띄운다.

```
[Postgres]  Railway PostgreSQL (계정·관심종목·기사·시세 전부)
  ▲  DATABASE_URL
[api]  Dockerfile (루트)        issue-stream serve = FastAPI + 수집 스케줄러
  ▲  내부망 http://api.railway.internal:8000  (외부에 공개하지 않음)
[web]  web/ (Next.js, Railpack)  공개 도메인 → 브라우저. 로그인 쿠키를 받아 API 에 Bearer 로 전달
```

## 0. PostgreSQL

프로젝트 캔버스에서 New → Database → **PostgreSQL** 추가. 아래 api Variables 의 `DATABASE_URL` 로 연결한다.
Railway 가 주는 `postgresql://` 주소는 앱이 `postgresql+psycopg://` 로 자동 변환하므로 그대로 넣으면 된다.
스키마는 api 가 시작할 때 자동으로 만든다 (`serve` 가 마이그레이션 먼저 실행).

> SQLite Volume 으로 운영하던 데이터는 옮겨지지 않는다. Postgres 로 바꾸면 첫 실행처럼 과거 시세·뉴스를 새로 채운다.
> Postgres 를 쓰면 api 의 Volume 은 필요 없다.

| 파일 | 용도 |
|---|---|
| `Dockerfile`, `.dockerignore` | api 이미지. 소스를 `/app` 에 두므로 DB 기본 경로가 `/app/data/issue_stream.db` |
| `web/package.json` | Railpack 이 Next.js 를 자동 인식. `engines` 로 Node 20.9+ 지정 |

> Railway 의 Config as Code(`railway.json`)는 폐지되어 2026-08-28 이후 만든 서비스는 쓸 수 없다.
> 아래 설정은 모두 **대시보드 Settings 에서 직접 입력**한다.
> 설정을 코드로 관리하고 싶으면 Infrastructure as Code(`.railway/railway.ts`, `railway config apply`)를 쓸 수 있지만,
> 서비스 두 개짜리 구성에는 대시보드로 충분하다.

## 1. api 서비스

New Project → Deploy from GitHub repo → 이 저장소. 서비스 이름 **`api`** (web 의 내부 주소에 쓰인다).

| Settings 항목 | 값 |
|---|---|
| Source → Root Directory | 비워 둠 |
| Source → Watch Paths | 아래 6개를 **한 줄에 하나씩** 따로 추가 |
| Build → Builder | Dockerfile (루트의 `Dockerfile` 자동 인식) |
| Deploy → Custom Start Command | 비워 둠 (Dockerfile 의 CMD 사용) |
| Deploy → Region | Southeast Asia (Singapore) 권장 |
| Deploy → Replicas | **1** |
| Deploy → Serverless (App Sleeping) | **끔** |
| Deploy → Healthcheck Path | `/health` |
| Deploy → Restart Policy | On Failure |
| Networking | **공개 도메인을 만들지 않는다** |

**Watch Paths** — 패턴마다 따로 입력한다. 한 칸에 공백으로 이어 붙이면 하나의 패턴으로 취급되어
어떤 파일과도 맞지 않고, 백엔드 커밋을 푸시해도 api 가 재배포되지 않는다 (배포 목록에 Skipped 로 남음).

```
/src/**
/config/**
/migrations/**
/alembic.ini
/pyproject.toml
/Dockerfile
```

**Volume** (SQLite 로 운영할 때만): 서비스 우클릭 → Attach Volume → Mount path **`/app/data`**.
이게 없으면 재배포할 때마다 DB 가 초기화된다. PostgreSQL 을 쓰면 필요 없다.

**Variables**

```ini
PORT=8000
TZ=Asia/Seoul
DATABASE_URL=${{Postgres.DATABASE_URL}}
# 가입: 누구나(기본) / 초대 코드를 아는 사람만 / 닫기(CLI 로만 계정 생성)
SIGNUP_ENABLED=true
SIGNUP_INVITE_CODE=
MAX_WATCHLIST_PER_USER=50
ALLOW_PAID_APIS=false
# 첫 실행 시 과거 시세를 채우느라 늦게 뜰 수 있어 헬스체크 대기 시간을 늘린다
RAILWAY_HEALTHCHECK_TIMEOUT_SEC=120
# 선택: DART_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID ...
```

`.env` 파일은 이미지에 들어가지 않는다 (`.dockerignore`). 값은 모두 Railway Variables 에 넣는다.

## 2. web 서비스

같은 프로젝트에서 New → GitHub Repo → 같은 저장소를 한 번 더 추가, 이름 **`web`**.

| Settings 항목 | 값 |
|---|---|
| Source → Root Directory | **`/web`** |
| Source → Watch Paths | `/web/**` |
| Build → Builder | Railpack (자동) |
| Build → Custom Build Command | 비워 둠 (`npm run build` 자동) |
| Deploy → Custom Start Command | **`npx next start -H 0.0.0.0`** |
| Deploy → Region | api 와 같은 리전 |
| Deploy → Replicas | 1 |
| Deploy → Serverless (App Sleeping) | 끔 |
| Deploy → Healthcheck Path | `/` |
| Deploy → Restart Policy | On Failure |
| Networking | **Generate Domain** (이 주소로 접속) |

Start Command 를 꼭 넣는 이유: `package.json` 의 `npm start` 는 포트가 3000 으로 고정돼 있다.
`next start` 를 `-p` 없이 실행하면 Railway 가 준 `PORT` 를 그대로 쓴다.

**Variables**

```ini
API_BASE=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000
NEXT_PUBLIC_REFRESH_SECONDS=60
```

`NEXT_PUBLIC_*` 는 빌드할 때 박히므로 값을 바꾸면 **재배포**해야 반영된다.
`API_BASE` 는 실행 중 서버에서 읽으므로 재시작만 하면 된다.

## 3. 배포 후 확인

- api 서비스 → Deployments → 로그에 `첫 실행: 과거 시세 채우기` → `초기 데이터 준비 완료` 가 나오면 정상.
- 소스 응답 점검: api 서비스 셸(`railway ssh` 또는 대시보드의 Shell)에서

  ```bash
  issue-stream doctor
  ```

  해외 서버라 막히는 RSS·시세 소스가 있으면 `config/sources.yaml` 에서 `enabled: false` 로 끄고 push.
- **로그인 계정 만들기**: web 도메인의 `/signup` 에서 가입한다.
  web 도메인은 공개 주소라 누구나 가입할 수 있으므로, 개인용이면 `SIGNUP_INVITE_CODE` 를 넣거나
  자기 계정을 만든 뒤 `SIGNUP_ENABLED=false` 로 닫는다. 관리자는 api 서비스 셸에서도 만들 수 있다:

  ```bash
  issue-stream user add myid --name 나     # 비밀번호 입력 (8자 이상)
  issue-stream user list
  ```

- 상태: web 화면 상단 배너, 또는 api 셸에서 `curl localhost:8000/health`.
- web 화면에 "API 서버에 연결할 수 없습니다" 가 나오면: api 서비스 이름이 `api` 인지, `API_BASE` 의 포트가
  api 의 `PORT`(8000) 와 같은지 확인.

## 운영 메모

- **replica 는 1 로 유지.** 스케줄러가 API 프로세스 안에 있어 2개면 수집도 두 번 돈다.
  Volume 이 붙은 서비스는 재배포 시 기존 컨테이너가 먼저 내려가므로 겹쳐 돌지 않는다.
- **App Sleeping 끔.** 켜면 요청이 없을 때 스케줄러가 멈춘다.
- `config/watchlist.yaml`·`sources.yaml` 은 이미지에 포함된다. 고친 뒤 push 하면 api 가 재배포되고,
  시작 시 관심종목 반영·과거 시세 채우기가 자동으로 돈다.
- Watch Paths 덕분에 `web/` 만 바뀌면 web 만, 백엔드만 바뀌면 api 만 재배포된다.
- 백업: Railway Postgres 의 Backups 탭 (SQLite 로 운영 중이면 Volume 의 `/app/data/issue_stream.db`).
- 접근 제한: 관심종목은 로그인한 계정만 볼 수 있다. 지수·AI 요약·이슈 브리핑은 web 도메인을 아는 누구나 볼 수 있다.
  로그인 쿠키는 HttpOnly·Secure(https 에서만)로 web 도메인에만 저장된다.
- 비용: 기본 무료 구성(hashing·extractive·SQLite)은 가볍다. `.[ml]` 로컬 모델은 메모리를 크게 쓰므로
  Railway 에서는 권장하지 않는다 (유료 API 쪽이 더 싸다 → `PAID_UPGRADES.md`).
