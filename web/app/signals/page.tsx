// 시그널 맵: 이슈 1건 = 1줄. 주제·키워드·출처 → 대표 종목(이유·등락률) → 함께 언급된 종목
import Link from "next/link";
import { ApiError, api, type SignalBoard, type SignalQuote, type SignalRow } from "@/lib/api";
import { ago, dir, isUS, pct, timeKST } from "@/lib/format";
import ErrorBox from "@/components/ErrorBox";
import { getUser } from "@/lib/user";

export const dynamic = "force-dynamic";

const HOURS = [1, 6, 24] as const;
// 로고 대신 쓰는 이름 첫 글자 아이콘 색 (흰 글자가 읽히는 중간 채도, 두 테마 공통)
const AVATAR = ["#1f5fae", "#c62f2e", "#2b7a4b", "#7b3fa0", "#b35c00", "#0a6e8a", "#8a1f5c", "#4b6b2a", "#5a4fcf"];

function color(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR[h % AVATAR.length];
}

function initials(name: string, n = 1): string {
  const t = name.replace(/^(KODEX|TIGER|ACE|SOL|KBSTAR|RISE)\s*/i, "").trim() || name;
  return /^[A-Za-z]/.test(t) ? t.slice(0, 2).toUpperCase() : t.slice(0, n);
}

function changeText(p: number | null): string {
  if (p === null) return "시세 없음";
  if (p === 0) return "보합";
  return `${Math.abs(p).toFixed(2)}% ${p > 0 ? "상승" : "하락"}`;
}

export default async function SignalsPage({ searchParams }: { searchParams: Promise<{ r?: string; h?: string }> }) {
  const q = await searchParams;
  const region = q.r === "us" ? "us" : "kr";
  const hours = HOURS.find((h) => String(h) === q.h) ?? 6;
  const href = (r: string, h: number) => {
    const p = new URLSearchParams();
    if (r === "us") p.set("r", "us");
    if (h !== 6) p.set("h", String(h));
    return p.size ? `/signals?${p}` : "/signals";
  };
  let d: SignalBoard;
  const user = await getUser();
  try {
    d = await api.signals(region, hours);
  } catch (e) {
    return <ErrorBox message={e instanceof ApiError ? e.message : String(e)} apiBase={api.apiBase} />;
  }
  const now = Date.now();
  const issueHref = (no: number) => `/issues?no=${no}`;

  const row = (s: SignalRow) => (
    <div className="sg-row" key={s.issue_no}>
      <div className="sg-topic">
        <h3><Link href={issueHref(s.issue_no)}>{s.category}</Link></h3>
        {s.keywords.length > 0 && (
          <div className="sg-kw">{s.keywords.map((k) => <span key={k}>{k}</span>)}</div>
        )}
        <div className="sg-src" title={s.publishers.join(", ")}>
          <span className="sg-pubs" aria-hidden>
            {s.publishers.map((p) => <b key={p} style={{ background: color(p) }}>{initials(p)}</b>)}
          </span>
          {s.publisher_count}개의 출처
        </div>
      </div>
      <div className="sg-link" aria-hidden />
      <Link className="sg-card" href={`/?ticker=${encodeURIComponent(s.main.code)}`} scroll={false}
        title={s.headline}>
        <span className="sg-logo" style={{ background: s.main.is_index ? "var(--ink-2)" : color(s.main.name) }}>
          {s.main.is_index ? (region === "us" ? "US" : "KR") : initials(s.main.name, 2)}
          {isUS(s.main.market) && <span className="sg-flag">US</span>}
        </span>
        <span className="sg-name">{s.main.name}</span>
        <span className="sg-ago">{ago(s.last_seen, now)}</span>
        <span className="sg-why">{s.reason}</span>
        <span className={`sg-chg tnum ${dir(s.main.change_pct)}`}>{changeText(s.main.change_pct)} ›</span>
      </Link>
      <div className={`sg-arrow ${s.related.length ? "" : "none"}`} aria-hidden />
      <div className="sg-rel">
        {s.related.map((r: SignalQuote) => (
          <Link key={r.code} href={`/?ticker=${encodeURIComponent(r.code)}`} scroll={false}>
            <span className="sg-mini" style={{ background: color(r.name) }} aria-hidden>{initials(r.name)}</span>
            <span className="sg-rn">{r.name}</span>
            <span className={`tnum ${dir(r.change_pct)}`}>{r.change_pct === null ? "–" : pct(r.change_pct)}</span>
          </Link>
        ))}
        {s.related_more > 0 && (
          <Link className="sg-more" href={issueHref(s.issue_no)}>{s.related_more}개 더보기</Link>
        )}
      </div>
    </div>
  );

  return (
    <>
      <div className="page-head">
        <h1>시그널</h1>
        <p className="num-s">업데이트 {timeKST(d.generated_at)}</p>
      </div>
      <p className="sg-lede">최근 이슈를 주제별로 모아, 가장 크게 영향받은 종목과 그 이유, 지금 등락률, 함께 언급된 종목을 한 줄로 보여 줍니다.</p>
      <div className="sg-tools">
        <span className="chips chips-s" role="group" aria-label="지역">
          <Link href={href("kr", hours)} aria-current={region === "kr"}>국내</Link>
          <Link href={href("us", hours)} aria-current={region === "us"}>미국</Link>
        </span>
        <span className="chips chips-s" role="group" aria-label="기간">
          {HOURS.map((h) => (
            <Link key={h} href={href(region, h)} aria-current={hours === h}>{h}시간</Link>
          ))}
        </span>
      </div>

      <section className="sg-map" aria-label="시그널">
        {d.items.length === 0 && d.mine.length === 0 && (
          <div className="card pad muted">최근 {hours}시간 {region === "us" ? "미국 시장 " : ""}이슈가 없습니다. 기간을 늘려 보세요.</div>
        )}
        {d.items.map(row)}

        <div className="sg-divider">
          <h2>내 관심 시그널 <small>☆ 관심종목이 나온 이슈</small></h2>
        </div>
        {d.mine.length > 0 ? d.mine.map(row) : (
          <p className="sg-empty muted">
            {user ? `최근 ${hours}시간 관심종목이 나온 이슈가 없습니다.`
              : <><Link href="/login?next=/signals">로그인</Link>하면 관심종목이 나온 이슈를 따로 모아 봅니다.</>}
          </p>
        )}
      </section>
    </>
  );
}
