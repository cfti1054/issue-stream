"use client";
// 상단 내비게이션·자동 새로고침 (브라우저에서 동작하는 부분만)
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

export function Nav() {
  const path = usePathname();
  const items = [
    { href: "/", label: "마켓 대시보드" },
    { href: "/issues", label: "이슈 브리핑" },
  ];
  return (
    <nav className="nav" aria-label="화면">
      {items.map((it) => {
        const active = it.href === "/" ? path === "/" : path.startsWith(it.href);
        return (
          <Link key={it.href} href={it.href} aria-current={active ? "page" : undefined}>{it.label}</Link>
        );
      })}
    </nav>
  );
}

/** 서버 데이터를 주기적으로 다시 받아온다 (스크롤·펼침 상태는 유지). */
export function AutoRefresh() {
  const router = useRouter();
  useEffect(() => {
    const sec = Number(process.env.NEXT_PUBLIC_REFRESH_SECONDS ?? 60);
    if (!sec) return;
    const t = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, sec * 1000);
    return () => clearInterval(t);
  }, [router]);
  return null;
}

/** 이슈 브리핑 종목 필터 (선택 즉시 이동) */
export function TickerSelect({ tickers, value, baseQuery }: {
  tickers: { code: string; name: string }[]; value?: string; baseQuery: Record<string, string>;
}) {
  const router = useRouter();
  return (
    <select className="select" aria-label="종목" value={value ?? ""}
      onChange={(e) => {
        const q = new URLSearchParams(baseQuery);
        if (e.target.value) q.set("ticker", e.target.value); else q.delete("ticker");
        router.push(`/issues?${q}`);
      }}>
      <option value="">전체 종목</option>
      {tickers.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
    </select>
  );
}
