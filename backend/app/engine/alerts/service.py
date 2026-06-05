"""AlertService: persist operational alerts and fan out to channels.

Channels are best-effort and never raise into the caller: a logging channel
(always on) plus an optional webhook (POST JSON) when ``ALERT_WEBHOOK_URL`` is
configured. The webhook poster is injectable so this stays unit-testable without
any network access.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertLevel

logger = logging.getLogger("alerts")

_LOG_LEVEL = {
    AlertLevel.info: logging.INFO,
    AlertLevel.warning: logging.WARNING,
    AlertLevel.critical: logging.CRITICAL,
}

WebhookPoster = Callable[[str, dict[str, Any]], None]


class AlertService:
    def __init__(
        self,
        db: Session,
        webhook_url: str | None = None,
        webhook_poster: WebhookPoster | None = None,
    ) -> None:
        if webhook_url is None:
            from app.core.config import get_settings

            webhook_url = get_settings().alert_webhook_url
        self._db = db
        self._webhook_url = webhook_url
        self._poster = webhook_poster

    def emit(
        self,
        level: str | AlertLevel,
        category: str,
        message: str,
        detail: dict | None = None,
    ) -> Alert:
        level = AlertLevel(level)
        alert = Alert(level=level, category=category, message=message, detail=detail or {})
        self._db.add(alert)
        self._db.commit()
        self._db.refresh(alert)

        logger.log(_LOG_LEVEL[level], "[%s] %s", category, message)

        if self._webhook_url:
            try:
                self._post(
                    self._webhook_url,
                    {
                        "level": str(level),
                        "category": category,
                        "message": message,
                        "detail": detail or {},
                    },
                )
                alert.delivered = True
                self._db.commit()
            except Exception:  # delivery is best-effort; never break the caller
                logger.exception("alert webhook delivery failed")
        return alert

    def _post(self, url: str, payload: dict[str, Any]) -> None:
        if self._poster is not None:
            self._poster(url, payload)
            return
        import httpx

        httpx.post(url, json=payload, timeout=5.0)
