# 유료 기능 켜기

현재 프로젝트는 **전부 무료**로 동작한다. 아래 유료 옵션은 코드에 이미 들어 있으며, 필요하다고 판단될 때 `.env` 만 바꿔 켠다.
코드를 고칠 필요는 없다.

## 안전장치

유료 provider는 **두 조건을 모두** 만족해야 실행된다.

```ini
ALLOW_PAID_APIS=true          # ① 유료 허용 스위치
SUMMARIZER_PROVIDER=anthropic # ② 유료 provider 선택
ANTHROPIC_API_KEY=sk-ant-...
```

①이 `false`면 ②를 설정해도 `PaidApiDisabledError`로 멈춘다. 실수로 과금되는 일을 막기 위한 장치다.
`issue-stream check` 로 현재 무료/유료 구성을 확인할 수 있다.

## 언제 유료로 바꿀지 판단 기준

유료로 바꾸기 전에 **무료 고급 옵션**을 먼저 시도해 볼 것을 권장한다.

| 증상 | 먼저 시도 (무료) | 그래도 부족하면 (유료) |
|---|---|---|
| 같은 사건인데 표현이 달라 이슈가 쪼개짐 | `EMBEDDING_PROVIDER=local` (e5 모델) | `openai` 임베딩 |
| 요약이 제목 나열 수준이라 읽기 불편 | `SUMMARIZER_PROVIDER=ollama` (로컬 LLM) | `anthropic` (Claude Haiku) |
| 로컬 LLM 요약에 사실 오류가 잦음 | 더 큰 Ollama 모델 | `anthropic` |
| 감성 분류가 부정확 | `SENTIMENT_PROVIDER=hf_local` | `summarizer` + 유료 요약기 |
| 여러 이슈를 종합한 일간 브리핑이 필요 | - | Claude Sonnet (추가 개발 필요) |

`issue_summaries` 테이블에 provider별 요약이 모두 남으므로, 같은 이슈를 무료·유료로 요약한 결과를 나란히 비교한 뒤 결정할 수 있다.

## 옵션별 설정

### 1. 요약: Claude API (유료)

```ini
ALLOW_PAID_APIS=true
SUMMARIZER_PROVIDER=anthropic
ANTHROPIC_MODEL=claude-haiku-4-5
ANTHROPIC_API_KEY=...
```

- 이슈당 1회만 호출된다. 기사가 30% 이상 늘 때만 다시 요약한다(`RESUMMARIZE_GROWTH_RATIO`).
- 호출이 실패하면 자동으로 무료 추출 요약으로 대체되어 화면이 비지 않는다.
- 응답에서 입력에 없는 종목코드·기사 id는 자동 제거된다(환각 방지).
- **예상 비용**(기획서 가정: 하루 이슈 30~50개, 이슈당 입력 2,000·출력 300토큰): 월 약 $5~15.
- 가격은 자주 바뀐다. 켜기 전에 https://docs.claude.com/en/docs/about-claude/pricing 에서 확인할 것.

### 2. 임베딩: OpenAI (유료)

```ini
ALLOW_PAID_APIS=true
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
OPENAI_API_KEY=...
```

- 모델을 바꾼 뒤에는 아래 "임베딩 교체" 절차대로 `issue-stream reembed` 를 실행한다.
- 예상 비용: 기사 1,000건/일 × 300토큰 기준 **월 약 $0.2** (기획서의 $1~3은 과대 추정).
- 비용보다 품질 차이를 보고 결정할 항목이다. 무료 `local`(e5)로도 충분한 경우가 많다.

### 3. 무료 고급 옵션 (참고)

```ini
# 로컬 다국어 임베딩 (pip install -e ".[ml]", 첫 실행 시 모델 약 470MB 다운로드)
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=intfloat/multilingual-e5-small
EMBEDDING_DIM=384

# 로컬 LLM 요약 (docker compose --profile llm up -d → docker compose exec ollama ollama pull qwen2.5:7b-instruct)
SUMMARIZER_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b-instruct

# 한국어 금융 감성 모델
SENTIMENT_PROVIDER=hf_local
```

7B 로컬 LLM은 RAM 8GB 이상에서 동작하며, GPU가 없으면 이슈당 수십 초가 걸릴 수 있다.

## 임베딩 교체 절차

임베딩 모델을 바꾸면 벡터 공간이 달라서 **기존 이슈 중심과 새 기사를 비교할 수 없다.** 반드시 재임베딩한다.

임베딩은 DB 에 바이트로 저장하고 유사도는 파이썬에서 계산하므로 **차원이 바뀌어도 DB 구조를 바꿀 필요가 없다.**

```bash
# .env 에서 EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_DIM 변경, CLUSTER_SIM_THRESHOLD 는 비워 기본값 사용
issue-stream reembed          # 모든 이슈를 지우고 기사 전체를 다시 임베딩·클러스터링
issue-stream tune-threshold   # 새 모델의 유사도 분포 확인 후 임계값 조정
```

## 유료 기능을 추가로 만들 때

새 유료 provider를 붙일 때는 같은 패턴을 따른다.

1. `providers/` 의 해당 모듈에 기본 클래스(`Embedder`, `Summarizer`, `SentimentModel`)를 상속한 클래스를 추가한다.
2. provider 이름을 `core/config.py` 의 `PAID_PROVIDERS` 에 추가한다.
3. `get_xxx()` 팩토리에 분기를 추가한다. 팩토리가 먼저 `require_paid()` 를 호출하므로 안전장치는 자동으로 적용된다.
