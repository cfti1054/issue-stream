// FastAPI 응답 타입과 호출 함수. 화면은 여기서 받은 값을 그리기만 한다 (계산은 백엔드).

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
  issue_id: number;
  text: string;
  sentiment: Sentiment;
  importance: number;
}

export interface MarketBrief {
  headline: string;
  bullets: BriefBullet[];
  tone: Record<Sentiment, number>;
  issue_count: number;
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
  close: number | null;
  change: number | null;
  change_pct: number | null;
  day: string | null;
  spark: number[];
  stale: boolean;
  sentiment: SentimentCounts;
  top_issue: { id: number; headline: string } | null;
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
  id: number;
  title: string;
  publisher: string | null;
  url: string;
  published_at: string;
  kind: "news" | "disclosure";
  sentiment: Sentiment | null;
  cited: boolean;
}

export interface IssueCard {
  id: number;
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

export interface CollectionStatus {
  first_run: boolean;
  scheduler: boolean;
  problems: { job: string; label: string; message: string; at: string }[];
}

export interface Dashboard {
  generated_at: string;
  demo: boolean;
  collection: CollectionStatus;
  market_open: boolean;
  indices: IndexItem[];
  brief: MarketBrief;
  watchlist: WatchItem[];
  sectors: { day: string | null; basis: "etf" | "index"; items: SectorItem[] };
  issues: IssueCard[];
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

export interface PriceSeries {
  symbol: string;
  name: string;
  points: PricePoint[];
}

const API_BASE = (process.env.API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(`API 서버(${API_BASE})에 연결할 수 없습니다.`);
  }
  if (!res.ok) throw new ApiError(`API 오류 ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  dashboard: () => get<Dashboard>("/dashboard"),
  prices: (symbol: string, days = 120) =>
    get<PriceSeries>(`/market/prices/${encodeURIComponent(symbol)}?days=${days}`),
  issues: (q: { hours?: number; ticker?: string; sentiment?: string; limit?: number }) => {
    const p = new URLSearchParams();
    if (q.hours) p.set("hours", String(q.hours));
    if (q.ticker) p.set("ticker", q.ticker);
    if (q.sentiment) p.set("sentiment", q.sentiment);
    p.set("limit", String(q.limit ?? 30));
    return get<IssueCard[]>(`/issues?${p}`);
  },
  tickers: () => get<{ code: string; name: string }[]>("/tickers"),
  apiBase: API_BASE,
};
