"""종목 태깅 (사전 기반, 무료).

"현대차"와 "현대차증권", "SK"와 "SK하이닉스"처럼 부분 문자열이 겹치는 경우가 많아
긴 이름부터 매칭하고, 이미 매칭된 구간은 다시 쓰지 않는다.
또한 이름 바로 뒤에 한글이 붙으면(예: "삼성전자서비스", "현대차증권") 다른 회사로 보고 버린다.
단, 조사(은/는/이/가/의/와/과/도/로/를/을/에)는 허용한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_JOSA = set("은는이가의와과도로를을에만")
_HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class TickerEntry:
    code: str
    names: tuple[str, ...]


class TickerTagger:
    def __init__(self, entries: list[TickerEntry], min_len: int = 2):
        pairs = [(n, e.code) for e in entries for n in e.names if len(n) >= min_len]
        # 긴 이름 우선
        self._pairs = sorted(pairs, key=lambda p: len(p[0]), reverse=True)

    def tag(self, text: str) -> dict[str, int]:
        """{종목코드: 언급 횟수}"""
        taken = [False] * len(text)
        found: dict[str, int] = {}
        for name, code in self._pairs:
            start = 0
            while (i := text.find(name, start)) != -1:
                j = i + len(name)
                start = j
                if any(taken[i:j]):
                    continue
                nxt = text[j] if j < len(text) else ""
                if nxt and _HANGUL.match(nxt) and nxt not in _JOSA:
                    continue  # "삼성전자서비스" 등 더 긴 다른 이름의 일부
                prev = text[i - 1] if i > 0 else ""
                if prev and _HANGUL.match(prev):
                    continue  # "신현대차" 같은 앞쪽 결합
                for k in range(i, j):
                    taken[k] = True
                found[code] = found.get(code, 0) + 1
        return found
