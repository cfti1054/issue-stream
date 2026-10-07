// 이슈 카드 1장 = 이슈 1개. 요약 → 출처(매체·시각) → 근거 불릿 → 종목 태그 → 확산 → 근거 기사(접힘)
import Link from "next/link";
import type { IssueCard as Issue } from "@/lib/api";
import { SENTI_LABEL, ago, timeKST } from "@/lib/format";
import { CoverageBars } from "./charts";

export default function IssueCard({ issue, now }: { issue: Issue; now: number }) {
  const s = issue.summary;
  const hot = issue.importance >= 60;
  const cited = issue.articles?.filter((a) => a.cited).length ?? 0;
  return (
    <article className="card issue" id={`issue-${issue.no}`}>
      <div className="issue-top">
        <span className={`imp tnum ${hot ? "hot" : ""}`} title="중요도 (기사 수·매체 다양성·확산 속도·보유종목·공시 가중합)">
          중요도 {Math.round(issue.importance)}
        </span>
        <span className={`senti senti-${issue.sentiment}`}>{SENTI_LABEL[issue.sentiment]}</span>
        {issue.has_disclosure && <span className="tag-disc">공시 확인</span>}
        <span className="muted num-s" style={{ marginLeft: "auto" }}>
          {ago(issue.first_seen, now)} 최초 보도 · 최근 {ago(issue.last_seen, now)}
        </span>
      </div>

      <h3>{s?.headline ?? "요약 생성 대기 중"}</h3>

      {/* 출처를 요약 바로 아래에: 신뢰도 확보 */}
      <div className="sources">
        {issue.sources.slice(0, 4).map((src) => (
          <span key={src.publisher}><b>{src.publisher}</b> {timeKST(src.at)}</span>
        ))}
        {issue.sources.length > 4 && <span>외 {issue.sources.length - 4}곳</span>}
      </div>

      {s && s.bullets.length > 0 && (
        <ul className="bullets">{s.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>
      )}
      {s?.conflicting_views && <div className="warn">기사 간 전망이 엇갈립니다. 근거 기사를 함께 확인하세요.</div>}

      {issue.tickers.length > 0 && (
        <div className="tickers" aria-label="관련 종목">
          {issue.tickers.map((t) => (
            <Link key={t.code} className="ticker" href={`/?ticker=${t.code}`} title="마켓 대시보드에서 시세 보기">
              {t.name} <span className="muted">{t.code}</span>
            </Link>
          ))}
        </div>
      )}

      <div className="spread">
        <div>
          <div className="lbl"><span>보도량 추이</span><span>최근 24시간 · 1시간 단위</span></div>
          <CoverageBars counts={issue.coverage} />
        </div>
        <div className="stats">
          <div><b className="tnum">{issue.article_count}</b><span>기사</span></div>
          <div><b className="tnum">{issue.publisher_count}</b><span>매체</span></div>
          <div><b className={`tnum ${issue.last_hour ? "up" : ""}`}>+{issue.last_hour}</b><span>최근 1시간</span></div>
        </div>
      </div>

      {issue.articles && issue.articles.length > 0 && (
        <details className="evidence">
          <summary>근거 기사 {issue.articles.length}건{cited ? ` (요약에 사용 ${cited}건)` : ""}</summary>
          <ul className="ev-list">
            {issue.articles.map((a) => (
              <li key={a.no}>
                <span className="t tnum">{timeKST(a.published_at)}</span>
                <div>
                  <a className="ttl" href={a.url} target="_blank" rel="noreferrer">{a.title}</a>
                  <div className="m">
                    <span>{a.publisher}</span>
                    {a.kind === "disclosure" && <span>공시</span>}
                    {a.sentiment && <span className={`senti senti-${a.sentiment}`}>{SENTI_LABEL[a.sentiment]}</span>}
                    {a.cited && <span className="cited">요약 근거</span>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}

      {s && (
        <div className="muted num-s">
          요약: {s.generated_by === "extractive" ? "추출 요약 (무료)" : s.generated_by} · 신뢰도 {Math.round(s.confidence * 100)}%
        </div>
      )}
    </article>
  );
}
