// 이슈 브리핑: 뉴스·공시를 이슈 단위로 묶어 요약. 카드 1장 = 이슈 1개.
import Link from "next/link";
import { ApiError, api, type IssueCard as Issue, type IssuePage } from "@/lib/api";
import IssueCard from "@/components/IssueCard";
import IssueSearch from "@/components/IssueSearch";
import Pagination from "@/components/Pagination";
import ErrorBox from "@/components/ErrorBox";
import { TickerSelect } from "@/components/chrome";
import { tickerHref } from "@/lib/format";

export const dynamic = "force-dynamic";

type Q = {
  no?: string;   // 이슈 번호: 그 이슈 1건만 보기 (대시보드·시그널에서 이슈를 눌렀을 때)
  hours?: string; ticker?: string; sentiment?: string; region?: string;
  sort?: string; q?: string; qt?: string; page?: string;
};

const PAGE_SIZE = 20;
const REGIONS = [["kr", "국내"], ["us", "미국"], ["co", "코인"], ["all", "전체"]] as const;
const HOURS = [["6", "6시간"], ["24", "24시간"], ["48", "48시간"], ["168", "7일"]] as const;
const SENTIS = [["", "전체"], ["positive", "긍정"], ["neutral", "중립"], ["negative", "부정"]] as const;
const SORTS = [["importance", "중요도순"], ["recent", "최신순"]] as const;

/** 필터를 바꾸면 1페이지로 (page 를 지움), 페이지 이동만 page 를 바꾼다 */
function href(q: Q, patch: Partial<Q>): string {
  const p = new URLSearchParams();
  const m: Q = { ...q, page: undefined, ...patch };
  (Object.keys(m) as (keyof Q)[]).forEach((k) => { if (m[k]) p.set(k, m[k]!); });
  const s = p.toString();
  return s ? `/issues?${s}` : "/issues";
}

export default async function IssuesPage({ searchParams }: { searchParams: Promise<Q> }) {
  const q = await searchParams;
  if (q.no && Number(q.no) > 0) return <SingleIssue no={Number(q.no)} />;
  const hours = Number(q.hours ?? 24);
  const sort = q.sort === "recent" ? "recent" : "importance";
  const page = Math.max(1, Number(q.page ?? 1) || 1);
  const query = q.q?.trim() || undefined;
  // 지역: 기본 국내. 종목 필터·검색으로 들어오면 어느 지역이든 보이도록 전체
  const region = REGIONS.some(([v]) => v === q.region) ? q.region!
    : q.ticker || query ? "all" : "kr";
  let res: IssuePage;
  let tickers: { code: string; name: string }[];
  try {
    [res, tickers] = await Promise.all([
      api.issues({ hours, ticker: q.ticker, sentiment: q.sentiment, region, sort, q: query, qt: q.qt,
                   page, page_size: PAGE_SIZE }),
      api.tickers(),
    ]);
  } catch (e) {
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }
  const issues = res.items;
  const now = Date.now();
  const tickerName = tickers.find((t) => t.code === q.ticker)?.name;
  const base: Record<string, string> = {};
  for (const k of ["hours", "sentiment", "region", "sort", "q", "qt"] as const) if (q[k]) base[k] = q[k]!;
  const qtLabel = q.qt === "ticker" ? "종목" : q.qt === "text" ? "기사 내용" : "종목·기사";

  return (
    <>
      <div className="page-head">
        <h1>이슈 브리핑</h1>
        <p>같은 사건을 다룬 기사·공시를 하나로 묶어 요약합니다{region === "us" ? " · 미국 시장 (한국어 보도 + 영어 원문)"
          : region === "co" ? " · 코인 시장 (한국어 보도 + 영어 원문)" : ""}</p>
      </div>

      <div className="filters">
        <div className="chips" role="group" aria-label="지역">
          {REGIONS.map(([v, label]) => (
            <Link key={v} href={href(q, { region: v })} aria-current={region === v ? "true" : undefined}>{label}</Link>
          ))}
        </div>
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
        <div className="chips" role="group" aria-label="정렬">
          {SORTS.map(([v, label]) => (
            <Link key={v} href={href(q, { sort: v === "importance" ? undefined : v })}
              aria-current={sort === v ? "true" : undefined}>{label}</Link>
          ))}
        </div>
        <TickerSelect tickers={tickers} value={q.ticker} baseQuery={base} />
        {q.ticker && <Link className="ticker" href={tickerHref(q.ticker)}>{tickerName} 시세 보기 →</Link>}
      </div>

      <div className="filters">
        <IssueSearch q={query} qt={q.qt}
          keep={{ hours: q.hours, sentiment: q.sentiment, region: q.region, sort: q.sort, ticker: q.ticker }} />
        {query && (
          <span className="search-state">
            {qtLabel} 검색 “{query}” <Link href={href(q, { q: undefined, qt: undefined })}>검색 해제 ×</Link>
          </span>
        )}
        <span className="count">
          이슈 {res.total}건 · {sort === "recent" ? "최신순" : "중요도순"}
          {res.pages > 1 && ` · ${res.page}/${res.pages} 페이지`}
        </span>
      </div>

      {issues.length === 0 ? (
        <div className="card empty">
          {query ? `“${query}” 에 맞는 이슈가 없습니다. 기간을 7일로 늘리거나 검색 대상을 바꿔 보세요.`
            : "조건에 맞는 이슈가 없습니다. 기간을 늘리거나 필터를 해제해 보세요."}
        </div>
      ) : (
        <div className="issue-grid">
          {issues.map((it) => <IssueCard key={it.no} issue={it} now={now} />)}
        </div>
      )}

      <Pagination page={res.page} pages={res.pages} href={(n) => href(q, { page: n === 1 ? undefined : String(n) })} />
    </>
  );
}

/** 이슈 1건만: 요약과 근거 기사(펼친 상태)만 보여 주고 다른 이슈는 숨긴다 */
async function SingleIssue({ no }: { no: number }) {
  let issue: Issue;
  try {
    issue = await api.issue(no);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return (
        <>
          <div className="page-head"><h1>이슈 브리핑</h1></div>
          <div className="card empty">이슈 #{no} 를 찾을 수 없습니다. 오래되어 정리됐을 수 있습니다.{" "}
            <Link href="/issues">이슈 브리핑 전체 보기 →</Link></div>
        </>
      );
    }
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }
  return (
    <>
      <div className="page-head">
        <h1>이슈 브리핑</h1>
        <p>이슈 #{no} 와 관련 기사만 보는 중</p>
      </div>
      <div className="filters">
        <Link className="btn btn-s" href={issue.region === "kr" ? "/issues" : `/issues?region=${issue.region}`}>← 이슈 브리핑 전체 보기</Link>
      </div>
      <div className="issue-single">
        <IssueCard issue={issue} now={Date.now()} open scrollAt={10} />
      </div>
    </>
  );
}
