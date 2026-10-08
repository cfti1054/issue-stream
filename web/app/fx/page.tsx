// 환율·원자재: 원화 환율(하나은행 고시 매매기준율), 달러 지표(달러 인덱스·교차 환율),
// 원자재(금·은·원유·구리)와 국내 금 프리미엄, 선택 항목 차트·환율 계산기
import Link from "next/link";
import { ApiError, api, type BoardItem, type CommodityItem, type FxBoard, type FxItem, type PriceSeries } from "@/lib/api";
import { dateKST, dir, num, pct, signed, timeKST } from "@/lib/format";
import { Sparkline } from "@/components/charts";
import PriceChart from "@/components/PriceChart";
import ErrorBox from "@/components/ErrorBox";
import FxConverter from "@/components/FxConverter";

export const dynamic = "force-dynamic";

/** 원 단위 원자재(국내 금)는 정수, EUR/USD 처럼 1 근처 값은 소수 4자리, 나머지는 2자리 */
const digitsOf = (it: BoardItem) =>
  isCommodity(it) && it.unit_label.startsWith("원") ? 0 : it.close < 10 ? 4 : 2;
const isKRW = (it: BoardItem) => it.symbol.endsWith("/KRW");
const isCommodity = (it: BoardItem): it is CommodityItem => "unit_label" in it;
/** 카드·차트 제목 옆 단위: 원화 환율은 "100 JPY", 원자재는 "$/oz", 나머지는 심볼 */
const unitOf = (it: BoardItem) =>
  isCommodity(it) ? it.unit_label : isKRW(it) ? `${(it as FxItem).unit} ${(it as FxItem).currency}` : it.symbol;

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
  const all: BoardItem[] = [...d.items, ...d.commodities];
  const sel = all.find((it) => it.symbol === c) ?? all[0];
  let series: PriceSeries | null = null;
  if (sel) {
    try { series = await api.prices(sel.symbol, 130); } catch { series = null; }
  }

  // sparkW: 추이 그래프 폭 (원자재는 한 줄에 6장이라 좁게)
  const card = (it: BoardItem, sparkW = 84) => {
    const dg = digitsOf(it);
    return (
      <Link key={it.symbol} className="card index-card fx-card" href={`/fx?c=${encodeURIComponent(it.symbol)}`}
        scroll={false} aria-current={it.symbol === sel?.symbol ? "true" : undefined}>
        <span className="label">
          {it.name} <span className="muted">{unitOf(it)}</span>
          {it.stale && <span className="stale"> · {dateKST(it.day)} 기준</span>}
        </span>
        <span className="num-l tnum">{num(it.close, dg)}</span>
        <span className={`chg tnum ${dir(it.change_pct)}`}>
          {signed(it.change, dg)} <span className="num-s">{pct(it.change_pct)}</span>
        </span>
        <Sparkline values={it.spark} width={sparkW} height={40} label={`${it.name} 최근 ${it.spark.length}일 추이`} />
      </Link>
    );
  };

  return (
    <>
      <div className="page-head">
        <h1>환율·원자재</h1>
        {d.updated_at && <p className="num-s">업데이트 {timeKST(d.updated_at)}</p>}
      </div>

      <div className="stack">
        {all.length === 0 && (
          <div className="card pad muted">
            데이터 없음 — 수집기(issue-stream serve)가 채웁니다 (config/sources.yaml 의 fx_rates·commodities)
          </div>
        )}

        {krw.length > 0 && (
          <section aria-label="원화 환율">
            <h2 className="section-title">원화 환율 <small>하나은행 고시 매매기준율 · 원</small></h2>
            <div className="index-strip">{krw.map((it) => card(it))}</div>
          </section>
        )}
        {usd.length > 0 && (
          <section aria-label="달러 지표">
            <h2 className="section-title">달러 지표 <small>달러 인덱스 · 주요 교차 환율</small></h2>
            <div className="index-strip">{usd.map((it) => card(it))}</div>
          </section>
        )}
        {d.commodities.length > 0 && (
          <section aria-label="원자재">
            <h2 className="section-title">원자재 <small>국내 금은 KRX 금현물, 국제 시세는 뉴욕 선물(근월물)</small></h2>
            <div className="index-strip fx-tight">{d.commodities.map((it) => card(it, 60))}</div>
            {d.gold && (
              <p className="fx-gold">
                <b>국내 금 프리미엄</b>
                <span>국제 금 원화 환산 <b className="tnum">{num(d.gold.intl_krw_per_g, 0)}</b>원/g
                  {" "}(원/달러 {num(d.gold.usdkrw, 2)} 적용)</span>
                <span>국내 금 <b className="tnum">{num(d.gold.domestic, 0)}</b>원/g</span>
                <span className={`tnum ${dir(d.gold.premium_pct)}`} style={{ fontWeight: 700 }}>
                  국내가 {Math.abs(d.gold.premium_pct).toFixed(2)}% {d.gold.premium_pct >= 0 ? "비쌈" : "쌈"}
                </span>
              </p>
            )}
          </section>
        )}

        {sel && (
          <div className="grid-2">
            <section className="card pad" aria-label="시세 차트">
              <h2 className="section-title">
                {sel.name} <small>{unitOf(sel)}</small>
                <span className="right">일별 · {dateKST(sel.since)} 이후 최고 {num(sel.high, digitsOf(sel))}
                  {" "}/ 최저 {num(sel.low, digitsOf(sel))}</span>
              </h2>
              {series && series.points.length > 1
                ? <PriceChart points={series.points} digits={digitsOf(sel)} />
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
