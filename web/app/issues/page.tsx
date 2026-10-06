// 이슈 브리핑: 뉴스·공시를 이슈 단위로 묶어 요약. 카드 1장 = 이슈 1개.
import Link from "next/link";
import { ApiError, api, type IssueCard as Issue } from "@/lib/api";
import IssueCard from "@/components/IssueCard";
import ErrorBox from "@/components/ErrorBox";
import { TickerSelect } from "@/components/chrome";

export const dynamic = "force-dynamic";

type Q = { hours?: string; ticker?: string; sentiment?: string };

const HOURS = [["6", "6시간"], ["24", "24시간"], ["48", "48시간"]] as const;
const SENTIS = [["", "전체"], ["positive", "긍정"], ["neutral", "중립"], ["negative", "부정"]] as const;

function href(q: Q, patch: Partial<Q>): string {
  const p = new URLSearchParams();
  const m = { ...q, ...patch };
  (Object.keys(m) as (keyof Q)[]).forEach((k) => { if (m[k]) p.set(k, m[k]!); });
  const s = p.toString();
  return s ? `/issues?${s}` : "/issues";
}

export default async function IssuesPage({ searchParams }: { searchParams: Promise<Q> }) {
  const q = await searchParams;
  const hours = Number(q.hours ?? 24);
  let issues: Issue[];
  let tickers: { code: string; name: string }[];
  try {
    [issues, tickers] = await Promise.all([
      api.issues({ hours, ticker: q.ticker, sentiment: q.sentiment, limit: 40 }),
      api.tickers(),
    ]);
  } catch (e) {
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }
  const now = Date.now();
  const tickerName = tickers.find((t) => t.code === q.ticker)?.name;
  const base: Record<string, string> = {};
  if (q.hours) base.hours = q.hours;
  if (q.sentiment) base.sentiment = q.sentiment;

  return (
    <>
      <div className="page-head">
        <h1>이슈 브리핑</h1>
        <p>같은 사건을 다룬 기사·공시를 하나로 묶어 요약합니다</p>
      </div>

      <div className="filters">
        <div className="chips" role="group" aria-label="기간">
          {HOURS.map(([v, label]) => (
            <Link key={v} href={href(q, { hours: v === "24" ? undefined : v })}
              aria-current={String(hours) === v ? "true" : undefined}>{label}</Link>
          ))}
        </div>
        <div className="chips" role="group" aria-label="감성">
          {SENTIS.map(([v, label]) => (
            <Link key={v} href={href(q, { sentiment: v || undefined })}
              aria-current={(q.sentiment ?? "") === v ? "true" : undefined}>{label}</Link>
          ))}
        </div>
        <TickerSelect tickers={tickers} value={q.ticker} baseQuery={base} />
        {q.ticker && <Link className="ticker" href={`/?ticker=${q.ticker}`}>{tickerName} 시세 보기 →</Link>}
        <span className="count">이슈 {issues.length}건 · 중요도순</span>
      </div>

      {issues.length === 0 ? (
        <div className="card empty">조건에 맞는 이슈가 없습니다. 기간을 늘리거나 필터를 해제해 보세요.</div>
      ) : (
        <div className="issue-grid">
          {issues.map((it) => <IssueCard key={it.id} issue={it} now={now} />)}
        </div>
      )}
    </>
  );
}
