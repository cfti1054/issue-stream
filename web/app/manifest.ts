// 홈 화면에 추가(Android·Chrome 설치) 정보. 아이콘은 scripts/make-icons.mjs 로 만든다.
import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "issue-stream",
    short_name: "이슈스트림",   // 홈 화면 아이콘 아래 이름 (길면 잘린다)
    description: "뉴스·공시·시세를 이슈 단위로 묶어 보는 개인용 시장 대시보드",
    lang: "ko",
    start_url: "/",
    display: "standalone",      // 주소창 없이 앱처럼 열기
    background_color: "#f9f9f7",
    theme_color: "#f9f9f7",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
