"use client";
// 로그인·관심종목 조작 (브라우저에서 동작하는 부분). 실제 요청은 서버 액션(app/actions.ts)이 보낸다.
import Link from "next/link";
import { useActionState, useEffect, useRef, useState, useTransition } from "react";
import {
  loginAction, logoutAction, searchTickersAction, signupAction, unwatchAction, watchAction,
  type LoginState, type SignupState,
} from "@/app/actions";
import type { TickerHit } from "@/lib/api";

/** ☆ / ★ 관심종목 토글 */
export function StarButton({ code, name, watched, size = "m" }: {
  code: string; name: string; watched: boolean; size?: "s" | "m";
}) {
  const [on, setOn] = useState(watched);
  const [pending, start] = useTransition();
  useEffect(() => setOn(watched), [watched]);
  const label = on ? `${name} 관심종목 해제` : `${name} 관심종목 등록`;
  return (
    <button type="button" className={`star star-${size}`} aria-pressed={on} aria-label={label} title={label}
      disabled={pending}
      onClick={() => start(async () => {
        setOn(!on); // 먼저 바꿔 보여주고 실패하면 되돌린다
        const err = on ? await unwatchAction(code) : await watchAction(code);
        if (err) { setOn(on); alert(err); }
      })}>
      {on ? "★" : "☆"}
    </button>
  );
}

/** 보유 표시 토글 (중요도 점수 가산점) */
export function HoldToggle({ code, holding }: { code: string; holding: boolean }) {
  const [pending, start] = useTransition();
  return (
    <button type="button" className={`hold-toggle ${holding ? "on" : ""}`} aria-pressed={holding} disabled={pending}
      title={holding ? "보유 해제" : "보유 종목으로 표시 (이 종목 뉴스의 중요도가 올라갑니다)"}
      onClick={() => start(async () => {
        const err = await watchAction(code, !holding);
        if (err) alert(err);
      })}>
      보유
    </button>
  );
}

/** 종목 검색 → ☆ 로 관심종목 추가 */
export function WatchSearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<TickerHit[]>([]);
  const [open, setOpen] = useState(false);
  const seq = useRef(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (!term) { setHits([]); return; }
    const my = ++seq.current;
    const t = setTimeout(async () => {
      const r = await searchTickersAction(term);
      if (my === seq.current) { setHits(r); setOpen(true); }
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="watch-search" ref={box}>
      <input className="input" type="search" placeholder="종목명 또는 코드로 검색해 ☆ 추가" value={q}
        aria-label="관심종목 추가 검색" onChange={(e) => setQ(e.target.value)} onFocus={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }} />
      {open && q.trim() && (
        <ul className="watch-results" role="listbox">
          {hits.length === 0 && <li className="muted">검색 결과 없음</li>}
          {hits.map((h) => (
            <li key={h.code}>
              <StarButton code={h.code} name={h.name} watched={h.watched} size="s" />
              <Link href={`/?ticker=${h.code}`} scroll={false} onClick={() => setOpen(false)}>
                <span className="name">{h.name}</span> <span className="code">{h.code}{h.market ? ` · ${h.market}` : ""}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LoginForm({ next }: { next: string }) {
  const [state, action, pending] = useActionState<LoginState, FormData>(loginAction, {});
  return (
    <form action={action} className="login-form">
      <input type="hidden" name="next" value={next} />
      <label>
        <span>아이디</span>
        <input className="input" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
          required defaultValue={state.username} autoFocus />
      </label>
      <label>
        <span>비밀번호</span>
        <input className="input" name="password" type="password" autoComplete="current-password" required />
      </label>
      {state.error && <p className="form-error" role="alert">{state.error}</p>}
      <button className="btn" type="submit" disabled={pending}>{pending ? "로그인 중…" : "로그인"}</button>
    </form>
  );
}

export function SignupForm({ next, inviteRequired, minPassword, usernameRule }: {
  next: string; inviteRequired: boolean; minPassword: number; usernameRule: string;
}) {
  const [state, action, pending] = useActionState<SignupState, FormData>(signupAction, {});
  return (
    <form action={action} className="login-form">
      <input type="hidden" name="next" value={next} />
      <label>
        <span>아이디</span>
        <input className="input" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
          required minLength={4} maxLength={20} pattern="[A-Za-z][A-Za-z0-9_]{3,19}" title={usernameRule}
          defaultValue={state.username} autoFocus aria-describedby="username-help" />
        <small id="username-help" className="muted">영문으로 시작, 4~20자 (영문·숫자·_)</small>
      </label>
      <label>
        <span>이름 <small className="muted">(선택, 상단에 표시)</small></span>
        <input className="input" name="name" maxLength={60} autoComplete="nickname" defaultValue={state.name} />
      </label>
      <label>
        <span>비밀번호 <small className="muted">({minPassword}자 이상)</small></span>
        <input className="input" name="password" type="password" autoComplete="new-password" required
          minLength={minPassword} />
      </label>
      <label>
        <span>비밀번호 확인</span>
        <input className="input" name="password2" type="password" autoComplete="new-password" required
          minLength={minPassword} />
      </label>
      {inviteRequired && (
        <label>
          <span>초대 코드</span>
          <input className="input" name="invite_code" autoComplete="off" required />
        </label>
      )}
      {state.error && <p className="form-error" role="alert">{state.error}</p>}
      <button className="btn" type="submit" disabled={pending}>{pending ? "가입 중…" : "가입하고 시작하기"}</button>
    </form>
  );
}

export function LogoutButton() {
  return (
    <form action={logoutAction}>
      <button className="link-btn" type="submit">로그아웃</button>
    </form>
  );
}
