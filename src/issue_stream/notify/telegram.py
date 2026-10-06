"""텔레그램 봇 알림 (무료). 토큰이 없으면 아무것도 하지 않는다.

봇 만들기: 텔레그램에서 @BotFather → /newbot → 토큰을 TELEGRAM_BOT_TOKEN 에.
채팅 ID: 봇에게 메시지를 보낸 뒤 https://api.telegram.org/bot<토큰>/getUpdates 에서 chat.id 확인.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings

log = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        return False
    try:
        r = httpx.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage", timeout=10,
                       json={"chat_id": s.telegram_chat_id, "text": text, "disable_web_page_preview": True})
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning("텔레그램 전송 실패: %s", e)
        return False


def send_issue_alert(issue_id: int, score: float, db: Session) -> bool:
    from ..db.models import IssueSummaryRow

    row = db.scalar(select(IssueSummaryRow).where(IssueSummaryRow.issue_id == issue_id,
                                                  IssueSummaryRow.is_current.is_(True)))
    if row is None:
        return False
    p = row.payload
    text = f"🔔 중요 이슈 ({score:.0f}점)\n{p['headline']}\n" + "\n".join(f"• {b}" for b in p["bullets"])
    return send_message(text)


def send_job_failure(job: str, message: str) -> None:
    send_message(f"⚠️ 작업 실패: {job}\n{message[:500]}")
