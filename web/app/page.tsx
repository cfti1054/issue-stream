// 마켓 대시보드: 결론(지수·AI 요약)이 위, 근거(관심종목·차트·뉴스·업종)가 아래
import Link from "next/link";
import { ApiError, api, type Dashboard, type PriceSeries } from "@/lib/api";
import {
  INDEX_SYMBOLS, SENTI_LABEL, ago, dateKST, dir, isUS, num, pct, price, signed, stockChange, stockPrice, timeKST,
} from "@/lib/format";
import { Heatmap, SentimentBar, Sparkline } from "@/components/charts";
import PriceChart from "@/components/PriceChart";
import ErrorBox from "@/components/ErrorBox";
import CurrencyToggle from "@/components/CurrencyToggle";
import StatusBanner from "@/components/StatusBanner";
import { HoldToggle, StarButton, WatchSearch } from "@/components/watch";
import IssueSearch from "@/components/IssueSearch";

export const dynamic = "force-dynamic";

type Q = { ticker?: string; wl?: string; hm?: string; news?: string; nsort?: string; krw?: string };

export default async function DashboardPage({ searchParams }: { searchParams: Promise<Q> }) {
  const q = await searchParams;
  const { ticker } = q;
  // 관심종목·히트맵 탭 (?wl=us, ?hm=us). 다른 파라미터는 유지한 채 하나만 바꾼 주소
  const region = q.wl === "us" ? "us" : "kr";
  const hmRegion = q.hm === "us" ? "us" : "kr";
  const newsRegion = q.news === "us" ? "us" : "kr";   // AI 요약·주요 뉴스 탭
  const newsSort = q.nsort === "recent" ? "recent" : "importance";   // 주요 뉴스 정렬
  const issuesHref = (no?: number) => {
    const p = new URLSearchParams();
    if (newsRegion === "us") p.set("region", "us");
    if (newsSort === "recent") p.set("sort", "recent");
    if (no) return `/issues?no=${no}`;   // 그 이슈 1건만
    return `/issues${p.size ? `?${p}` : ""}`;
  };
  const newsTabs = (label: string) => (
    <span className="chips chips-s" role="group" aria-label={`${label} 지역`}>
      <Link href={href({ news: undefined })} scroll={false} aria-current={newsRegion === "kr"}>국내</Link>
      <Link href={href({ news: "us" })} scroll={false} aria-current={newsRegion === "us"}>미국</Link>
    </span>
  );
  const href = (patch: Q) => {
    const p = new URLSearchParams();
    const m: Q = { ...q, ...patch };
    (Object.keys(m) as (keyof Q)[]).forEach((k) => { if (m[k]) p.set(k, m[k]!); });
    return p.size ? `/?${p}` : "/";
  };
  let d: Dashboard;
  try {
    d = await api.dashboard(newsSort);
  } catch (e) {
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }

  const shown = d.watchlist.filter((w) => w.region === region);
  const count = { kr: d.watchlist.length - d.watchlist.filter((w) => w.region === "us").length,
                  us: d.watchlist.filter((w) => w.region === "us").length };
  const sectors = hmRegion === "us" ? d.sectors_us : d.sectors;
  const brief = newsRegion === "us" ? d.brief_us : d.brief;
  const topIssues = newsRegion === "us" ? d.issues_us : d.issues;

  // 차트 대상: URL 의 ?ticker= (관심종목이 아니어도 됨) → 현재 탭의 보유종목 → 현재 탭의 첫 관심종목
  const fallback = shown.find((w) => w.holding) ?? shown[0] ?? d.watchlist[0];
  const chartCode = ticker ?? fallback?.code;
  let series: PriceSeries | null = null;
  if (chartCode) {
    try { series = await api.prices(chartCode, 120, q.krw === "1" ? "krw" : undefined); } catch { series = null; }
  }
  const watched = d.watchlist.find((w) => w.code === chartCode);
  // 관심종목이 아니면 시세 데이터로 헤더를 채운다 (수집 대상이 아니면 시세가 비어 있을 수 있음)
  const last = series?.points.at(-1);
  const prev = series?.points.at(-2);
  const selected = watched ?? (chartCode && series ? {
    code: chartCode, name: series.name, market: series.market, close: last?.close ?? null, day: last?.day ?? null,
    change: last && prev ? last.close - prev.close : null, change_pct: last?.change_pct ?? null,
  } : undefined);
  const isStock = !!series?.is_stock;   // 지수·환율이면 ☆ 를 보여주지 않는다
  // 원화 보기(?krw=1): 미국 종목을 그날 원/달러로 환산. 헤더 값도 환산된 시세에서 꺼낸다
  const krwMode = series?.currency === "KRW";
  const head = krwMode && last ? {
    price: `${num(last.close, 0)}원`, change: signed(prev ? last.close - prev.close : null, 0), pct: last.change_pct,
  } : selected ? {
    price: stockPrice(selected.close, selected.market), change: stockChange(selected.change, selected.market),
    pct: selected.change_pct,
  } : null;
  const now = Date.now();

  return (
    <>
      <div className="page-head">
        <h1>마켓 대시보드</h1>
        <span className={`pill ${d.market_open ? "pill-live" : "pill-closed"}`}>국내 {d.market_open ? "장중" : "장 마감"}</span>
        <span className={`pill ${d.us_market_open ? "pill-live" : "pill-closed"}`}>미국 {d.us_market_open ? "장중" : "장 마감"}</span>
        {d.demo && <span className="pill pill-demo" title="issue-stream seed-demo --clear 로 삭제">데모 데이터</span>}
        <p className="num-s">업데이트 {timeKST(d.generated_at)}</p>
      </div>

      <StatusBanner s={d.collection}
        empty={!d.indices.length && !d.issues.length && !d.issues_us.length && !d.watchlist.some((w) => w.close)} />

      <div className="stack">
        {/* 1. 지수 스트립 */}
        <section aria-label="주요 지수" className="index-strip">
          {d.indices.length === 0 && <div className="card pad muted">지수 데이터 없음 — 수집기(issue-stream serve)가 채웁니다</div>}
          {d.indices.map((ix) => {
            const isIdx = INDEX_SYMBOLS.has(ix.symbol);
            return (
              <div key={ix.symbol} className="card index-card">
                <span className="label">{ix.name}{ix.stale && <span className="stale"> · {dateKST(ix.day)} 기준</span>}</span>
                <span className="num-l tnum">{price(ix.close, isIdx)}</span>
                <span className={`chg tnum ${dir(ix.change_pct)}`}>
                  {signed(ix.change, 2)} <span className="num-s">{pct(ix.change_pct)}</span>
                </span>
                <Sparkline values={ix.spark} width={84} height={40} label={`${ix.name} 최근 ${ix.spark.length}일 추이`} />
              </div>
            );
          })}
        </section>

        {/* 2. AI 요약 */}
        <section className="card brief" aria-label="AI 요약">
          <div className="brief-head">
            <span className="brief-tag">AI 요약</span>
            {newsTabs("AI 요약")}
            <span className="muted num-s">
              {brief.generated_by === "extractive" ? "추출 요약 (무료)" : brief.generated_by} · {timeKST(brief.generated_at)}
            </span>
          </div>
          <h2>{brief.headline}</h2>
          {brief.bullets.length > 0 ? (
            <ol>
              {brief.bullets.map((b, i) => (
                <li key={b.issue_no}>
                  <span className="rank tnum">{i + 1}</span>
                  <span className={`senti senti-${b.sentiment}`}>{SENTI_LABEL[b.sentiment]}</span>
                  <Link href={issuesHref(b.issue_no)}>{b.text}</Link>
                </li>
              ))}
            </ol>
          ) : <p className="muted">아직 요약할 이슈가 없습니다.</p>}
          <div className="brief-foot">
            <span>이슈 {brief.issue_count}건</span>
            <span className="senti-positive">긍정 {brief.tone.positive}</span>
            <span>중립 {brief.tone.neutral}</span>
            <span className="senti-negative">부정 {brief.tone.negative}</span>
            <Link href={issuesHref()} style={{ marginLeft: "auto" }}>이슈 브리핑 전체 보기 →</Link>
          </div>
        </section>

        {/* 3. 관심종목 / 차트 */}
        <div className="grid-2">
          <section className="card pad" aria-label="관심종목">
            <h2 className="section-title">관심종목 <small>뉴스 심리는 최근 24시간 기사 기준</small>
              {d.user && (
                <span className="right chips chips-s" role="group" aria-label="관심종목 지역">
                  <Link href={href({ wl: undefined })} scroll={false} aria-current={region === "kr"}>국내 {count.kr}</Link>
                  <Link href={href({ wl: "us" })} scroll={false} aria-current={region === "us"}>미국 {count.us}</Link>
                </span>
              )}
            </h2>
            {d.user && <WatchSearch />}
            {!d.user ? (
              <div className="empty">
                <Link className="btn" href="/login">로그인</Link>
                <p>로그인하면 원하는 종목을 ☆ 로 관심종목에 등록해 시세·뉴스 심리를 모아 볼 수 있습니다.</p>
                <p className="num-s">계정이 없으면 <Link href="/signup">가입하기</Link></p>
              </div>
            ) : shown.length === 0 ? (
              <div className="empty">
                {region === "us"
                  ? "미국 종목은 위 검색창에서 이름(엔비디아)이나 티커(NVDA)로 찾아 ☆ 를 누르세요"
                  : "위 검색창에서 종목을 찾아 ☆ 를 누르거나, 뉴스의 종목 태그를 눌러 차트에서 ☆ 를 누르세요"}
              </div>
            ) : (
              <div className="wl-scroll">
              <table className="wl">
                <thead>
                  <tr>
                    <th aria-label="관심종목" style={{ width: 28 }} />
                    <th>종목</th>
                    <th className="r">현재가</th>
                    <th className="r">등락</th>
                    <th className="hide-sm">뉴스 심리</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((w) => (
                    <tr key={w.code} aria-selected={w.code === selected?.code}>
                      <td className="star-cell"><StarButton code={w.code} name={w.name} watched size="s" /></td>
                      <td>
                        <div className="name-row">
                          <Link className="row-link" href={href({ ticker: w.code })} scroll={false}>
                            <span className="name">{w.name}</span>
                            <span className="code">{w.code}</span>
                          </Link>
                          <HoldToggle code={w.code} holding={w.holding} />
                        </div>
                        {w.top_issue && (
                          <Link className="issue-link" href={`/issues?no=${w.top_issue.no}`}
                            title={w.top_issue.headline}>↳ {w.top_issue.headline}</Link>
                        )}
                      </td>
                      <td className="r tnum" style={{ fontWeight: 600 }}>
                        {stockPrice(w.close, w.market)}
                        {w.stale && w.day && <div className="stale">{dateKST(w.day)} 기준</div>}
                      </td>
                      <td className={`r tnum ${dir(w.change_pct)}`}>
                        <div style={{ fontWeight: 600 }}>{pct(w.change_pct)}</div>
                        <div className="num-s">{stockChange(w.change, w.market)}</div>
                      </td>
                      <td className="hide-sm" style={{ width: 140 }}><SentimentBar c={w.sentiment} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </section>

          <section className="card pad" aria-label="가격 차트">
            {selected && series ? (
              <>
                <h2 className="section-title">
                  {d.user && isStock && <StarButton code={selected.code} name={selected.name} watched={!!watched} />}
                  {selected.name} <small>{selected.code}</small>
                  {!d.user && isStock && <Link className="num-s" href={`/login?next=${encodeURIComponent(`/?ticker=${selected.code}`)}`}>로그인하고 ☆ 관심종목 등록</Link>}
                  <span className="right" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    {series.convertible && (
                      <CurrencyToggle krw={krwMode} offHref={href({ krw: undefined })} onHref={href({ krw: "1" })} />
                    )}
                    종가 · 일봉
                  </span>
                </h2>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
                  <span className="num-l tnum">{head?.price}</span>
                  <span className={`num-m tnum ${dir(head?.pct)}`} style={{ fontWeight: 600 }}>
                    {head?.change} ({pct(head?.pct)})
                  </span>
                  <span className="muted num-s">{selected.day}</span>
                </div>
                {series.points.length > 0 ? <PriceChart points={series.points} isIndex={isUS(selected.market)}
                    digits={krwMode ? 0 : undefined} />
                  : <div className="empty">시세를 불러오지 못했습니다. 시세 소스가 응답하지 않거나 거래되지 않는 종목입니다.</div>}
              </>
            ) : <div className="empty">{d.user ? "관심종목을 추가하면 가격 차트가 표시됩니다" : "뉴스의 종목 태그를 누르면 가격 차트가 표시됩니다"}</div>}
          </section>
        </div>

        {/* 4. 주요 뉴스 / 업종 히트맵 */}
        <div className="grid-2b">
          <section className="card pad" aria-label="주요 뉴스">
            <h2 className="section-title">주요 뉴스 <small>이슈 단위 · {newsSort === "recent" ? "최신순" : "중요도순"}</small>
              <span className="right" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                {newsTabs("주요 뉴스")}
                <Link href={issuesHref()}>전체 →</Link>
              </span>
            </h2>
            <div className="news-tools">
              <span className="chips chips-s" role="group" aria-label="주요 뉴스 정렬">
                <Link href={href({ nsort: undefined })} scroll={false} aria-current={newsSort === "importance"}>중요도순</Link>
                <Link href={href({ nsort: "recent" })} scroll={false} aria-current={newsSort === "recent"}>최신순</Link>
              </span>
              <IssueSearch compact keep={{ sort: newsSort === "recent" ? "recent" : undefined }} />
            </div>
            {topIssues.length === 0 ? <div className="empty">최근 24시간 {newsRegion === "us" ? "미국 시장 " : ""}이슈가 없습니다</div> : (
              <ul className="news-list">
                {topIssues.map((it) => (
                  <li key={it.no}>
                    <span className={`score tnum ${it.importance >= 60 ? "hot" : ""}`} title="중요도">
                      {Math.round(it.importance)}
                    </span>
                    <div>
                      <Link className="headline" href={issuesHref(it.no)}>{it.summary?.headline ?? "요약 대기"}</Link>
                      <div className="meta">
                        <span className={`senti senti-${it.sentiment}`}>{SENTI_LABEL[it.sentiment]}</span>
                        <span>{it.sources[0]?.publisher} 외 {Math.max(0, it.publisher_count - 1)}곳</span>
                        <span>기사 {it.article_count}건</span>
                        <span>{ago(it.last_seen, now)}</span>
                      </div>
                    </div>
                    <div className="tickers">
                      {it.tickers.slice(0, 2).map((t) => (
                        <Link key={t.code} className="ticker" href={href({ ticker: t.code })} scroll={false}>{t.name}</Link>
                      ))}
                      {it.tickers.length > 2 && (
                        <Link className="ticker ticker-more" href={issuesHref(it.no)}
                          title={`관련 종목 ${it.tickers.length}개: ${it.tickers.map((t) => t.name).join(", ")}`}
                          aria-label={`관련 종목 ${it.tickers.length - 2}개 더 보기`}>…</Link>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card pad" aria-label="업종 히트맵">
            <h2 className="section-title">업종 히트맵{" "}
              <small>
                {sectors.basis === "us_etf" ? "미국 업종 ETF 전일 대비 등락률"
                  : sectors.basis === "etf" ? "업종 ETF 전일 대비 등락률" : "KRX 업종 지수 등락률"}
                {sectors.day ? ` · ${sectors.day}` : ""}
              </small>
              <span className="right chips chips-s" role="group" aria-label="업종 히트맵 지역">
                <Link href={href({ hm: undefined })} scroll={false} aria-current={hmRegion === "kr"}>국내</Link>
                <Link href={href({ hm: "us" })} scroll={false} aria-current={hmRegion === "us"}>미국</Link>
              </span>
            </h2>
            {sectors.items.length === 0
              ? <div className="empty">업종 데이터 없음 — 수집기가 채웁니다
                  (config/sources.yaml 의 {hmRegion === "us" ? "us_sector_etfs" : "sector_etfs"})</div>
              : <Heatmap items={sectors.items} />}
          </section>
        </div>
      </div>
    </>
  );
}
