# issue-stream 대시보드 실행 (Windows) — 무료 구성, Docker 불필요
#   start-dashboard.cmd 를 더블클릭하거나 PowerShell 에서:
#   powershell -ExecutionPolicy Bypass -File .\start-dashboard.ps1          수집 + API + 웹
#   powershell -ExecutionPolicy Bypass -File .\start-dashboard.ps1 -Demo    가상 데이터도 함께 (화면 미리보기)
#   powershell -ExecutionPolicy Bypass -File .\start-dashboard.ps1 -Doctor  데이터 소스 점검만
param([switch]$Demo, [switch]$Doctor)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$root = $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n▶ $msg" -ForegroundColor Cyan }

# 1) 파이썬 가상환경 + 패키지 (pyproject.toml 이 바뀌었을 때만 다시 설치)
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Step "파이썬 가상환경 만들기 (.venv)"
  python -m venv .venv
}
$stamp = Join-Path $root ".venv\.issue-stream-deps"
$hash = (Get-FileHash (Join-Path $root "pyproject.toml")).Hash
if (-not (Test-Path $stamp) -or (Get-Content $stamp -ErrorAction SilentlyContinue) -ne $hash) {
  Step "파이썬 패키지 설치·갱신 (처음 한 번, 1~3분)"
  & $venvPy -m pip install --upgrade pip --quiet
  & $venvPy -m pip install -e ".[dev]"
  if ($LASTEXITCODE -ne 0) { throw "pip install 실패" }
  Set-Content $stamp $hash
}
$cli = Join-Path $root ".venv\Scripts\issue-stream.exe"

# 2) 설정 파일 (.env) — 없으면 예시에서 복사. 예전 Docker DB 주소는 SQLite 로 전환
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $root ".env.example") $envFile }
$legacy = "DATABASE_URL=postgresql+psycopg://issue:issue@localhost:5432/issue_stream"
$lines = Get-Content $envFile -Encoding UTF8
if (($lines -contains $legacy) -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Step ".env: Docker 가 없어 DB 를 SQLite(data\issue_stream.db)로 전환 (.env.bak 에 백업)"
  Copy-Item $envFile "$envFile.bak" -Force
  $lines | ForEach-Object { if ($_ -eq $legacy) { "# $_   (Docker 없이 SQLite 사용)" } else { $_ } } |
    Set-Content $envFile -Encoding UTF8
}

if ($Doctor) {
  Step "무료 데이터 소스 점검"
  & $cli doctor
  Read-Host "`n엔터를 누르면 닫힙니다"
  exit
}

# 3) DB 준비 (+ 데모 데이터)
Step "DB 준비"
& $cli migrate
if ($Demo) { Step "데모 데이터 생성"; & $cli seed-demo }

# 4) API + 수집 스케줄러 (새 창)
Step "API + 수집기 실행 (새 창)  http://127.0.0.1:8000/docs"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Set-Location '$root'; & '$cli' serve"

# 5) 웹 대시보드 (새 창)
$web = Join-Path $root "web"
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Host "`nNode.js 가 없습니다. https://nodejs.org 에서 LTS 를 설치한 뒤 다시 실행하세요." -ForegroundColor Yellow
  Read-Host "엔터를 누르면 닫힙니다"; exit 1
}
$lockHash = (Get-FileHash (Join-Path $web "package.json")).Hash
$webStamp = Join-Path $web "node_modules\.issue-stream-deps"
if (-not (Test-Path $webStamp) -or (Get-Content $webStamp -ErrorAction SilentlyContinue) -ne $lockHash) {
  Step "웹 패키지 설치 (처음 한 번)"
  Push-Location $web; npm install; Pop-Location
  Set-Content $webStamp $lockHash
}
Step "웹 대시보드 실행 (새 창)  http://localhost:3000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$web'; npm run dev"

Start-Sleep -Seconds 8
Start-Process "http://localhost:3000"
Write-Host "`n완료. 두 창(API·웹)을 닫으면 종료됩니다. 처음에는 데이터가 채워지는 데 1~2분 걸립니다." -ForegroundColor Green
