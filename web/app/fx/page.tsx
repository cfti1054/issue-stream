// 환율: 원화 환율(하나은행 고시 매매기준율)과 달러 지표(달러 인덱스·교차 환율), 선택 통화 차트·계산기
import Link from "next/link";
import { ApiError, api, type FxBoard, type FxItem, type PriceSeries } from "@/lib/api";
import { dateKST, dir, num, pct, signed, timeKST } from "@/lib/format";
import { Sparkline } from "@/components/charts";
import PriceChart from "@/components/PriceChart";
import ErrorBox from "@/components/ErrorBox";
import FxConverter from "@/components/FxConverter";

export const dynamic = "force-dynamic";

/** EUR/USD 처럼 1 근처 값은 소수 4자리, 나머지는 2자리 */
const digitsOf = (v: number) => (v < 10 ? 4 : 2);
const isKRW = (it: FxItem) => it.symbol.endsWith("/KRW");

export default async function FxPage({ searchParams }: { searchParams: Promise<{ c?: string }> }) {
  const { c } = await searchParams;
  let d: FxBoard;
  try {
    d = await api.fx();
  } catch (e) {
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }
  const krw = d.items.filter(isKRW);
  const usd = d.items.filter((it) => !isKRW(it));
  const sel = d.items.find((it) => it.symbol === c) ?? d.items[0];
  let series: PriceSeries | null = null;
  if (sel) {
    try { series = await api.prices(sel.symbol, 130); } catch { series = null; }
  }

  const card = (it: FxItem) => {
    const dg = digitsOf(it.close);
    return (
      <Link key={it.symbol} className="card index-card fx-card" href={`/fx?c=${encodeURIComponent(it.symbol)}`}
        scroll={false} aria-current={it.symbol === sel?.symbol ? "true" : undefined}>
        <span className="label">
          {it.name} <span className="muted">{isKRW(it) ? `${it.unit} ${it.currency}` : it.symbol}</span>
          {it.stale && <span className="stale"> · {dateKST(it.day)} 기준</span>}
        </span>
        <span className="num-l tnum">{num(it.close, dg)}</span>
        <span className={`chg tnum ${dir(it.change_pct)}`}>
          {signed(it.change, dg)} <span className="num-s">{pct(it.change_pct)}</span>
        </span>
        <Sparkline values={it.spark} width={84} height={40} label={`${it.name} 최근 ${it.spark.length}일 추이`} />
      </Link>
    );
  };

  return (
    <>
      <div className="page-head">
        <h1>환율</h1>
        {d.updated_at && <p className="num-s">업데이트 {timeKST(d.updated_at)}</p>}
      </div>

      <div className="stack">
        {d.items.length === 0 && (
          <div className="card pad muted">환율 데이터 없음 — 수집기(issue-stream serve)가 채웁니다 (config/sources.yaml 의 fx_rates)</div>
        )}

        {krw.length > 0 && (
          <section aria-label="원화 환율">
            <h2 className="section-title">원화 환율 <small>하나은행 고시 매매기준율 · 원</small></h2>
            <div className="index-strip">{krw.map(card)}</div>
          </section>
        )}
        {usd.length > 0 && (
          <section aria-label="달러 지표">
            <h2 className="section-title">달러 지표 <small>달러 인덱스 · 주요 교차 환율</small></h2>
            <div className="index-strip">{usd.map(card)}</div>
          </section>
        )}

        {sel && (
          <div className="grid-2">
            <section className="card pad" aria-label="환율 차트">
              <h2 className="section-title">
                {sel.name} <small>{sel.symbol}{isKRW(sel) && sel.unit !== 1 ? ` · ${sel.unit}${sel.currency}당` : ""}</small>
                <span className="right">일별 · {dateKST(sel.since)} 이후 최고 {num(sel.high, digitsOf(sel.close))}
                  {" "}/ 최저 {num(sel.low, digitsOf(sel.close))}</span>
              </h2>
              {series && series.points.length > 1
                ? <PriceChart points={series.points} digits={digitsOf(sel.close)} />
                : <div className="empty">과거 시세를 모으는 중입니다</div>}
            </section>
            <section className="card pad" aria-label="환율 계산기">
              <h2 className="section-title">환율 계산기</h2>
              <FxConverter rates={krw.filter((it) => it.currency).map((it) => (
                { currency: it.currency!, name: it.name, unit: it.unit, close: it.close }))} />
            </section>
          </div>
        )}
      </div>
    </>
  );
}
