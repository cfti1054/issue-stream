from datetime import datetime, timedelta, timezone

import numpy as np

from issue_stream.pipeline.cluster import assign
from issue_stream.pipeline.dedupe import find_duplicate, hamming, simhash
from issue_stream.pipeline.importance import ImportanceInput, importance
from issue_stream.pipeline.normalize import normalize_title
from issue_stream.pipeline.tagging import TickerEntry, TickerTagger
from issue_stream.providers.embedding import HashingEmbedder
from issue_stream.providers.sentiment import LexiconSentiment
from issue_stream.providers.summarizer import ArticleInput, ExtractiveSummarizer, _parse


def test_normalize_strips_tags():
    assert normalize_title("[속보] 삼성전자, 3분기 영업익 10조…'사상 최대'") == \
        normalize_title("삼성전자 3분기 영업익 10조 사상 최대 (종합)")


def test_simhash_near_duplicate():
    a = simhash(normalize_title("삼성전자 3분기 영업이익 10조원 돌파…시장 예상 상회"))
    b = simhash(normalize_title("[종합] 삼성전자 3분기 영업이익 10조원 돌파, 시장 예상 상회"))
    c = simhash(normalize_title("한국은행 기준금리 동결…연내 인하 가능성 시사"))
    assert hamming(a, b) < hamming(a, c)
    assert find_duplicate(a, {1: b, 2: c}, threshold=12) == 1
    assert -(1 << 63) <= a < (1 << 63)  # BIGINT 범위


def test_tagger_longest_match_and_boundaries():
    t = TickerTagger([
        TickerEntry("005380", ("현대차", "현대자동차")),
        TickerEntry("001500", ("현대차증권",)),
        TickerEntry("000720", ("현대건설",)),
        TickerEntry("000660", ("SK하이닉스", "하이닉스")),
        TickerEntry("034730", ("SK",)),
    ])
    assert t.tag("현대차증권, 현대차 목표가 상향") == {"001500": 1, "005380": 1}
    assert t.tag("현대차는 오늘") == {"005380": 1}         # 조사 허용
    assert t.tag("SK하이닉스 신고가") == {"000660": 1}     # SK 로 중복 태깅 안 됨
    assert "000720" not in t.tag("현대건설기계 수주")       # 다른 회사명의 일부


def test_importance_is_additive_not_zeroed():
    base = dict(article_count=8, publisher_count=5, articles_last_hour=4, touches_watchlist=True,
                has_disclosure=True)
    with_hold, _ = importance(ImportanceInput(touches_holding=True, **base))
    no_hold, _ = importance(ImportanceInput(touches_holding=False, **base))
    assert 0 < no_hold < with_hold <= 100      # 보유 아님 ≠ 0점


def test_hashing_embedder_clusters_same_event():
    emb = HashingEmbedder(384)
    titles = [
        "삼성전자 3분기 영업이익 10조원 돌파",
        "삼성전자, 3분기 영업이익 10조 돌파 '어닝 서프라이즈'",
        "한국은행 기준금리 연 3.0% 동결",
        "한은 기준금리 동결…3.0% 유지",
    ]
    v = emb.embed(titles)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)
    clusters = assign(v, [], threshold=0.35)
    groups = sorted(sorted(c.members) for c in clusters)
    assert groups == [[0, 1], [2, 3]]


def test_lexicon_sentiment():
    s = LexiconSentiment().classify(["주가 급등 신고가", "실적 부진에 급락", "주주총회 개최"])
    assert s == ["positive", "negative", "neutral"]


def _articles():
    now = datetime.now(timezone.utc)
    return [
        ArticleInput("1", "삼성전자 3분기 영업이익 10조원 돌파", "한국경제", now, "시장 예상 8조원을 크게 웃돌았다.",
                     sentiment="positive", tickers=["005930"]),
        ArticleInput("2", "삼성전자 3분기 영업익 10조…HBM 효과", "매일경제", now - timedelta(minutes=5),
                     "HBM 판매 확대가 실적을 견인했다.", sentiment="positive", tickers=["005930"]),
        ArticleInput("3", "[공시] 삼성전자 - 연결재무제표기준영업(잠정)실적(공정공시)", "DART", now,
                     kind="disclosure", tickers=["005930"]),
    ]


def test_extractive_summary_news_headline_with_disclosure_anchor():
    s = ExtractiveSummarizer().summarize(_articles())
    assert not s.headline.startswith("[공시]")
    assert s.bullets[0].startswith("공시:")
    assert "3" in s.source_article_ids
    assert s.affected_tickers == ["005930"]
    assert set(s.source_article_ids) <= {"1", "2", "3"}
    assert s.generated_by == "extractive"


def test_llm_output_is_sanitized():
    raw = ('설명 {"headline":"h","bullets":["a"],"sentiment":"positive","affected_tickers":["005930","999999"],'
           '"confidence":0.8,"conflicting_views":false,"source_article_ids":["1","42"]} 끝')
    s = _parse(raw, "ollama:test", _articles())
    assert s.affected_tickers == ["005930"]     # 입력에 없는 종목 제거
    assert s.source_article_ids == ["1"]        # 입력에 없는 기사 id 제거


def test_disclosure_joins_same_ticker_issue_only():
    emb = HashingEmbedder(384)
    titles = ["삼성전자 3분기 영업이익 10조원 돌파", "삼성전자 3분기 영업익 10조 돌파 호실적",
              "[공시] 삼성전자 - 연결재무제표기준영업(잠정)실적(공정공시)",
              "[공시] 현대차 - 연결재무제표기준영업(잠정)실적(공정공시)"]
    clusters = assign(emb.embed(titles), [], threshold=0.35,
                      tickers=[["005930"], ["005930"], ["005930"], ["005380"]],
                      kinds=["news", "news", "disclosure", "disclosure"])
    groups = sorted(sorted(c.members) for c in clusters)
    assert groups == [[0, 1, 2], [3]]


def test_topics_category_keywords_reason():
    from issue_stream.pipeline import topics
    titles = ["SK하이닉스 HBM4 양산 돌입…엔비디아 공급 확대", "SK하이닉스, HBM4 양산 돌입 엔비디아 공급 확대 기대",
              "SK하이닉스 HBM4 양산 돌입 소식에 신고가"]
    assert topics.classify(titles) == "신제품·기술"
    kw = topics.keywords(titles, ["SK하이닉스", "엔비디아"])
    assert kw[0] == "HBM4 양산" and "공급 확대" in kw           # 원래 표기 유지, 종목명 제외
    assert all("SK하이닉스" not in k for k in kw)
    assert topics.keywords(["원달러 환율 1,380원대 하락"])[1] == "1,380원대 하락"   # 숫자 쉼표는 자르지 않음
    assert topics.reason("[속보] 삼성전자, 3분기 영업이익 10조원 돌파…시장 예상 상회", ["삼성전자"]) == \
        "3분기 영업이익 10조원 돌파"
    assert topics.classify(["오늘의 날씨"]) == topics.DEFAULT_CATEGORY


def test_summaries_carry_signal_fields():
    arts = _articles()
    for a in arts:
        a.ticker_names = ["삼성전자"]
    s = ExtractiveSummarizer().summarize(arts)
    assert s.category == "실적" and s.keywords and s.reason
    assert all("삼성전자" not in k for k in s.keywords)
    # LLM 이 목록 밖 주제·긴 키워드를 주면 규칙으로 고친다
    raw = ('{"headline":"h","bullets":[],"sentiment":"neutral","affected_tickers":[],"confidence":0.5,'
           '"conflicting_views":false,"source_article_ids":[],"category":"반도체 호황",'
           '"keywords":["이건 열두 글자를 훨씬 넘는 너무 긴 키워드"],"reason":"HBM 판매 확대로"}')
    p = _parse(raw, "ollama:test", arts)
    assert p.category == "실적" and p.keywords and p.reason == "HBM 판매 확대로"
