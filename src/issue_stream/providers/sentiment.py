"""감성 분류 (기사 단위).

- lexicon  : 금융 뉴스 제목에 자주 나오는 긍정/부정 어휘 사전. 무료·즉시 동작. 기본값.
- hf_local : snunlp/KR-FinBert-SC (한국어 금융 감성 모델, 무료, `.[ml]` 필요).
- summarizer: 기사 단위 감성은 lexicon 으로 두고, 이슈 감성은 요약기(LLM) 결과를 쓴다.

이슈 감성은 pipeline/enrich.py 에서 기사 감성의 다수결로 계산한다.
(summarizer 설정이고 LLM 요약기가 켜져 있으면 LLM 판단을 우선)
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from functools import lru_cache

from ..core.config import get_settings
from ..core.schemas import Sentiment

POSITIVE = [
    "급등", "상승", "강세", "반등", "호실적", "최대 실적", "사상 최대", "흑자전환", "흑자 전환", "수주",
    "신고가", "상향", "개선", "호조", "돌파", "증가", "성장", "확대", "승인", "계약 체결", "자사주 매입",
    "배당 확대", "순매수", "기대감", "훈풍", "회복",
]
NEGATIVE = [
    "급락", "하락", "약세", "폭락", "적자", "적자전환", "적자 전환", "부진", "하향", "우려", "악화", "감소",
    "쇼크", "리콜", "소송", "제재", "과징금", "횡령", "배임", "상장폐지", "거래정지", "유상증자", "불성실공시",
    "순매도", "신저가", "경고", "충격", "철회", "지연", "파업",
]


# 영어 기사 (미국 시장 원문). 단어 경계로만 센다 ("rise" 가 "enterprise" 에 걸리지 않도록)
POSITIVE_EN = [
    "surge", "surges", "surged", "soar", "soars", "soared", "jump", "jumps", "jumped", "rally", "rallies",
    "rallied", "gain", "gains", "gained", "rise", "rises", "rose", "climb", "climbs", "climbed", "rebound",
    "rebounds", "record high", "all-time high", "beat", "beats", "tops estimates", "upgrade", "upgraded",
    "upgrades", "bullish", "strong", "outperform", "raises guidance", "raised guidance", "boost", "boosts",
    "higher", "optimism", "recovery",
]
NEGATIVE_EN = [
    "plunge", "plunges", "plunged", "tumble", "tumbles", "tumbled", "slump", "slumps", "slumped", "fall",
    "falls", "fell", "drop", "drops", "dropped", "sink", "sinks", "sank", "slide", "slides", "slid", "decline",
    "declines", "declined", "miss", "misses", "missed", "downgrade", "downgraded", "downgrades", "bearish",
    "weak", "selloff", "sell-off", "recession", "layoffs", "lawsuit", "probe", "fears", "warning", "warns",
    "cuts guidance", "bankruptcy", "lower", "losses", "crash", "crashes",
]
_HANGUL = re.compile(r"[가-힣]")


def _en_pattern(words: list[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b",
                      re.IGNORECASE)


_POS_EN, _NEG_EN = _en_pattern(POSITIVE_EN), _en_pattern(NEGATIVE_EN)


class SentimentModel(ABC):
    name: str

    @abstractmethod
    def classify(self, texts: list[str]) -> list[Sentiment]:
        ...


class LexiconSentiment(SentimentModel):
    name = "lexicon"

    def classify(self, texts: list[str]) -> list[Sentiment]:
        out: list[Sentiment] = []
        for t in texts:
            if _HANGUL.search(t):
                pos = sum(t.count(w) for w in POSITIVE)
                neg = sum(t.count(w) for w in NEGATIVE)
            else:   # 영어 원문
                pos, neg = len(_POS_EN.findall(t)), len(_NEG_EN.findall(t))
            out.append("positive" if pos > neg else "negative" if neg > pos else "neutral")
        return out


class HfLocalSentiment(SentimentModel):
    name = "hf_local:KR-FinBert-SC"

    def __init__(self):
        try:
            from transformers import pipeline
        except ImportError as e:
            raise RuntimeError("SENTIMENT_PROVIDER=hf_local 은 `pip install -e .[ml]` 이 필요합니다.") from e
        self.pipe = pipeline("text-classification", model="snunlp/KR-FinBert-SC", truncation=True)

    def classify(self, texts: list[str]) -> list[Sentiment]:
        res = self.pipe(texts, batch_size=16)
        return [r["label"].lower() if r["label"].lower() in ("positive", "negative") else "neutral"
                for r in res]


@lru_cache
def get_sentiment_model() -> SentimentModel:
    p = get_settings().sentiment_provider
    if p == "hf_local":
        return HfLocalSentiment()
    return LexiconSentiment()  # lexicon, summarizer 모두 기사 단위는 사전 사용
