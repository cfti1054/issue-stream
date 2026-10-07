// 가입. SIGNUP_ENABLED=false 면 닫히고, SIGNUP_INVITE_CODE 가 있으면 초대 코드 칸이 나온다.
import Link from "next/link";
import { redirect } from "next/navigation";
import { ApiError, api, type AuthConfig } from "@/lib/api";
import { getUser } from "@/lib/user";
import { SignupForm } from "@/components/watch";

export const dynamic = "force-dynamic";

export default async function SignupPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  const dest = next?.startsWith("/") && !next.startsWith("//") ? next : "/";
  if (await getUser()) redirect(dest);
  let cfg: AuthConfig | null = null;
  let error = "";
  try {
    cfg = await api.authConfig();
  } catch (e) {
    // 404 = api 서비스가 가입 기능이 없는 이전 버전 (새 배포 실패·진행 중)
    error = e instanceof ApiError && e.status === 404
      ? "API 서버가 이전 버전입니다. api 서비스의 최신 배포가 끝났는지 확인하세요."
      : e instanceof Error ? e.message : String(e);
  }
  const q = dest === "/" ? "" : `?next=${encodeURIComponent(dest)}`;
  return (
    <div className="login-wrap">
      <section className="card pad login-card" aria-label="가입">
        <h1>가입</h1>
        {cfg?.signup ? (
          <>
            <p className="muted">가입하면 기본 종목이 관심종목으로 들어가 있고, ☆ 로 원하는 종목을 더할 수 있습니다.</p>
            <SignupForm next={dest} inviteRequired={cfg.invite_required} minPassword={cfg.min_password}
              usernameRule={cfg.username_rule} />
          </>
        ) : (
          <p className="muted">
            {cfg ? "지금은 가입을 받지 않습니다. 관리자에게 계정을 요청하세요." : `가입 설정을 불러오지 못했습니다: ${error}`}
          </p>
        )}
        <p className="muted num-s">이미 계정이 있나요? <Link href={`/login${q}`}>로그인</Link></p>
      </section>
    </div>
  );
}
