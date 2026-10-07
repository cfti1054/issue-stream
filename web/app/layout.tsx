import type { Metadata, Viewport } from "next";
import "./globals.css";
import Link from "next/link";
import { AutoRefresh, Nav } from "@/components/chrome";
import { LogoutButton } from "@/components/watch";
import { getUser } from "@/lib/user";

export const metadata: Metadata = {
  title: "issue-stream",
  description: "뉴스·공시·시세를 이슈 단위로 묶어 보는 개인용 시장 대시보드",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getUser();
  return (
    <html lang="ko">
      <body>
        <header className="topbar">
          <div className="topbar-inner">
            <div className="brand"><span className="brand-dot" />issue-stream</div>
            <Nav />
            <div className="topbar-meta">
              {user ? (
                <>
                  <span title={user.username}>{user.name || user.username}</span>
                  <LogoutButton />
                </>
              ) : <Link className="btn btn-s" href="/login">로그인</Link>}
            </div>
          </div>
        </header>
        <main className="shell">{children}</main>
        <AutoRefresh />
      </body>
    </html>
  );
}
