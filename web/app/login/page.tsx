// 로그인. 가입이 열려 있으면(SIGNUP_ENABLED) 가입 화면 링크를 보여준다.
import Link from "next/link";
import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import { getUser } from "@/lib/user";
import { LoginForm } from "@/components/watch";

export const dynamic = "force-dynamic";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  const dest = next?.startsWith("/") && !next.startsWith("//") ? next : "/";
  if (await getUser()) redirect(dest);
  const signup = await api.authConfig().then((c) => c.signup).catch(() => false);
  const q = dest === "/" ? "" : `?next=${encodeURIComponent(dest)}`;
  return (
    <div className="login-wrap">
      <section className="card pad login-card" aria-label="로그인">
        <h1>로그인</h1>
        <p className="muted">로그인하면 관심종목을 계정별로 저장하고 대시보드에서 시세·뉴스 심리를 볼 수 있습니다.</p>
        <LoginForm next={dest} />
        <p className="muted num-s">
          {signup ? <>계정이 없나요? <Link href={`/signup${q}`}>가입하기</Link></> : "계정이 없으면 관리자에게 요청하세요."}
        </p>
      </section>
    </div>
  );
}
