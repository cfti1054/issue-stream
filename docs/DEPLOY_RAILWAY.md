# Railway 배포

GitHub 저장소 하나에서 서비스 두 개를 띄운다.

```
[api]  Dockerfile (루트)        issue-stream serve = FastAPI + 수집 스케줄러, Volume /app/data (SQLite)
  ▲  내부망 http://api.railway.internal:8000  (외부에 공개하지 않음)
[web]  web/ (Next.js, Railpack)  공개 도메인 → 브라우저
```

| 파일 | 용도 |
|---|---|
| `Dockerfile`, `.dockerignore` | api 이미지. 소스를 `/app` 에 두므로 DB 기본 경로가 `/app/data/issue_stream.db` |
| `railway.json` | api 서비스 설정 (replica 1, 슬립 끔, `/health` 헬스체크) |
| `web/railway.json` | web 서비스 설정 (`npm run build` → `next start`, `PORT` 자동 사용) |

## 1. api 서비스

1. Railway → New Project → Deploy from GitHub repo → 이 저장소 선택.
2. 서비스 이름을 **`api`** 로 바꾼다 (아래 내부 주소에 쓰인다).
3. Settings
   - Root Directory: 비워 둠 (루트의 `railway.json`·`Dockerfile` 사용)
   - Region: **Southeast Asia (Singapore)** 권장 (국내 소스 응답 속도·차단 가능성)
   - Networking: **공개 도메인을 만들지 않는다.** web 만 내부망으로 호출한다.
4. **Volume 추가**: 서비스 우클릭 → Attach Volume → Mount path **`/app/data`**
   - 이게 없으면 재배포할 때마다 DB 가 초기화된다.
5. Variables

   ```ini
   PORT=8000
   TZ=Asia/Seoul
   # 무료 기본 구성은 아래만으로 충분. 나머지는 .env.example 참고해 필요할 때 추가
   ALLOW_PAID_APIS=false
   # 선택: DART_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID ...
   ```

   `.env` 파일은 이미지에 들어가지 않는다 (`.dockerignore`). 값은 모두 Railway Variables 에 넣는다.

## 2. web 서비스

1. 같은 프로젝트에서 New → GitHub Repo → 같은 저장소를 한 번 더 추가, 이름 **`web`**.
2. Settings
   - Root Directory: **`/web`**
   - Config-as-code 경로(Railway Config File): **`/web/railway.json`** (루트 기준 경로로 지정해야 한다)
   - Networking: **Generate Domain** (이 주소로 접속)
3. Variables

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
- 상태: web 화면 상단 배너, 또는 api 셸에서 `curl localhost:8000/health`.

## 운영 메모

- **replica 는 1 로 유지.** 스케줄러가 API 프로세스 안에 있어 2개면 수집도 두 번 돈다.
  Volume 이 붙은 서비스는 재배포 시 기존 컨테이너가 먼저 내려가므로 겹쳐 돌지 않는다.
- **슬립 끔**(`sleepApplication: false`). 켜면 요청이 없을 때 스케줄러가 멈춘다.
- `config/watchlist.yaml`·`sources.yaml` 은 이미지에 포함된다. 고친 뒤 push 하면 api 가 재배포되고,
  시작 시 관심종목 반영·과거 시세 채우기가 자동으로 돈다.
- `watchPatterns` 덕분에 `web/` 만 바뀌면 web 만, 백엔드만 바뀌면 api 만 재배포된다.
- 백업: Volume 의 `/app/data/issue_stream.db` 를 받아 둔다 (`railway ssh` 로 `sqlite3 ... .backup`),
  또는 Railway Postgres 를 추가하고 api 에 `DATABASE_URL=${{Postgres.DATABASE_URL}}` 을 넣어 옮긴다
  (드라이버는 이미지에 설치돼 있다. URL 스킴을 `postgresql+psycopg://` 로 바꿔 넣을 것).
- 접근 제한: 화면에 로그인이 없다. web 도메인을 아는 사람은 누구나 볼 수 있다.
- 비용: 기본 무료 구성(hashing·extractive·SQLite)은 가볍다. `.[ml]` 로컬 모델은 메모리를 크게 쓰므로
  Railway 에서는 권장하지 않는다 (유료 API 쪽이 더 싸다 → `PAID_UPGRADES.md`).
