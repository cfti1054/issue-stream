"""계정 관리. 웹 가입 화면(/signup)과 관리자 CLI 가 같은 함수를 쓴다.

  issue-stream user add myid           비밀번호를 물어본 뒤 계정 생성
  issue-stream user passwd myid        비밀번호 변경 (기존 로그인 모두 해제)
  issue-stream user list
  issue-stream user disable|enable|delete myid

로그인 ID: 영문 소문자로 시작하는 4~20자, 영문 소문자·숫자·_ (대문자로 입력해도 소문자로 저장).
"""
from __future__ import annotations

import re

from sqlalchemy import delete, select

from .core.config import load_yaml
from .core.security import hash_password
from .db.models import Ticker, User, UserSession, UserWatchlist
from .db.ops import upsert
from .db.session import session_scope

MIN_PASSWORD = 8
USERNAME_RULE = "아이디는 영문 소문자로 시작하는 4~20자이며 영문 소문자·숫자·_ 만 쓸 수 있습니다"
_USERNAME = re.compile(r"^[a-z][a-z0-9_]{3,19}$")


class AccountError(ValueError):
    pass


class DuplicateAccountError(AccountError):
    pass


def normalize_username(username: str) -> str:
    return username.strip().lower()


def _check_username(username: str) -> str:
    username = normalize_username(username)
    if not _USERNAME.match(username):
        raise AccountError(USERNAME_RULE)
    return username


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다")


def create_user(username: str, password: str, name: str | None = None, default_watchlist: bool = True) -> int:
    """계정 생성. default_watchlist 면 watchlist.yaml 종목을 이 계정의 관심종목으로 넣어 둔다."""
    from .jobs.tasks import sync_watchlist
    username = _check_username(username)
    _check_password(password)
    with session_scope() as db:
        if db.scalar(select(User.id).where(User.username == username)):
            raise DuplicateAccountError(f"이미 사용 중인 아이디입니다: {username}")
        user = User(username=username, password_hash=hash_password(password), name=name)
        db.add(user)
        db.flush()
        if default_watchlist:
            for w in load_yaml("watchlist.yaml").get("watchlist", []):
                code = str(w["code"])
                upsert(db, Ticker, dict(code=code, name=w["name"], aliases=w.get("aliases", [])), ["code"], [])
                db.add(UserWatchlist(user_id=user.id, ticker=code, holding=bool(w.get("holding"))))
        uid = user.id
    sync_watchlist()
    return uid


def set_password(username: str, password: str) -> None:
    _check_password(password)
    with session_scope() as db:
        user = _get(db, username)
        user.password_hash = hash_password(password)
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))


def set_active(username: str, active: bool) -> None:
    with session_scope() as db:
        user = _get(db, username)
        user.is_active = active
        if not active:
            db.execute(delete(UserSession).where(UserSession.user_id == user.id))


def delete_user(username: str) -> None:
    from .jobs.tasks import sync_watchlist
    with session_scope() as db:
        user = _get(db, username)
        db.execute(delete(UserWatchlist).where(UserWatchlist.user_id == user.id))
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.delete(user)
    sync_watchlist()


def list_users() -> list[dict]:
    with session_scope() as db:
        return [{"username": u.username, "name": u.name, "active": u.is_active, "last_login_at": u.last_login_at,
                 "watchlist": len(db.scalars(select(UserWatchlist.ticker)
                                             .where(UserWatchlist.user_id == u.id)).all())}
                for u in db.scalars(select(User).order_by(User.id)).all()]


def _get(db, username: str) -> User:
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None:
        raise AccountError(f"계정이 없습니다: {username}")
    return user
