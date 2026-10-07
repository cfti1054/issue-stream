"""login by username instead of email

users.email → users.username. 기존 계정은 이메일의 @ 앞부분을 아이디 규칙에 맞게 바꿔 쓰고,
겹치면 뒤에 번호를 붙인다 (예: me@example.com → me, 겹치면 me_2). 새 DB 는 0001 에서 이미 username 으로 만들어진다.
SQLite 는 RENAME COLUMN 으로 바꿔 users 의 트리거·인덱스(trg_users_no, uq_users_no)를 그대로 유지한다.

Revision ID: 0005
Revises: 0004
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _columns(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns("users")}


def _username_from_email(email: str) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", email.split("@")[0].lower()).strip("_") or "user"
    if not base[0].isalpha():
        base = "u" + base
    return base[:20].ljust(4, "0")


def upgrade():
    bind = op.get_bind()
    if "email" not in _columns(bind):
        return
    taken: set[str] = set()
    for uid, email in bind.execute(sa.text("SELECT id, email FROM users ORDER BY id")).all():
        name = base = _username_from_email(email)
        n = 2
        while name in taken:
            suffix = f"_{n}"
            name, n = base[:20 - len(suffix)] + suffix, n + 1
        taken.add(name)
        bind.execute(sa.text("UPDATE users SET email = :u WHERE id = :id"), {"u": name, "id": uid})
    op.execute("ALTER TABLE users RENAME COLUMN email TO username")
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users ALTER COLUMN username TYPE VARCHAR(20)")
        op.execute("ALTER TABLE users RENAME CONSTRAINT users_email_key TO users_username_key")
        op.execute("COMMENT ON COLUMN users.username IS '로그인 ID (소문자로 저장)'")


def downgrade():
    bind = op.get_bind()
    if "username" not in _columns(bind):
        return
    op.execute("ALTER TABLE users RENAME COLUMN username TO email")
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users ALTER COLUMN email TYPE VARCHAR(254)")
        op.execute("ALTER TABLE users RENAME CONSTRAINT users_username_key TO users_email_key")
