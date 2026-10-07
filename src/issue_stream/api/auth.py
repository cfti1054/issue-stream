"""로그인·세션.

웹(Next.js 서버)이 로그인 결과로 받은 토큰을 HttpOnly 쿠키에 넣어 두고, API 를 부를 때마다
`Authorization: Bearer <토큰>` 으로 넘긴다. 브라우저는 API 를 직접 부르지 않는다.
계정은 가입 화면(/auth/signup, SIGNUP_ENABLED·SIGNUP_INVITE_CODE)이나 `issue-stream user add` 로 만든다.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import accounts
from ..core.config import get_settings
from ..core.security import dummy_verify, new_session_token, token_hash, verify_password
from ..db.models import User, UserSession
from ..db.session import SessionLocal

router = APIRouter(prefix="/auth", tags=["auth"])


def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def optional_user(authorization: str | None = Header(None), s: Session = Depends(db)) -> User | None:
    """로그인했으면 계정, 아니면 None (공개 화면용)."""
    token = _bearer(authorization)
    if not token:
        return None
    row = s.get(UserSession, token_hash(token))
    if not row or row.expires_at < _now():
        return None
    user = s.get(User, row.user_id)
    return user if user and user.is_active else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다")
    return user


def user_json(u: User) -> dict:
    return {"no": u.no, "username": u.username, "name": u.name}


class LoginIn(BaseModel):
    username: str
    password: str


def _issue_session(s: Session, user: User) -> dict:
    token = new_session_token()
    expires = _now() + timedelta(days=get_settings().session_days)
    s.add(UserSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
    user.last_login_at = _now()
    s.commit()
    return {"token": token, "expires_at": expires, "user": user_json(user)}


@router.get("/config")
def auth_config():
    """가입 화면을 보여줄지, 초대 코드 칸이 필요한지."""
    st = get_settings()
    return {"signup": st.signup_enabled, "invite_required": bool(st.signup_invite_code),
            "min_password": accounts.MIN_PASSWORD, "username_rule": accounts.USERNAME_RULE}


class SignupIn(BaseModel):
    username: str
    password: str
    name: str | None = None
    invite_code: str | None = None


@router.post("/signup", status_code=201)
def signup(body: SignupIn, s: Session = Depends(db)):
    """가입 후 바로 로그인한 상태로 토큰을 돌려준다. 관심종목은 watchlist.yaml 종목으로 시작."""
    st = get_settings()
    if not st.signup_enabled:
        raise HTTPException(403, "가입이 닫혀 있습니다. 관리자에게 계정을 요청하세요")
    if st.signup_invite_code and not hmac.compare_digest(
            (body.invite_code or "").strip().encode(), st.signup_invite_code.encode()):
        raise HTTPException(403, "초대 코드가 올바르지 않습니다")
    name = (body.name or "").strip()[:60] or None
    try:
        uid = accounts.create_user(body.username, body.password, name)
    except accounts.AccountError as e:
        status = 409 if isinstance(e, accounts.DuplicateAccountError) else 400
        raise HTTPException(status, str(e)) from None
    return _issue_session(s, s.get(User, uid))


@router.post("/login")
def login(body: LoginIn, s: Session = Depends(db)):
    user = s.scalar(select(User).where(User.username == accounts.normalize_username(body.username)))
    if user is None or not user.is_active:
        dummy_verify(body.password)  # 계정 존재 여부가 응답 시간으로 드러나지 않도록
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    return _issue_session(s, user)


@router.post("/logout", status_code=204)
def logout(authorization: str | None = Header(None), s: Session = Depends(db)):
    token = _bearer(authorization)
    if token:
        s.execute(delete(UserSession).where(UserSession.token_hash == token_hash(token)))
        s.commit()


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_json(user)
