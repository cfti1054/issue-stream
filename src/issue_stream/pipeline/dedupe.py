"""SimHash 기반 중복 기사 제거.

통신사 기사를 받아쓴 기사가 많아 제목만으로도 30~40%가 걸러진다.
임베딩·요약 전에 수행해야 비용(유료 전환 시)과 연산량이 통제된다.
"""
from __future__ import annotations

import hashlib

BITS = 64


def _h(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "little")


def simhash(text: str) -> int:
    """글자 3-gram SimHash. 한국어는 띄어쓰기가 불규칙해 단어보다 글자 n-gram이 안정적."""
    t = "".join(text.split())
    grams = [t[i:i + 3] for i in range(max(1, len(t) - 2))]
    v = [0] * BITS
    for g in grams:
        h = _h(g)
        for b in range(BITS):
            v[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(BITS):
        if v[b] > 0:
            out |= 1 << b
    # PostgreSQL BIGINT(부호 있음)에 넣기 위해 signed 64bit 로 변환
    return out - (1 << 64) if out >= (1 << 63) else out


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def find_duplicate(h: int, candidates: dict[int, int], threshold: int) -> int | None:
    """candidates: {article_id: simhash}. 가장 가까운 중복 기사 id 또는 None."""
    best, best_d = None, threshold + 1
    for aid, ch in candidates.items():
        d = hamming(h, ch)
        if d < best_d:
            best, best_d = aid, d
    return best if best_d <= threshold else None
