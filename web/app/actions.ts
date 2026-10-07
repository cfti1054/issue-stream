"use server";
// 브라우저에서 호출하는 서버 액션. API 는 내부망에만 있으므로 쓰기 요청도 Next 서버를 거친다.
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, api, type Session, type TickerHit } from "@/lib/api";
import { COOKIE_SECURE, SESSION_COOKIE } from "@/lib/session";

export type LoginState = { error?: string; username?: string };
export type SignupState = { error?: string; username?: string; name?: string };

/** 로그인 후 돌아갈 주소. 외부 주소로 보내지 않도록 같은 사이트 경로만 허용 */
function safeNext(v: FormDataEntryValue | null): string {
  const s = typeof v === "string" ? v : "";
  return s.startsWith("/") && !s.startsWith("//") ? s : "/";
}

async function startSession(r: Session): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, r.token, {
    httpOnly: true, sameSite: "lax", secure: COOKIE_SECURE, path: "/", expires: new Date(r.expires_at),
  });
}

export async function loginAction(_prev: LoginState, form: FormData): Promise<LoginState> {
  const username = String(form.get("username") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!username || !password) return { error: "아이디와 비밀번호를 입력하세요.", username };
  try {
    await startSession(await api.login(username, password));
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "로그인 중 오류가 발생했습니다.", username };
  }
  revalidatePath("/", "layout");
  redirect(safeNext(form.get("next")));
}

/** 가입 → 바로 로그인 상태로 돌아갈 화면으로 이동 */
export async function signupAction(_prev: SignupState, form: FormData): Promise<SignupState> {
  const username = String(form.get("username") ?? "").trim();
  const name = String(form.get("name") ?? "").trim();
  const password = String(form.get("password") ?? "");
  const keep = { username, name };
  if (!username || !password) return { error: "아이디와 비밀번호를 입력하세요.", ...keep };
  if (password !== String(form.get("password2") ?? "")) return { error: "비밀번호가 서로 다릅니다.", ...keep };
  try {
    await startSession(await api.signup({
      username, password, name: name || undefined, invite_code: String(form.get("invite_code") ?? "") || undefined,
    }));
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "가입 중 오류가 발생했습니다.", ...keep };
  }
  revalidatePath("/", "layout");
  redirect(safeNext(form.get("next")));
}

export async function logoutAction(): Promise<void> {
  try { await api.logout(); } catch { /* 이미 만료된 세션이어도 쿠키는 지운다 */ }
  (await cookies()).delete(SESSION_COOKIE);
  revalidatePath("/", "layout");
  redirect("/");
}

/** ☆ 관심종목 등록 / 보유 표시 변경. 실패 시 오류 메시지를 돌려준다 */
export async function watchAction(code: string, holding?: boolean): Promise<string | null> {
  try {
    await api.watch(code, holding);
  } catch (e) {
    return e instanceof ApiError && e.status === 401 ? "로그인이 필요합니다." : String((e as Error).message);
  }
  revalidatePath("/", "layout");
  return null;
}

/** ★ 관심종목 해제 */
export async function unwatchAction(code: string): Promise<string | null> {
  try {
    await api.unwatch(code);
  } catch (e) {
    return String((e as Error).message);
  }
  revalidatePath("/", "layout");
  return null;
}

export async function searchTickersAction(q: string): Promise<TickerHit[]> {
  if (!q.trim()) return [];
  try { return await api.searchTickers(q); } catch { return []; }
}
