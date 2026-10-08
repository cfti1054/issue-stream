// FastAPI 응답 타입과 호출 함수. 화면은 여기서 받은 값을 그리기만 한다 (계산은 백엔드).
// 서버(서버 컴포넌트·서버 액션)에서만 쓴다. 로그인 토큰은 HttpOnly 쿠키에서 꺼내 Bearer 로 넘긴다.
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "./session";

export type Sentiment = "positive" | "neutral" | "negative";

export interface IndexItem {
  symbol: string;
  name: string;
  close: number;
  change: number | null;
  change_pct: number | null;
  day: string;
  stale: boolean;
  spark: number[];
}

export interface BriefBullet {
  issue_no: number;
  text: string;
  sentiment: Sentiment;
  importance: number;
}

export interface MarketBrief {
  headline: string;
  bullets: BriefBullet[];
  tone: Record<Sentiment, number>;
  issue_count: number;
  region: "kr" | "us";
  generated_by: string;
  generated_at: string;
}

export interface SentimentCounts {
  positive: number;
  neutral: number;
  negative: number;
  total: number;
}

export interface WatchItem {
  code: string;
  name: string;
  holding: boolean;
  market: string | null;
  region: "kr" | "us";
  close: number | null;
  change: number | null;
  change_pct: number | null;
  day: string | null;
  spark: number[];
  stale: boolean;
  sentiment: SentimentCounts;
  top_issue: { no: number; headline: string } | null;
}

export interface SectorItem {
  name: string;
  market: string;
  change_pct: number | null;
  close: number | null;
}

export interface IssueSummary {
  headline: string;
  bullets: string[];
  sentiment: Sentiment;
  affected_tickers: string[];
  confidence: number;
  conflicting_views: boolean;
  source_article_ids: string[];
  generated_by: string;
}

export interface IssueArticle {
  no: number;
  title: string;
  publisher: string | null;
  url: string;
  published_at: string;
  kind: "news" | "disclosure";
  sentiment: Sentiment | null;
  cited: boolean;
  also?: string[]; // 같은 내용을 받아쓴 다른 매체 (중복 기사는 한 줄로 묶음)
}

export interface IssueCard {
  no: number;
  region: "kr" | "us";
  importance: number;
  sentiment: Sentiment;
  article_count: number;
  publisher_count: number;
  has_disclosure: boolean;
  first_seen: string;
  last_seen: string;
  tickers: { code: string; name: string }[];
  summary: IssueSummary | null;
  sources: { publisher: string; at: string }[];
  coverage: number[];
  last_hour: number;
  article_sentiment: Partial<Record<Sentiment, number>>;
  articles?: IssueArticle[];
}

export interface IssuePage {
  items: IssueCard[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CollectionStatus {
  first_run: boolean;
  scheduler: boolean;
  problems: { job: string; label: string; message: string; at: string }[];
}

export interface User {
  no: number;
  username: string;
  name: string | null;
}

export interface AuthConfig {
  signup: boolean;
  invite_required: boolean;
  min_password: number;
  username_rule: string;
}

export interface Session {
  token: string;
  expires_at: string;
  user: User;
}

export interface TickerHit {
  code: string;
  name: string;
  market: string | null;
  watched: boolean;
}

export interface Dashboard {
  generated_at: string;
  user: User | null;
  demo: boolean;
  collection: CollectionStatus;
  market_open: boolean;
  us_market_open: boolean;
  indices: IndexItem[];
  brief: MarketBrief;
  brief_us: MarketBrief;
  watchlist: WatchItem[];
  sectors: SectorBlock;
  sectors_us: SectorBlock;
  issues: IssueCard[];
  issues_us: IssueCard[];
}

export interface PricePoint {
  day: string;
  close: number;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  change_pct: number | null;
}

export interface SectorBlock {
  day: string | null;
  basis: "etf" | "index" | "us_etf";
  items: SectorItem[];
}

export interface FxItem {
  symbol: string;        // "USD/KRW", "EUR/USD", "DXY"
  name: string;
  currency: string | null; // 원화 환율이면 외화 코드 (USD, JPY …)
  unit: number;          // 원화 환율: unit 외화당 원 (엔화 100)
  close: number;
  change: number | null;
  change_pct: number | null;
  day: string;
  stale: boolean;
  high: number;          // 최근 약 6개월 최고·최저
  low: number;
  since: string;
  spark: number[];
}

export interface FxBoard {
  updated_at: string | null;
  items: FxItem[];
}

export interface PriceSeries {
  symbol: string;
  name: string;
  market: string | null;
  is_stock: boolean;
  points: PricePoint[];
}

const API_BASE = (process.env.API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly status = 0) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = {};
  token ??= (await cookies()).get(SESSION_COOKIE)?.value;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method, headers, cache: "no-store", body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(`API 서버(${API_BASE})에 연결할 수 없습니다.`);
  }
  if (!res.ok) {
    const detail = await res.json().then((j) => j?.detail).catch(() => null);
    throw new ApiError(typeof detail === "string" ? detail : `API 오류 ${res.status}: ${path}`, res.status);
  }
  return (res.status === 204 ? null : res.json()) as Promise<T>;
}

const get = <T,>(path: string) => call<T>("GET", path);

export const api = {
  dashboard: (sort?: "importance" | "recent") => get<Dashboard>(`/dashboard${sort === "recent" ? "?sort=recent" : ""}`),
  prices: (symbol: string, days = 120) =>
    get<PriceSeries>(`/market/prices/${encodeURIComponent(symbol)}?days=${days}`),
  fx: () => get<FxBoard>("/market/fx"),
  issues: (q: {
    hours?: number; ticker?: string; sentiment?: string; region?: string; sort?: string;
    q?: string; qt?: string; page?: number; page_size?: number;
  }) => {
    const p = new URLSearchParams();
    if (q.sort && q.sort !== "importance") p.set("sort", q.sort);
    if (q.q) { p.set("q", q.q); if (q.qt && q.qt !== "all") p.set("qt", q.qt); }
    if (q.page && q.page > 1) p.set("page", String(q.page));
    if (q.page_size) p.set("page_size", String(q.page_size));
    if (q.region && q.region !== "all") p.set("region", q.region);
    if (q.hours) p.set("hours", String(q.hours));
    if (q.ticker) p.set("ticker", q.ticker);
    if (q.sentiment) p.set("sentiment", q.sentiment);
    return get<IssuePage>(`/issues?${p}`);
  },
  tickers: () => get<{ code: string; name: string }[]>("/tickers"),
  searchTickers: (q: string) => get<TickerHit[]>(`/tickers/search?q=${encodeURIComponent(q)}`),

  // 로그인 (로그인 전이라 쿠키 토큰 대신 빈 토큰을 넘긴다)
  login: (username: string, password: string) =>
    call<Session>("POST", "/auth/login", { username, password }, ""),
  signup: (b: { username: string; password: string; name?: string; invite_code?: string }) =>
    call<Session>("POST", "/auth/signup", b, ""),
  authConfig: () => call<AuthConfig>("GET", "/auth/config", undefined, ""),
  logout: () => call<null>("POST", "/auth/logout"),
  me: () => get<User>("/auth/me"),

  // 관심종목 (로그인 필요)
  watch: (code: string, holding?: boolean) =>
    call<{ code: string; name: string; holding: boolean }>(
      "PUT", `/me/watchlist/${encodeURIComponent(code)}`, holding === undefined ? undefined : { holding }),
  unwatch: (code: string) => call<null>("DELETE", `/me/watchlist/${encodeURIComponent(code)}`),
  apiBase: API_BASE,
};
