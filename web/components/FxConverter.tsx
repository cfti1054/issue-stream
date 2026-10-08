"use client";
// 환율 계산기: 원화 환율(매매기준율)로 외화 ↔ 원화 환산. 실제 환전은 은행 수수료(스프레드)가 붙는다.
import { useState } from "react";
import { num } from "@/lib/format";

type Rate = { currency: string; name: string; unit: number; close: number };

export default function FxConverter({ rates }: { rates: Rate[] }) {
  const [cur, setCur] = useState(rates[0]?.currency ?? "USD");
  const [toKRW, setToKRW] = useState(true);
  const [amount, setAmount] = useState("100");
  const r = rates.find((x) => x.currency === cur) ?? rates[0];
  if (!r) return <div className="empty">원화 환율 데이터가 없습니다</div>;

  const v = Number(amount.replace(/,/g, ""));
  const perOne = r.close / r.unit;   // 외화 1단위당 원
  const result = Number.isFinite(v) ? (toKRW ? v * perOne : v / perOne) : null;

  return (
    <div className="fx-conv">
      <div className="fx-conv-row">
        <input className="input tnum" inputMode="decimal" value={amount} aria-label="금액"
          onChange={(e) => setAmount(e.target.value)} />
        {toKRW ? (
          <select className="select" aria-label="통화" value={cur} onChange={(e) => setCur(e.target.value)}>
            {rates.map((x) => <option key={x.currency} value={x.currency}>{x.currency} {x.name}</option>)}
          </select>
        ) : <span className="fx-conv-cur">KRW 원</span>}
      </div>
      <button className="btn btn-s fx-swap" onClick={() => setToKRW(!toKRW)} aria-label="환산 방향 바꾸기">⇅</button>
      <div className="fx-conv-row">
        <output className="num-l tnum fx-conv-out">{result === null ? "–" : num(result, toKRW ? 0 : 2)}</output>
        {toKRW ? <span className="fx-conv-cur">KRW 원</span> : (
          <select className="select" aria-label="통화" value={cur} onChange={(e) => setCur(e.target.value)}>
            {rates.map((x) => <option key={x.currency} value={x.currency}>{x.currency} {x.name}</option>)}
          </select>
        )}
      </div>
      <p className="muted num-s">
        {r.unit} {r.currency} = {num(r.close, 2)}원 (매매기준율) · 실제 환전 시 은행 수수료가 붙습니다
      </p>
    </div>
  );
}
