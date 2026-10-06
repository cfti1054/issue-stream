"""이슈 중요도 점수 (0~100). LLM이 아닌 계산식으로 산출해 일관성·설명 가능성을 확보한다.

기획서의 곱셈식(기사 수 × 매체 다양성 × 증가율 × 보유 여부)은 한 항목이 0이면 전체가 0이 되는
문제가 있어 가중합으로 바꿨다. 각 항목은 0~1로 정규화하고 가중치는 WEIGHTS에서 조정한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

WEIGHTS = {
    "volume": 0.30,      # 기사 수
    "diversity": 0.25,   # 서로 다른 매체 수
    "velocity": 0.20,    # 최근 1시간 증가 속도
    "holding": 0.15,     # 보유종목 관련 여부
    "disclosure": 0.10,  # 공시(DART)로 뒷받침되는지
}


@dataclass
class ImportanceInput:
    article_count: int
    publisher_count: int
    articles_last_hour: int
    touches_holding: bool
    touches_watchlist: bool
    has_disclosure: bool


def _sat(x: float, half: float) -> float:
    """x 가 half 일 때 0.5, 커질수록 1에 수렴하는 포화 함수."""
    return 1 - math.exp(-math.log(2) * x / half) if x > 0 else 0.0


def importance(i: ImportanceInput) -> tuple[float, dict[str, float]]:
    parts = {
        "volume": _sat(i.article_count, 5),
        "diversity": _sat(i.publisher_count, 3),
        "velocity": _sat(i.articles_last_hour, 3),
        "holding": 1.0 if i.touches_holding else 0.5 if i.touches_watchlist else 0.0,
        "disclosure": 1.0 if i.has_disclosure else 0.0,
    }
    score = 100 * sum(WEIGHTS[k] * v for k, v in parts.items())
    return round(score, 1), {k: round(v, 2) for k, v in parts.items()}
