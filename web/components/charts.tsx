// 서버에서 그려지는 작은 차트들 (JS 불필요). 호버 시 브라우저 기본 툴팁(<title>)으로 값을 보여준다.
import type { SectorItem, SentimentCounts } from "@/lib/api";
import { pct } from "@/lib/format";

/** 스파크라인: 추이만 보여주는 2px 선. 마지막 점 강조. 색은 기간 등락 방향. */
export function Sparkline({ values, width = 96, height = 32, label }: {
  values: number[]; width?: number; height?: number; label?: string;
}) {
  if (values.length < 2) return <svg width={width} height={height} aria-hidden />;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - pad * 2);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const rising = values[values.length - 1] >= values[0];
  const color = rising ? "var(--up-mark)" : "var(--down-mark)";
  const lx = x(values.length - 1), ly = y(values[values.length - 1]);
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={label ?? `최근 ${values.length}일 추이`}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r={2.5} fill={color} stroke="var(--surface)" strokeWidth={1.5} />
    </svg>
  );
}

/** 감성 비율 막대 (긍정·중립·부정 고정 순서, 2px 간격) + 개수 범례. 색만으로 전달하지 않도록 숫자 병기. */
export function SentimentBar({ c, compact = false }: { c: SentimentCounts; compact?: boolean }) {
  if (!c.total) {
    return (
      <div>
        <div className="sbar-empty" aria-label="최근 24시간 기사 없음" />
        {!compact && <div className="sbar-legend">기사 없음</div>}
      </div>
    );
  }
  const parts: [keyof SentimentCounts, string, string][] = [
    ["positive", "p", "긍정"], ["neutral", "n", "중립"], ["negative", "g", "부정"],
  ];
  const summary = `긍정 ${c.positive} · 중립 ${c.neutral} · 부정 ${c.negative}`;
  return (
    <div title={summary}>
      <div className="sbar" role="img" aria-label={`뉴스 심리 ${summary}`}>
        {parts.map(([k, cls]) => c[k] > 0 && (
          <span key={k} className={cls} style={{ flexGrow: c[k] }} />
        ))}
      </div>
      <div className="sbar-legend">
        <span className="senti-positive">긍정 {c.positive}</span>
        <span>중립 {c.neutral}</span>
        <span className="senti-negative">부정 {c.negative}</span>
      </div>
    </div>
  );
}

/** 업종 히트맵: 발산형(하락 파랑 ← 회색 → 상승 빨강), 모든 칸에 업종명·등락률 직접 표기. */
function hmClass(v: number | null): string {
  if (v === null || Math.abs(v) < 0.3) return "";
  const s = Math.abs(v) >= 2 ? 3 : Math.abs(v) >= 1 ? 2 : 1;
  return v > 0 ? `hm-up-${s}` : `hm-dn-${s}`;
}

export function Heatmap({ items }: { items: SectorItem[] }) {
  return (
    <>
      <div className="heatmap" role="list">
        {items.map((s) => (
          <div key={`${s.market}-${s.name}`} role="listitem" className={`hm-cell ${hmClass(s.change_pct)}`}
            title={`${s.name} ${pct(s.change_pct)}`}>
            <span className="n">{s.name}</span>
            <span className="v tnum">{pct(s.change_pct)}</span>
          </div>
        ))}
      </div>
      <div className="hm-legend" aria-hidden>
        <span className="lbl">하락</span>
        <i style={{ background: "var(--hm-dn-3)" }} /><i style={{ background: "var(--hm-dn-2)" }} />
        <i style={{ background: "var(--hm-dn-1)" }} /><i style={{ background: "var(--hm-mid)" }} />
        <i style={{ background: "var(--hm-up-1)" }} /><i style={{ background: "var(--hm-up-2)" }} />
        <i style={{ background: "var(--hm-up-3)" }} />
        <span className="lbl">상승</span>
        <span className="muted" style={{ marginLeft: "auto" }}>±0.3% · ±1% · ±2% 구간</span>
      </div>
    </>
  );
}

/** 보도량 추이: 최근 24시간 1시간 단위 막대. 막대마다 호버 툴팁. */
export function CoverageBars({ counts, width = 360, height = 40 }: { counts: number[]; width?: number; height?: number }) {
  const max = Math.max(1, ...counts);
  const gap = 2;
  const bw = (width - gap * (counts.length - 1)) / counts.length;
  const n = counts.length;
  return (
    <svg width={width} height={height + 12} viewBox={`0 0 ${width} ${height + 12}`} role="img"
      aria-label={`최근 ${n}시간 보도량: ${counts.join(", ")}`}>
      <line x1={0} x2={width} y1={height + 0.5} y2={height + 0.5} stroke="var(--axis)" strokeWidth={1} />
      {counts.map((c, i) => {
        const h = c ? Math.max(3, (c / max) * (height - 2)) : 0;
        const hoursAgo = n - 1 - i;
        return (
          <g key={i}>
            <rect x={i * (bw + gap)} y={0} width={bw} height={height} fill="transparent">
              <title>{hoursAgo === 0 ? "최근 1시간" : `${hoursAgo}~${hoursAgo + 1}시간 전`}: {c}건</title>
            </rect>
            {c > 0 && (
              <path d={roundedTop(i * (bw + gap), height - h, bw, h, Math.min(2, bw / 2))}
                fill={hoursAgo === 0 ? "var(--accent)" : "var(--neu-mark)"} pointerEvents="none" />
            )}
          </g>
        );
      })}
      <text x={0} y={height + 11} fontSize={10} fill="var(--muted)">24시간 전</text>
      <text x={width} y={height + 11} fontSize={10} fill="var(--muted)" textAnchor="end">지금</text>
    </svg>
  );
}

function roundedTop(x: number, y: number, w: number, h: number, r: number): string {
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
