// 로그인 토큰을 담는 쿠키. HttpOnly 라 브라우저 스크립트는 읽지 못하고, Next 서버만 API 에 전달한다.
export const SESSION_COOKIE = "is_session";

// https 에서만 쿠키를 보내도록. 로컬에서 http 로 next start 할 때는 COOKIE_SECURE=false
export const COOKIE_SECURE =
  process.env.COOKIE_SECURE ? process.env.COOKIE_SECURE === "true" : process.env.NODE_ENV === "production";
