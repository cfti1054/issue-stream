"""시그널 화면용 이슈 주제·키워드·이유 (LLM 없이 규칙으로).

- category : 정해진 주제 목록(CATEGORIES) 중 하나. 기사 제목·스니펫의 단서 단어 점수로 고른다.
- keywords : 기사 제목에 여러 번 나온 짧은 구(2단어 우선) 2~3개. 종목명은 빼고 고른다.
- reason   : 대표 헤드라인에서 종목명·머리표를 뗀 짧은 한 줄.

LLM 요약(ollama·anthropic)은 같은 세 값을 직접 만들고, 형식이 어긋나면 여기 규칙으로 채운다.
"""
from __future__ import annotations

import re
from collections import defaultdict

# 주제 → 단서 단어. 위에 있을수록 동점일 때 우선. 영어 단어는 소문자로 비교한다.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "실적": ("실적", "영업이익", "영업익", "순이익", "매출", "어닝", "분기", "잠정", "흑자", "적자", "호실적",
           "earnings", "revenue", "profit", "quarter", "guidance"),
    "거시·금리": ("금리", "기준금리", "연준", "fed", "fomc", "국채", "물가", "cpi", "인플레", "고용", "gdp", "한은",
              "금통위", "rates", "rate", "yield", "yields", "treasury", "inflation", "jobs"),
    "환율": ("환율", "원달러", "원/달러", "달러", "엔화", "위안", "dollar", "currency", "yen"),
    "수급": ("외국인", "기관", "순매수", "순매도", "공매도", "리밸런싱", "수급", "프로그램", "매도세", "매수세"),
    "정책·규제": ("관세", "규제", "정부", "정책", "법안", "제재", "승인", "fda", "허가", "세제", "tariff", "tariffs",
              "regulation", "approval", "sanction"),
    "수주·계약": ("수주", "계약", "공급계약", "체결", "납품", "수출", "contract", "order", "deal"),
    "M&A·지배구조": ("인수", "합병", "m&a", "지분", "매각", "구조조정", "분할", "지배구조", "경영권", "acquisition",
                  "merger", "stake"),
    "자금 조달": ("유상증자", "회사채", "자금조달", "조달", "전환사채", "차입", "발행", "ipo", "상장", "offering", "debt"),
    "신제품·기술": ("양산", "개발", "출시", "신제품", "hbm", "ai", "기술", "칩", "launch", "chip", "chips"),
    "시장 동향": ("증시", "지수", "코스피", "코스닥", "나스닥", "마감", "랠리", "최고치", "강세", "약세", "급등", "급락",
              "stocks", "market", "rally", "nasdaq", "s&p", "dow", "wall"),
}
DEFAULT_CATEGORY = "시장 이슈"
ALL_CATEGORIES = [*CATEGORIES, DEFAULT_CATEGORY]

_BRACKETS = re.compile(r"[\[\(<【〈][^\]\)>】〉]{0,12}[\]\)>】〉]")
_CLAUSE = re.compile(r",(?!\d)|[…·:;|\"“”‘’!?]|\.{2,}")
_SPLIT = re.compile(r"(?:[\s·…\"'“”‘’!?:;|/]|,(?!\d))+|\.{2,}")
_NUMERIC = re.compile(r"^[\d.,%]+[가-힣a-z%]{0,3}$")
_PARTICLES2 = ("에서", "으로", "에게", "까지", "부터", "보다", "처럼", "에도", "에는", "이며", "에선")
_PARTICLES1 = ("은", "는", "을", "를", "와", "과", "로", "도", "만", "에", "이", "가", "의")
# 조사처럼 끝나지만 한 단어인 것 (떼면 뜻이 바뀜)
_KEEP = {"주가", "최고가", "신고가", "유가", "물가", "원가", "시가", "종가", "단가", "호가", "평가", "증가", "국가",
         "전문가", "투자가", "가치", "사이", "차이", "하이", "데이", "회의", "합의", "논의", "협의", "심의", "주의"}
_STOP = {"속보", "종합", "단독", "오늘", "관련", "기자", "뉴스", "이번", "올해", "대비", "위해", "통해", "등", "및",
         "이후", "지난", "소식", "사진", "영상", "특징주",
         "the", "and", "for", "with", "from", "are", "its", "after", "amid", "says", "said", "into", "over", "new",
         "has", "have", "will", "what", "this", "that", "hits", "hit", "jumps", "jump", "rise", "rises", "fall",
         "falls", "signal", "signals", "rush", "cut", "cuts", "record", "high", "low", "all-time", "gains", "gain",
         "surge", "surges", "stocks", "stock", "market", "markets", "today", "why", "how", "more", "than", "but",
         "not", "about", "could", "would", "may", "officials", "shares", "week", "day"}
MAX_KEYWORD_LEN = 12      # 한글 키워드 칩 최대 글자 수 (영어는 단어가 길어 18자)


def too_long(k: str) -> bool:
    return len(k) > (18 if re.search(r"[A-Za-z]{3}", k) else MAX_KEYWORD_LEN)


def _strip_particle(tok: str) -> str:
    if tok in _KEEP or not re.search(r"[가-힣]$", tok):
        return tok
    for p in _PARTICLES2:
        if tok.endswith(p) and len(tok) - len(p) >= 2:
            return tok[:-len(p)]
    for p in _PARTICLES1:
        if tok.endswith(p) and len(tok) >= 3:
            return tok[:-1]
    return tok


def _tokens(title: str, lower: bool = True) -> list[str]:
    t = _BRACKETS.sub(" ", title.removeprefix("[공시]"))
    return [_strip_particle(w) for w in _SPLIT.split(t.lower() if lower else t) if w]


def classify(texts: list[str]) -> str:
    """제목(·스니펫) 묶음 → 주제. 단서 단어가 하나도 없으면 DEFAULT_CATEGORY."""
    toks = [tok for t in texts for tok in _tokens(t)]
    joined = " ".join(t.lower() for t in texts)
    best, best_score = DEFAULT_CATEGORY, 0.0
    for cat, cues in CATEGORIES.items():
        # 한글 단서는 부분 일치(영업이익률·순매수세), 영어는 단어 일치
        score = sum(joined.count(c) if re.search(r"[가-힣&]", c) else toks.count(c) for c in cues)
        if score > best_score:
            best, best_score = cat, score
    return best


def keywords(titles: list[str], exclude: list[str] | tuple[str, ...] = (), n: int = 3) -> list[str]:
    """여러 제목에 공통으로 나온 짧은 구. 두 단어 구를 우선하고, 서로 겹치는 후보는 하나만."""
    ex = [e.lower() for e in exclude if e]

    def usable(tok: str, orig: str) -> bool:
        if re.fullmatch(r"[a-z\-']+", tok) and len(tok) < 3 and not orig.isupper():
            return False   # 영어 짧은 단어(as, to)는 빼고 약어(AI)는 남김
        return len(tok) >= 2 and tok not in _STOP and not any(e in tok or tok in e for e in ex)

    score: dict[str, float] = defaultdict(float)
    first: dict[str, int] = {}
    shown: dict[str, str] = {}   # 소문자 키 → 처음 나온 원래 표기 (HBM4, FDA)
    for title in titles:
        seen: set[str] = set()   # 한 제목 안에서는 한 번만 센다
        # 두 단어 구가 쉼표·말줄임표를 건너뛰지 않도록 구절마다 따로 본다
        for clause in _CLAUSE.split(title):
            orig = _tokens(clause, lower=False)
            toks = [o.lower() for o in orig]
            for i, tok in enumerate(toks):
                ok = usable(tok, orig[i])
                cands = [(tok, orig[i], 1.0)] if ok and not _NUMERIC.match(tok) else []
                if (ok and i + 1 < len(toks) and usable(toks[i + 1], orig[i + 1])
                        and not _NUMERIC.match(toks[i + 1])):
                    cands.append((f"{tok} {toks[i + 1]}", f"{orig[i]} {orig[i + 1]}", 2.0))
                for c, disp, w in cands:
                    if c in seen or too_long(c):
                        continue
                    seen.add(c)
                    score[c] += w
                    first.setdefault(c, len(first))
                    shown.setdefault(c, disp)

    picked: list[str] = []
    for c in sorted(score, key=lambda c: (-score[c], first[c])):
        words = set(c.split())
        if any(words & set(p.split()) for p in picked):
            continue
        picked.append(c)
        if len(picked) == n:
            break
    return [shown[c] for c in picked]


def reason(headline: str, exclude: list[str] | tuple[str, ...] = (), max_len: int = 26) -> str:
    """헤드라인 → 짧은 이유 한 줄: 머리표·앞쪽 종목명을 떼고 '…' 앞 첫 구절만."""
    t = _BRACKETS.sub(" ", headline.removeprefix("[공시]")).strip()
    for name in sorted((e for e in exclude if e), key=len, reverse=True):
        if t.startswith(name):
            t = t[len(name):].lstrip(" ,·-")
            break
    t = re.split(r"…|\.\.\.|[;|]", t)[0].strip(" ,·-")
    t = re.sub(r"\s+", " ", t)
    return t if len(t) <= max_len else t[:max_len - 1].rstrip() + "…"
