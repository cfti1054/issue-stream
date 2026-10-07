"""종목 태깅 (사전 기반, 무료).

"현대차"와 "현대차증권", "SK"와 "SK하이닉스"처럼 부분 문자열이 겹치는 경우가 많아
긴 이름부터 매칭하고, 이미 매칭된 구간은 다시 쓰지 않는다.
또한 이름 바로 뒤에 한글이 붙으면(예: "삼성전자서비스", "현대차증권") 다른 회사로 보고 버린다.
단, 조사(은/는/이/가/의/와/과/도/로/를/을/에)는 허용한다.
영문 이름·티커(미국 종목: Nvidia, NVDA)는 대소문자를 무시하고 영숫자 단어 경계에서만 찾는다
("Meta" 가 "metal" 에, "AMD" 가 "AMDX" 에 걸리지 않도록).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_JOSA = set("은는이가의와과도로를을에만")
_HANGUL = re.compile(r"[가-힣]")
_ASCII_NAME = re.compile(r"^[A-Za-z0-9 .&'-]+$")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")  # 길이가 변하지 않는 소문자화


def _is_word(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


@dataclass(frozen=True)
class TickerEntry:
    code: str
    names: tuple[str, ...]


class TickerTagger:
    def __init__(self, entries: list[TickerEntry], min_len: int = 2):
        pairs = []
        for e in entries:
            for n in e.names:
                if len(n) < min_len:
                    continue
                ascii_name = bool(_ASCII_NAME.match(n))
                pairs.append((n.translate(_ASCII_LOWER) if ascii_name else n, e.code, ascii_name))
        # 긴 이름 우선
        self._pairs = sorted(pairs, key=lambda p: len(p[0]), reverse=True)

    def tag(self, text: str) -> dict[str, int]:
        """{종목코드: 언급 횟수}"""
        taken = [False] * len(text)
        lowered = text.translate(_ASCII_LOWER)
        found: dict[str, int] = {}
        for name, code, ascii_name in self._pairs:
            hay = lowered if ascii_name else text
            start = 0
            while (i := hay.find(name, start)) != -1:
                j = i + len(name)
                start = j
                if any(taken[i:j]):
                    continue
                nxt = text[j] if j < len(text) else ""
                prev = text[i - 1] if i > 0 else ""
                if ascii_name:
                    if _is_word(prev) or _is_word(nxt):
                        continue  # 영문 단어의 일부
                else:
                    if nxt and _HANGUL.match(nxt) and nxt not in _JOSA:
                        continue  # "삼성전자서비스" 등 더 긴 다른 이름의 일부
                    if prev and _HANGUL.match(prev):
                        continue  # "신현대차" 같은 앞쪽 결합
                for k in range(i, j):
                    taken[k] = True
                found[code] = found.get(code, 0) + 1
        return found
