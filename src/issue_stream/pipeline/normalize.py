"""제목 정규화. 중복 판정과 태깅 전에 표기 차이를 없앤다."""
from __future__ import annotations

import re
import unicodedata

# [속보], [단독], (종합), <사진> 같은 머리표·꼬리표
_BRACKETS = re.compile(r"[\[\(<【〈][^\]\)>】〉]{0,12}[\]\)>】〉]")
_PUNCT = re.compile(r"[^\w\s%.]")
_SPACES = re.compile(r"\s+")
_DOT = re.compile(r"(?<!\d)\.|\.(?!\d)")  # 소수점(3.5%)만 남기고 마침표 제거


def normalize_title(title: str) -> str:
    t = title.replace("…", " ").replace("·", " ")
    t = unicodedata.normalize("NFKC", t)
    t = _BRACKETS.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    t = _DOT.sub(" ", t)
    return _SPACES.sub(" ", t).strip().lower()
