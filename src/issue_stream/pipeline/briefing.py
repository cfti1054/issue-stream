"""시장 AI 요약 (대시보드 상단 요약 박스).

무료 기본값은 LLM 없이 "지수 등락 + 중요도 상위 이슈 헤드라인"으로 조립한다.
이슈 요약 자체가 요약기 provider(extractive/ollama/anthropic)를 따르므로,
요약기를 LLM으로 바꾸면 이 박스의 문장 품질도 함께 올라간다.
여러 이슈를 종합한 서술형 브리핑(Claude Sonnet 등)은 유료 확장 지점이다 → docs/PAID_UPGRADES.md
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..core.config import get_settings, load_yaml
from ..db.models import Issue, IssueSummaryRow, Price

SENTI_KO = {"positive": "긍정", "neutral": "중립", "negative": "부정"}


def _latest(db: Session, symbol: str) -> Price | None:
    return db.scalar(select(Price).where(Price.symbol == symbol).order_by(desc(Price.day)).limit(1))


def build_market_brief(db: Session, hours: int = 24, top: int = 3) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    issues = db.scalars(select(Issue).where(Issue.last_seen >= since).order_by(desc(Issue.importance))).all()
    tone = {"positive": 0, "neutral": 0, "negative": 0}
    for i in issues:
        tone[i.sentiment or "neutral"] += 1

    # 지수 한 줄: 코스피 +0.82%, 코스닥 -0.31%
    market_bits = []
    for item in load_yaml("sources.yaml").get("index_strip", [])[:2]:
        sym, name = (item["symbol"], item["name"]) if isinstance(item, dict) else (item, item)
        p = _latest(db, sym)
        if p and p.change_pct is not None:
            market_bits.append(f"{name} {p.change_pct:+.2f}%")

    bullets = []
    for i in issues[:top]:
        sm = db.scalar(select(IssueSummaryRow).where(IssueSummaryRow.issue_id == i.id,
                                                     IssueSummaryRow.is_current.is_(True)))
        if sm:
            bullets.append({"issue_id": i.id, "text": sm.payload["headline"],
                            "sentiment": i.sentiment or "neutral", "importance": i.importance})

    if issues:
        lead = max(tone, key=lambda k: tone[k])
        mood = {"positive": "긍정 우위", "negative": "부정 우위", "neutral": "중립"}[lead] \
            if tone[lead] > len(issues) / 2 else "혼조"
        headline = f"최근 {hours}시간 주요 이슈 {len(issues)}건 · 뉴스 흐름 {mood}"
    else:
        headline = f"최근 {hours}시간 동안 수집된 이슈가 없습니다"
    if market_bits:
        headline = " · ".join(market_bits) + " | " + headline

    return {
        "headline": headline,
        "bullets": bullets,
        "tone": tone,
        "issue_count": len(issues),
        "generated_by": get_settings().summarizer_provider,
        "generated_at": datetime.now(timezone.utc),
    }
