// 차트 표시 통화 토글 (달러 ↔ 원화). 주소 파라미터(krw=1, 코인은 usd=1)가 바뀌어 서버가 환산한 시세를 다시 그린다.
import Link from "next/link";

/** krw: 두 번째(on) 쪽이 선택됐는지 */
export default function CurrencyToggle({
  krw, offHref, onHref, offLabel = "달러", onLabel = "원화", onTitle = "그날 원/달러 환율을 곱한 원화 가격",
}: {
  krw: boolean; offHref: string; onHref: string; offLabel?: string; onLabel?: string; onTitle?: string;
}) {
  return (
    <span className="chips chips-s" role="group" aria-label="표시 통화">
      <Link href={offHref} scroll={false} aria-current={!krw}>{offLabel}</Link>
      <Link href={onHref} scroll={false} aria-current={krw} title={onTitle}>{onLabel}</Link>
    </span>
  );
}
