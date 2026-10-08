// 코인: ① 시장 요약(시가총액·BTC 점유율·공포탐욕·김치 프리미엄) → ② 주요 코인 카드 →
// ③ 선택 코인 차트(원화 | 달러) · ④ 김치 프리미엄 표 → ⑤ 업비트 원화 시장 순위(거래대금·상승·하락)
import Link from "next/link";
import { ApiError, api, type CoinBoard, type CoinRank, type PriceSeries } from "@/lib/api";
import { dateKST, dir, num, pct, signed, timeKST } from "@/lib/format";
import { Sparkline } from "@/components/charts";
import PriceChart from "@/components/PriceChart";
import ErrorBox from "@/components/ErrorBox";
import CurrencyToggle from "@/components/CurrencyToggle";

export const dynamic = "force-dynamic";

type Q = { c?: string; usd?: string; rk?: string };
const RANKS = [["value", "거래대금"], ["up", "상승률"], ["down", "하락률"]] as const;

/** 코인 원화가: 100원 이상은 정수, 그 아래는 업비트 호가 단위에 맞춰 소수 */
const wonDigits = (v: number) => (v >= 100 ? 0 : v >= 1 ? 2 : 4);
const won = (v: number | null | undefined) => (v === null || v === undefined ? "–" : num(v, wonDigits(v)));
/** 억·만 단위까지 (1억 1,305만): 김치 프리미엄처럼 몇 % 차이를 보여야 할 때 */
function manWon(v: number): string {
  const eok = Math.floor(v / 1e8), man = Math.round((v % 1e8) / 1e4);
  return eok ? `${eok}억${man ? ` ${num(man, 0)}만` : ""}` : `${num(man, 0)}만`;
}
/** 큰 원화 금액: 조·억 단위 */
function bigWon(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  if (v >= 1e12) return `${num(v / 1e12, 1)}조`;
  if (v >= 1e8) return `${num(v / 1e8, 0)}억`;
  return num(v, 0);
}

export default async function CoinsPage({ searchParams }: { searchParams: Promise<Q> }) {
  const q = await searchParams;
  const usd = q.usd === "1";
  const rk = RANKS.find(([k]) => k === q.rk)?.[0] ?? "value";
  const href = (patch: Q) => {
    const p = new URLSearchParams();
    const m: Q = { ...q, ...patch };
    (Object.keys(m) as (keyof Q)[]).forEach((k) => { if (m[k]) p.set(k, m[k]!); });
    return p.size ? `/coins?${p}` : "/coins";
  };
  let d: CoinBoard;
  try {
    d = await api.coins();
  } catch (e) {
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }
  const sel = d.coins.find((c) => c.code === q.c) ?? d.coins[0];
  let series: PriceSeries | null = null;
  if (sel) {
    try { series = await api.prices(sel.symbol, 130, usd ? "usd" : undefined); } catch { series = null; }
  }
  const usdMode = series?.currency === "USD";
  const closes = series?.points.map((p) => p.close) ?? [];
  const lastClose = closes.at(-1) ?? sel?.price ?? 0;
  const chartDigits = usdMode ? (lastClose >= 1 ? 2 : 4) : wonDigits(lastClose);
  const fmt = (v: number | null | undefined) =>
    v === null || v === undefined ? "–" : usdMode ? `$${num(v, chartDigits)}` : `${num(v, chartDigits)}원`;
  const s = d.summary;
  const fg = s.fear_greed;
  const rows: CoinRank[] = d.ranking[rk];
  const maxPrem = Math.max(1, ...d.premium.map((p) => Math.abs(p.premium_pct)));

  return (
    <>
      <div className="page-head">
        <h1>코인</h1>
        <span className="pill">24시간 거래</span>
        <p className="num-s">업데이트 {timeKST(d.updated_at)} · 업비트 원화 시장 {s.markets}종목</p>
      </div>

      <div className="stack">
        {/* ① 시장 요약 */}
        <section className="cn-summary" aria-label="시장 요약">
          <div className="card cn-stat">
            <span className="label">전체 시가총액</span>
            <span className="v tnum">{s.market_cap_usd ? `$${num(s.market_cap_usd / 1e12, 2)}조` : "–"}</span>
            <span className="sub">
              {s.market_cap_krw ? `약 ${bigWon(s.market_cap_krw)}원` : ""}
              {s.market_cap_change_pct !== null && (
                <span className={dir(s.market_cap_change_pct)}> · 24시간 {pct(s.market_cap_change_pct)}</span>
              )}
            </span>
          </div>
          <div className="card cn-stat">
            <span className="label">BTC 점유율</span>
            <span className="v tnum">{s.btc_dominance !== null ? `${num(s.btc_dominance, 1)}%` : "–"}</span>
            <span className="sub">
              {s.eth_dominance !== null && s.btc_dominance !== null
                ? `ETH ${num(s.eth_dominance, 1)}% · 나머지 ${num(100 - s.btc_dominance - s.eth_dominance, 1)}%` : "코인게코"}
            </span>
          </div>
          <div className="card cn-stat">
            <span className="label">공포·탐욕 지수
              {fg && <span className={`cn-fg ${fg.value >= 55 ? "greed" : fg.value <= 45 ? "fear" : ""}`}>{fg.label}</span>}
            </span>
            <span className="v tnum">{fg ? fg.value : "–"}
              <small> / 100{fg?.prev !== null && fg?.prev !== undefined ? ` · 어제 ${fg.prev}` : ""}</small>
            </span>
            {fg && <div className="cn-gauge" role="img" aria-label={`0 극단적 공포 ~ 100 극단적 탐욕 중 ${fg.value}`}>
              <b style={{ left: `calc(${fg.value}% - 2px)` }} /></div>}
          </div>
          <div className="card cn-stat">
            <span className="label">김치 프리미엄 (BTC)</span>
            <span className={`v tnum ${dir(s.kimchi?.premium_pct)}`}>{s.kimchi ? pct(s.kimchi.premium_pct) : "–"}</span>
            <span className="sub">{s.kimchi
              ? `업비트 ${manWon(s.kimchi.upbit)} vs 해외 ${manWon(s.kimchi.global_krw)}원` : "해외 시세를 받지 못했습니다"}</span>
          </div>
        </section>

        {/* ② 주요 코인 */}
        <section aria-label="주요 코인">
          <h2 className="section-title">주요 코인 <small>업비트 원화 시세 · 24시간 등락 · 30일 추이</small></h2>
          {d.coins.length === 0 ? <div className="card pad muted">코인 시세를 받지 못했습니다 (config/sources.yaml 의 coins)</div> : (
            <div className="index-strip cn-coins">
              {d.coins.map((c) => (
                <Link key={c.code} className="card index-card fx-card" href={href({ c: c.code })} scroll={false}
                  aria-current={c.code === sel?.code ? "true" : undefined}>
                  <span className="label">{c.name} <span className="muted">{c.code}</span>
                    {!c.live && <span className="stale"> · 지연</span>}</span>
                  <span className="num-l tnum">{won(c.price)}</span>
                  <span className={`chg tnum ${dir(c.change_pct)}`}>
                    {signed(c.change, wonDigits(c.price))} <span className="num-s">{pct(c.change_pct)}</span>
                  </span>
                  <Sparkline values={c.spark} width={64} height={40} label={`${c.name} 최근 ${c.spark.length}일 추이`} />
                </Link>
              ))}
            </div>
          )}
        </section>

        <div className="grid-2">
          {/* ③ 차트 */}
          <section className="card pad" aria-label="코인 차트">
            {sel ? (
              <>
                <h2 className="section-title">
                  {sel.name} <small>{sel.code} · {usdMode ? "달러" : "원"}</small>
                  <CurrencyToggle krw={usdMode} offHref={href({ usd: undefined })} onHref={href({ usd: "1" })}
                    offLabel="원화" onLabel="달러" onTitle="그날 원/달러 환율로 나눈 달러 가격" />
                  <span className="right">일봉{sel.since ? ` · ${dateKST(sel.since)} 이후` : ""} 최고 {fmt(closes.length ? Math.max(...closes) : null)}
                    {" "}/ 최저 {fmt(closes.length ? Math.min(...closes) : null)}</span>
                </h2>
                {series && series.points.length > 1
                  ? <PriceChart points={series.points} digits={chartDigits} />
                  : <div className="empty">과거 시세를 모으는 중입니다</div>}
              </>
            ) : <div className="empty">코인을 고르면 차트가 표시됩니다</div>}
          </section>

          {/* ④ 김치 프리미엄 */}
          <section className="card pad" aria-label="김치 프리미엄">
            <h2 className="section-title">김치 프리미엄
              <small>업비트 원화가 vs 해외 달러가 × 원/달러{s.usdkrw ? ` ${num(s.usdkrw, 1)}` : ""}</small></h2>
            {d.premium.length === 0 ? <div className="empty">해외 시세를 받지 못했습니다</div> : (
              <div className="cn-tbl">
                <table className="cn-table">
                  <thead><tr><th>코인</th><th className="r">업비트</th><th className="r">해외 (원 환산)</th><th className="r">차이</th></tr></thead>
                  <tbody>
                    {d.premium.map((p) => (
                      <tr key={p.code}>
                        <td><b>{p.name}</b> <span className="muted">{p.code}</span></td>
                        <td className="r tnum">{won(p.upbit)}</td>
                        <td className="r tnum" title={`$${num(p.global_usd, p.global_usd >= 1 ? 2 : 4)}`}>{won(p.global_krw)}</td>
                        <td className={`r tnum ${dir(p.premium_pct)}`}>
                          <span className={`cn-bar ${p.premium_pct >= 0 ? "up" : "down"}`}
                            style={{ width: `${Math.max(2, (Math.abs(p.premium_pct) / maxPrem) * 48)}px` }} aria-hidden />
                          {pct(p.premium_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="muted num-s" style={{ margin: "10px 0 0" }}>
              +면 국내가 더 비쌉니다. 보통 ±3% 안쪽이고, 크게 벌어지면 국내 매수세 과열 신호로 봅니다.
            </p>
          </section>
        </div>

        {/* ⑤ 업비트 순위 */}
        <section className="card pad" aria-label="업비트 원화 시장 순위">
          <h2 className="section-title">업비트 원화 시장 순위
            <small>{rk === "value" ? "24시간 거래대금" : "24시간 등락률 · 거래대금 상위 100종목 중"}</small>
            <span className="right chips chips-s" role="group" aria-label="순위 기준">
              {RANKS.map(([k, label]) => (
                <Link key={k} href={href({ rk: k === "value" ? undefined : k })} scroll={false} aria-current={rk === k}>{label}</Link>
              ))}
            </span>
          </h2>
          <div className="cn-tbl">
            <table className="cn-table">
              <thead><tr><th style={{ width: 28 }} /><th>코인</th><th className="r">현재가</th><th className="r">24시간</th><th className="r">거래대금</th></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.market}>
                    <td className="muted tnum">{i + 1}</td>
                    <td><b>{r.name}</b> <span className="muted">{r.code}</span></td>
                    <td className="r tnum">{won(r.price)}</td>
                    <td className={`r tnum ${dir(r.change_pct)}`}>{pct(r.change_pct)}</td>
                    <td className="r tnum">{bigWon(r.volume_krw)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
