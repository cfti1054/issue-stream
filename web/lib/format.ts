// 표시 형식만 담당 (값 계산은 하지 않음)
import type { Sentiment } from "./api";

const KST = "Asia/Seoul";

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** 지수는 소수 2자리, 주가는 정수 */
export function price(v: number | null | undefined, isIndex = false): string {
  return num(v, isIndex ? 2 : 0);
}

const US_MARKETS = new Set(["NASDAQ", "NYSE", "AMEX", "US"]);

export function isUS(market: string | null | undefined): boolean {
  return !!market && US_MARKETS.has(market);
}

/** 주가: 국내는 원 단위 정수, 미국은 달러 소수 2자리 */
export function stockPrice(v: number | null | undefined, market?: string | null): string {
  if (v === null || v === undefined) return "–";
  return isUS(market) ? `$${num(v, 2)}` : num(v, 0);
}

export function stockChange(v: number | null | undefined, market?: string | null): string {
  return signed(v, isUS(market) ? 2 : 0);
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${Math.abs(v).toFixed(2)}%`;
}

export function signed(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "";
  const sign = v > 0 ? "▲" : v < 0 ? "▼" : "";
  return `${sign}${num(Math.abs(v), digits)}`;
}

/** 등락 방향 → CSS 클래스 (한국 관례: 상승 빨강, 하락 파랑) */
export function dir(v: number | null | undefined): "up" | "down" | "flat" {
  if (!v) return "flat";
  return v > 0 ? "up" : "down";
}

export function timeKST(iso: string): string {
  return new Date(iso).toLocaleTimeString("ko-KR", { timeZone: KST, hour: "2-digit", minute: "2-digit", hour12: false });
}

export function dateKST(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", { timeZone: KST, month: "numeric", day: "numeric" });
}

export function ago(iso: string, now = Date.now()): string {
  const m = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}시간 전`;
  return `${Math.floor(h / 24)}일 전`;
}

export const SENTI_LABEL: Record<Sentiment, string> = { positive: "긍정", neutral: "중립", negative: "부정" };


/** 종목 링크: 코인(COIN:BTC)은 코인 탭, 나머지는 마켓 대시보드 차트 */
export function tickerHref(code: string): string {
  return code.startsWith("COIN:") ? `/coins?c=${encodeURIComponent(code.slice(5))}` : `/?ticker=${encodeURIComponent(code)}`;
}

export const INDEX_SYMBOLS = new Set(["KS11", "KQ11", "US500", "IXIC", "USD/KRW", "DJI", "N225"]);
