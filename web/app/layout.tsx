import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AutoRefresh, Nav } from "@/components/chrome";

export const metadata: Metadata = {
  title: "issue-stream",
  description: "뉴스·공시·시세를 이슈 단위로 묶어 보는 개인용 시장 대시보드",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <header className="topbar">
          <div className="topbar-inner">
            <div className="brand"><span className="brand-dot" />issue-stream</div>
            <Nav />
          </div>
        </header>
        <main className="shell">{children}</main>
        <AutoRefresh />
      </body>
    </html>
  );
}
