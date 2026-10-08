// 이슈 검색 (종목명·코드 / 기사 제목·요약문). 일반 GET 폼이라 JS 없이 /issues?q=…&qt=… 로 이동한다.
export default function IssueSearch({ q, qt, keep, compact = false }: {
  q?: string; qt?: string; keep?: Record<string, string | undefined>; compact?: boolean;
}) {
  return (
    <form action="/issues" method="get" role="search" className={`issue-search ${compact ? "compact" : ""}`}>
      {Object.entries(keep ?? {}).map(([k, v]) => v ? <input key={k} type="hidden" name={k} value={v} /> : null)}
      <select className="select" name="qt" defaultValue={qt ?? "all"} aria-label="검색 대상">
        <option value="all">전체</option>
        <option value="ticker">종목</option>
        <option value="text">기사 내용</option>
      </select>
      <input className="input" type="search" name="q" defaultValue={q ?? ""} aria-label="검색어"
        placeholder={compact ? "종목·기사 검색" : "종목명·종목코드 또는 기사 제목·내용"} />
      <button className="btn btn-s" type="submit">검색</button>
    </form>
  );
}
