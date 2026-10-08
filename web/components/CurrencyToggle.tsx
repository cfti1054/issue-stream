// 차트 표시 통화 토글 (달러 ↔ 원화). 주소의 krw=1 로 바뀌어 서버가 원화로 환산한 시세를 다시 그린다.
import Link from "next/link";

export default function CurrencyToggle({ krw, offHref, onHref, offLabel = "달러", onLabel = "원화" }: {
  krw: boolean; offHref: string; onHref: string; offLabel?: string; onLabel?: string;
}) {
  return (
    <span className="chips chips-s" role="group" aria-label="표시 통화">
      <Link href={offHref} scroll={false} aria-current={!krw}>{offLabel}</Link>
      <Link href={onHref} scroll={false} aria-current={krw} title="그날 원/달러 환율을 곱한 원화 가격">{onLabel}</Link>
    </span>
  );
}
