// 페이지 이동: << < 1 2 3 … 9 > >>  (현재 페이지 기준 최대 9개 번호)
import Link from "next/link";

const WINDOW = 9;

export default function Pagination({ page, pages, href }: {
  page: number; pages: number; href: (page: number) => string;
}) {
  if (pages <= 1) return null;
  const start = Math.max(1, Math.min(page - Math.floor(WINDOW / 2), pages - WINDOW + 1));
  const nums = Array.from({ length: Math.min(WINDOW, pages) }, (_, i) => start + i);
  const step = (label: string, target: number, disabled: boolean, aria: string) => disabled
    ? <span className="pg-btn" aria-disabled="true" aria-label={aria}>{label}</span>
    : <Link className="pg-btn" href={href(target)} aria-label={aria}>{label}</Link>;
  return (
    <nav className="pagination" aria-label="페이지">
      {step("«", 1, page === 1, "첫 페이지")}
      {step("‹", page - 1, page === 1, "이전 페이지")}
      {nums.map((n) => n === page
        ? <span key={n} className="pg-btn" aria-current="page">{n}</span>
        : <Link key={n} className="pg-btn" href={href(n)}>{n}</Link>)}
      {step("›", page + 1, page === pages, "다음 페이지")}
      {step("»", pages, page === pages, "마지막 페이지")}
    </nav>
  );
}
