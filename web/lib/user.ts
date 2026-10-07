// 현재 로그인한 계정 (서버 전용). 쿠키가 없으면 API 를 부르지 않는다.
import { cookies } from "next/headers";
import { api, type User } from "./api";
import { SESSION_COOKIE } from "./session";

export async function getUser(): Promise<User | null> {
  if (!(await cookies()).get(SESSION_COOKIE)) return null;
  try {
    return await api.me();
  } catch {
    return null; // 만료된 세션 또는 API 연결 실패 → 비로그인으로 보여준다
  }
}
