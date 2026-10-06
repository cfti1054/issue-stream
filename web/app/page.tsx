// 마켓 대시보드: 결론(지수·AI 요약)이 위, 근거(관심종목·차트·뉴스·업종)가 아래
import Link from "next/link";
import { ApiError, api, type Dashboard, type PriceSeries } from "@/lib/api";
import { INDEX_SYMBOLS, SENTI_LABEL, ago, dateKST, dir, pct, price, signed, timeKST } from "@/lib/format";
import { Heatmap, SentimentBar, Sparkline } from "@/components/charts";
import PriceChart from "@/components/PriceChart";
import ErrorBox from "@/components/ErrorBox";
import StatusBanner from "@/components/StatusBanner";

export const dynamic = "force-dynamic";

export default async function DashboardPage({ searchParams }: { searchParams: Promise<{ ticker?: string }> }) {
  const { ticker } = await searchParams;
  let d: Dashboard;
  try {
    d = await api.dashboard();
  } catch (e) {
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }

  // 차트 대상: URL 의 ?ticker= → 보유종목 → 첫 관심종목
  const selected = d.watchlist.find((w) => w.code === ticker)
    ?? d.watchlist.find((w) => w.holding) ?? d.watchlist[0];
  let series: PriceSeries | null = null;
  if (selected) {
    try { series = await api.prices(selected.code, 120); } catch { series = null; }
  }
  const now = Date.now();

  return (
    <>
      <div className="page-head">
        <h1>마켓 대시보드</h1>
        <span className={`pill ${d.market_open ? "pill-live" : "pill-closed"}`}>{d.market_open ? "장중" : "장 마감"}</span>
        {d.demo && <span className="pill pill-demo" title="issue-stream seed-demo --clear 로 삭제">데모 데이터</span>}
        <p className="num-s">업데이트 {timeKST(d.generated_at)}</p>
      </div>

      <StatusBanner s={d.collection} empty={!d.indices.length && !d.issues.length && !d.watchlist.some((w) => w.close)} />

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
            <span className="muted num-s">
              {d.brief.generated_by === "extractive" ? "추출 요약 (무료)" : d.brief.generated_by} · {timeKST(d.brief.generated_at)}
            </span>
          </div>
          <h2>{d.brief.headline}</h2>
          {d.brief.bullets.length > 0 ? (
            <ol>
              {d.brief.bullets.map((b, i) => (
                <li key={b.issue_id}>
                  <span className="rank tnum">{i + 1}</span>
                  <span className={`senti senti-${b.sentiment}`}>{SENTI_LABEL[b.sentiment]}</span>
                  <Link href={`/issues#issue-${b.issue_id}`}>{b.text}</Link>
                </li>
              ))}
            </ol>
          ) : <p className="muted">아직 요약할 이슈가 없습니다.</p>}
          <div className="brief-foot">
            <span>이슈 {d.brief.issue_count}건</span>
            <span className="senti-positive">긍정 {d.brief.tone.positive}</span>
            <span>중립 {d.brief.tone.neutral}</span>
            <span className="senti-negative">부정 {d.brief.tone.negative}</span>
            <Link href="/issues" style={{ marginLeft: "auto" }}>이슈 브리핑 전체 보기 →</Link>
          </div>
        </section>

        {/* 3. 관심종목 / 차트 */}
        <div className="grid-2">
          <section className="card pad" aria-label="관심종목">
            <h2 className="section-title">관심종목 <small>뉴스 심리는 최근 24시간 기사 기준</small></h2>
            {d.watchlist.length === 0 ? <div className="empty">config/watchlist.yaml 에 종목을 추가하세요</div> : (
              <table className="wl">
                <thead>
                  <tr>
                    <th>종목</th>
                    <th className="r">현재가</th>
                    <th className="r">등락</th>
                    <th className="hide-sm">뉴스 심리</th>
                  </tr>
                </thead>
                <tbody>
                  {d.watchlist.map((w) => (
                    <tr key={w.code} aria-selected={w.code === selected?.code}>
                      <td>
                        <Link className="row-link" href={`/?ticker=${w.code}`} scroll={false}>
                          <span className="name">{w.name}{w.holding && <span className="hold">보유</span>}</span>
                          <span className="code">{w.code}</span>
                        </Link>
                        {w.top_issue && (
                          <Link className="issue-link" href={`/issues?ticker=${w.code}#issue-${w.top_issue.id}`}
                            title={w.top_issue.headline}>↳ {w.top_issue.headline}</Link>
                        )}
                      </td>
                      <td className="r tnum" style={{ fontWeight: 600 }}>
                        {price(w.close)}
                        {w.stale && w.day && <div className="stale">{dateKST(w.day)} 기준</div>}
                      </td>
                      <td className={`r tnum ${dir(w.change_pct)}`}>
                        <div style={{ fontWeight: 600 }}>{pct(w.change_pct)}</div>
                        <div className="num-s">{signed(w.change)}</div>
                      </td>
                      <td className="hide-sm" style={{ width: 140 }}><SentimentBar c={w.sentiment} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card pad" aria-label="가격 차트">
            {selected && series ? (
              <>
                <h2 className="section-title">
                  {selected.name} <small>{selected.code}</small>
                  <span className="right">종가 · 일봉</span>
                </h2>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
                  <span className="num-l tnum">{price(selected.close)}</span>
                  <span className={`num-m tnum ${dir(selected.change_pct)}`} style={{ fontWeight: 600 }}>
                    {signed(selected.change)} ({pct(selected.change_pct)})
                  </span>
                  <span className="muted num-s">{selected.day}</span>
                </div>
                <PriceChart points={series.points} />
              </>
            ) : <div className="empty">시세 데이터가 없습니다</div>}
          </section>
        </div>

        {/* 4. 주요 뉴스 / 업종 히트맵 */}
        <div className="grid-2b">
          <section className="card pad" aria-label="주요 뉴스">
            <h2 className="section-title">주요 뉴스 <small>이슈 단위 · 중요도순</small>
              <Link className="right" href="/issues">전체 →</Link>
            </h2>
            {d.issues.length === 0 ? <div className="empty">최근 24시간 이슈가 없습니다</div> : (
              <ul className="news-list">
                {d.issues.map((it) => (
                  <li key={it.id}>
                    <span className={`score tnum ${it.importance >= 60 ? "hot" : ""}`} title="중요도">
                      {Math.round(it.importance)}
                    </span>
                    <div>
                      <Link className="headline" href={`/issues#issue-${it.id}`}>{it.summary?.headline ?? "요약 대기"}</Link>
                      <div className="meta">
                        <span className={`senti senti-${it.sentiment}`}>{SENTI_LABEL[it.sentiment]}</span>
                        <span>{it.sources[0]?.publisher} 외 {Math.max(0, it.publisher_count - 1)}곳</span>
                        <span>기사 {it.article_count}건</span>
                        <span>{ago(it.last_seen, now)}</span>
                      </div>
                    </div>
                    <div className="tickers">
                      {it.tickers.slice(0, 2).map((t) => (
                        <Link key={t.code} className="ticker" href={`/?ticker=${t.code}`} scroll={false}>{t.name}</Link>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card pad" aria-label="업종 히트맵">
            <h2 className="section-title">업종 히트맵{" "}
              <small>{d.sectors.basis === "etf" ? "업종 ETF 전일 대비 등락률" : "KRX 업종 지수 등락률"}</small>
              <span className="right">{d.sectors.day ?? ""}</span>
            </h2>
            {d.sectors.items.length === 0
              ? <div className="empty">업종 데이터 없음 — 수집기가 채웁니다 (config/sources.yaml 의 sector_etfs)</div>
              : <Heatmap items={d.sectors.items} />}
          </section>
        </div>
      </div>
    </>
  );
}
