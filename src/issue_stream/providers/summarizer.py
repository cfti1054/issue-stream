"""이슈(클러스터) 요약. 이슈당 1회만 호출된다.

- extractive : LLM 없이 기사 제목·스니펫에서 문장을 골라 요약 카드를 만든다. 무료·즉시·환각 없음.
- ollama     : 로컬 LLM (무료). `docker compose --profile llm up -d` 후 `ollama pull <모델>`.
               JSON 스키마를 강제해 IssueSummary 형태로 받는다.
- anthropic  : Claude API (유료). ALLOW_PAID_APIS=true 필요.

LLM 요약이 실패하면(서버 꺼짐, JSON 파싱 실패 등) 자동으로 extractive 로 대체한다.
대시보드는 어떤 경우에도 카드가 비지 않는다.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

import httpx

from ..core.config import get_settings
from ..core.schemas import IssueSummary
from ..pipeline import topics

log = logging.getLogger(__name__)


@dataclass
class ArticleInput:
    id: str
    title: str
    publisher: str | None
    published_at: datetime
    snippet: str | None = None
    body: str | None = None
    kind: str = "news"
    sentiment: str | None = None
    tickers: list[str] = field(default_factory=list)
    ticker_names: list[str] = field(default_factory=list)   # 키워드·이유에서 종목명을 빼는 데만 쓴다


class Summarizer(ABC):
    name: str

    @abstractmethod
    def summarize(self, articles: list[ArticleInput]) -> IssueSummary:
        ...


# ── 무료: 추출 요약 ────────────────────────────────────────────
def _bigrams(s: str) -> set[str]:
    t = "".join(s.split())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class ExtractiveSummarizer(Summarizer):
    name = "extractive"

    def summarize(self, articles: list[ArticleInput]) -> IssueSummary:
        if not articles:
            raise ValueError("빈 이슈")
        grams = [_bigrams(a.title) for a in articles]

        # 1) 헤드라인: 다른 제목들과 가장 많이 겹치는(=가장 대표적인) 뉴스 제목.
        #    공시 제목은 읽기 어려워 헤드라인 대신 근거 불릿 첫 줄에 둔다 (사실 확인용 앵커).
        def centrality(i: int) -> float:
            return sum(_jaccard(grams[i], grams[j]) for j in range(len(articles)) if j != i)

        news = [i for i, a in enumerate(articles) if a.kind != "disclosure"]
        discs = [i for i, a in enumerate(articles) if a.kind == "disclosure"]
        order = sorted(news, key=centrality, reverse=True) or discs
        head = order[0]

        bullets: list[str] = []
        used_ids = [articles[head].id]
        for i in discs[:1]:
            if i != head:
                bullets.append(f"공시: {articles[i].title.removeprefix('[공시] ')}")
                used_ids.append(articles[i].id)

        # 2) 나머지 불릿: 헤드라인·서로와 겹치지 않는 스니펫/제목, 가능하면 매체가 다르게, 최대 3개
        seen_pub = {articles[head].publisher}
        chosen = [grams[head]]
        candidates = ([(head, articles[head].snippet)] if articles[head].snippet else []) + [
            (i, articles[i].snippet or articles[i].title) for i in order[1:]]
        all_pubs = {articles[i].publisher for i in news}
        for i, raw in candidates:
            if len(bullets) >= 3:
                break
            a = articles[i]
            text = raw.split(". ")[0].strip()
            g = _bigrams(text)
            if any(_jaccard(g, c) > 0.5 for c in chosen):
                continue
            if i != head and a.publisher in seen_pub and len(seen_pub) < len(all_pubs):
                continue
            bullets.append(text[:160])
            if a.id not in used_ids:
                used_ids.append(a.id)
            chosen.append(g)
            seen_pub.add(a.publisher)

        names = sorted({n for a in articles for n in a.ticker_names})
        titles = [a.title for a in articles]
        sents = Counter(a.sentiment or "neutral" for a in articles)
        sentiment = sents.most_common(1)[0][0]
        tickers = [t for t, _ in Counter(t for a in articles for t in a.tickers).most_common(5)]
        publishers = len({a.publisher for a in articles})
        return IssueSummary(
            headline=articles[head].title,
            bullets=bullets,
            sentiment=sentiment,  # type: ignore[arg-type]
            affected_tickers=tickers,
            confidence=round(min(0.9, 0.3 + 0.1 * publishers), 2),
            conflicting_views=sents["positive"] > 0 and sents["negative"] > 0,
            source_article_ids=used_ids,
            generated_by=self.name,
            category=topics.classify(titles + [a.snippet for a in articles if a.snippet]),
            keywords=topics.keywords(titles, names),
            reason=topics.reason(articles[head].title, names),
        )


# ── LLM 공통 ────────────────────────────────────────────────────
SYSTEM_PROMPT = """당신은 한국 주식시장 뉴스 편집자입니다. 같은 사건을 다룬 기사 묶음을 받아 하나의 이슈 카드로 요약합니다.
규칙:
- 제공된 기사에 없는 내용은 절대 쓰지 마세요. 수치·날짜는 기사에 나온 그대로만.
- 추측이 섞이면 confidence 를 0.5 이하로 낮추세요.
- 기사끼리 전망이 엇갈리면 conflicting_views 를 true 로.
- affected_tickers 는 6자리 종목코드만. 후보 목록 밖의 코드는 넣지 마세요.
- source_article_ids 에는 요약에 실제로 사용한 기사 id 만.
- category 는 스키마의 목록 중 이 사건에 가장 맞는 주제 하나.
- keywords 는 기사에 나온 핵심 표현 2~3개. 각 12자 이내의 명사구, 종목명은 넣지 마세요. (예: "AI칩 구매", "위성통신 정책")
- reason 은 대표 종목(affected_tickers 첫 번째)이 움직인 이유를 "~로" 로 끝나는 20자 이내 한 구절로. 종목명은 빼세요.
  (예: "AI칩 자금조달 논의로", "외국인·기관 동반 매도로")
- 반드시 JSON 하나만 출력하세요."""

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "affected_tickers": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "conflicting_views": {"type": "boolean"},
        "source_article_ids": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string", "enum": topics.ALL_CATEGORIES},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "reason": {"type": "string"},
    },
    "required": ["headline", "bullets", "sentiment", "affected_tickers", "confidence",
                 "conflicting_views", "source_article_ids", "category", "keywords", "reason"],
}

MAX_ARTICLES = 5


def build_user_prompt(articles: list[ArticleInput]) -> str:
    # 대표 기사 최대 5건. 본문이 없으면(기본 설정) 제목+스니펫만 넣는다.
    picked = sorted(articles, key=lambda a: (a.kind == "disclosure", len(a.snippet or "")), reverse=True)
    lines = []
    for a in picked[:MAX_ARTICLES]:
        text = (a.body or a.snippet or "")[:1500]
        lines.append(f"[id={a.id}] ({a.publisher}, {a.published_at:%m-%d %H:%M}) {a.title}\n{text}")
    candidates = sorted({t for a in articles for t in a.tickers})
    return (f"종목코드 후보: {', '.join(candidates) or '없음'}\n\n기사 목록:\n\n" + "\n\n".join(lines)
            + "\n\nJSON 스키마:\n" + json.dumps(JSON_SCHEMA, ensure_ascii=False))


def _parse(text: str, generated_by: str, articles: list[ArticleInput]) -> IssueSummary:
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start:end + 1])
    s = IssueSummary(**data, generated_by=generated_by)
    # 환각 방지: 입력에 없는 id·종목코드 제거
    valid_ids = {a.id for a in articles}
    valid_tickers = {t for a in articles for t in a.tickers}
    s.source_article_ids = [i for i in s.source_article_ids if i in valid_ids]
    s.affected_tickers = [t for t in s.affected_tickers if t in valid_tickers]
    # 시그널 필드: 목록 밖 주제·빈 값·너무 긴 값은 규칙으로 채운다 (작은 로컬 모델이 형식을 자주 어김)
    names = sorted({n for a in articles for n in a.ticker_names})
    titles = [a.title for a in articles]
    if s.category not in topics.ALL_CATEGORIES:
        s.category = topics.classify(titles)
    s.keywords = [k.strip() for k in s.keywords if k.strip() and not topics.too_long(k.strip())][:3]         or topics.keywords(titles, names)
    s.reason = (s.reason or "").strip() or topics.reason(s.headline, names)
    if len(s.reason) > 30:
        s.reason = s.reason[:29].rstrip() + "…"
    return s


class _LLMSummarizer(Summarizer):
    fallback = ExtractiveSummarizer()

    def summarize(self, articles: list[ArticleInput]) -> IssueSummary:
        try:
            return _parse(self._call(build_user_prompt(articles)), self.name, articles)
        except Exception as e:
            log.warning("%s 요약 실패, extractive 로 대체: %s", self.name, e)
            return self.fallback.summarize(articles)

    @abstractmethod
    def _call(self, user_prompt: str) -> str:
        ...


# ── 무료: 로컬 LLM (Ollama) ─────────────────────────────────────
class OllamaSummarizer(_LLMSummarizer):
    def __init__(self, base_url: str, model: str):
        self.base_url, self.model = base_url.rstrip("/"), model
        self.name = f"ollama:{model}"

    def _call(self, user_prompt: str) -> str:
        r = httpx.post(f"{self.base_url}/api/chat", timeout=180, json={
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": user_prompt}],
            "format": JSON_SCHEMA,
            "stream": False,
            "options": {"temperature": 0.1},
        })
        r.raise_for_status()
        return r.json()["message"]["content"]


# ── 유료: Claude API ────────────────────────────────────────────
class AnthropicSummarizer(_LLMSummarizer):
    API = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str):
        self.model = model
        self.name = f"anthropic:{model}"
        self.key = get_settings().anthropic_api_key

    def _call(self, user_prompt: str) -> str:
        r = httpx.post(self.API, timeout=60, headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json",
        }, json={
            "model": self.model, "max_tokens": 1000, "temperature": 0.1,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        })
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])


@lru_cache
def get_summarizer() -> Summarizer:
    s = get_settings()
    p = s.summarizer_provider
    s.require_paid("SUMMARIZER_PROVIDER", p)
    if p == "extractive":
        return ExtractiveSummarizer()
    if p == "ollama":
        return OllamaSummarizer(s.ollama_base_url, s.ollama_model)
    if p == "anthropic":
        return AnthropicSummarizer(s.anthropic_model)
    raise ValueError(f"알 수 없는 SUMMARIZER_PROVIDER: {p}")
