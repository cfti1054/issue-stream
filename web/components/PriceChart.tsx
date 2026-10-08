"use client";
// 선택 종목 가격 차트: 2px 선 + 옅은 영역, 가로 격자, 호버 시 십자선과 툴팁.
import { useMemo, useRef, useState } from "react";
import type { PricePoint } from "@/lib/api";
import { num, pct } from "@/lib/format";

const RANGES = [
  { key: "1M", label: "1개월", n: 22 },
  { key: "3M", label: "3개월", n: 66 },
  { key: "ALL", label: "전체", n: 10_000 },
] as const;

const W = 640, H = 240, L = 8, R = 56, T = 10, B = 24;

export default function PriceChart({ points, isIndex = false, digits: fixedDigits }: {
  points: PricePoint[]; isIndex?: boolean; digits?: number;
}) {
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("3M");
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const data = useMemo(() => {
    const n = RANGES.find((r) => r.key === range)!.n;
    return points.slice(-n);
  }, [points, range]);

  if (data.length < 2) return <div className="empty">가격 데이터가 없습니다</div>;

  const closes = data.map((p) => p.close);
  let min = Math.min(...closes), max = Math.max(...closes);
  const padV = (max - min) * 0.08 || max * 0.01;
  min -= padV; max += padV;
  const x = (i: number) => L + (i / (data.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - min) / (max - min)) * (H - T - B);
  const line = data.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join("");
  const area = `${line}L${x(data.length - 1)},${H - B}L${x(0)},${H - B}Z`;
  const first = data[0].close, last = data[data.length - 1].close;
  const periodPct = (last / first - 1) * 100;
  const color = last >= first ? "var(--up-mark)" : "var(--down-mark)";
  const ticks = niceTicks(min, max, 4);
  const digits = fixedDigits ?? (isIndex ? 2 : 0);
  const dateTicks = [0, Math.floor((data.length - 1) / 2), data.length - 1];

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = svgRef.current!.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((px - L) / (W - L - R)) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  }

  const hp = hover !== null ? data[hover] : null;

  return (
    <div>
      <div className="chart-head">
        <div>
          <div className="muted num-s">{RANGES.find((r) => r.key === range)!.label} 등락</div>
          <div className={`num-m tnum ${periodPct >= 0 ? "up" : "down"}`} style={{ fontWeight: 700 }}>
            {periodPct >= 0 ? "▲" : "▼"} {pct(periodPct)}
          </div>
        </div>
        <div className="seg" role="group" aria-label="기간">
          {RANGES.map((r) => (
            <button key={r.key} aria-pressed={range === r.key} onClick={() => setRange(r.key)}>{r.label}</button>
          ))}
        </div>
      </div>
      <div className="chart-wrap">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img"
          aria-label={`가격 차트, ${data[0].day}부터 ${data[data.length - 1].day}까지, 종가 ${num(first, digits)}에서 ${num(last, digits)}`}
          onPointerMove={onMove} onPointerLeave={() => setHover(null)} style={{ touchAction: "pan-y" }}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
              <text x={W - R + 6} y={y(t) + 3.5} fontSize={10.5} fill="var(--muted)" className="tnum">{num(t, digits)}</text>
            </g>
          ))}
          <line x1={L} x2={W - R} y1={H - B + 0.5} y2={H - B + 0.5} stroke="var(--axis)" />
          {dateTicks.map((i, k) => (
            <text key={i} x={x(i)} y={H - 6} fontSize={10.5} fill="var(--muted)"
              textAnchor={k === 0 ? "start" : k === 2 ? "end" : "middle"}>{data[i].day.slice(5).replace("-", "/")}</text>
          ))}
          <path d={area} fill={color} opacity={0.08} />
          <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hp && hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="var(--axis)" strokeDasharray="3 3" />
              <circle cx={x(hover)} cy={y(hp.close)} r={4.5} fill={color} stroke="var(--surface)" strokeWidth={2} />
            </g>
          )}
          <rect x={L} y={T} width={W - L - R} height={H - T - B} fill="transparent" />
        </svg>
        {hp && hover !== null && (
          <div className="tooltip" style={{ left: `${(x(hover) / W) * 100}%`, top: `${(y(hp.close) / H) * 100}%` }}>
            <div className="muted">{hp.day}</div>
            <b className="tnum">{num(hp.close, digits)}</b>{" "}
            {hp.change_pct !== null && (
              <span className={`tnum ${hp.change_pct >= 0 ? "up" : "down"}`}>{pct(hp.change_pct)}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function niceTicks(min: number, max: number, count: number): number[] {
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) out.push(Number(v.toFixed(6)));
  return out;
}
