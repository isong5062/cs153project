"""Single local user for v1 (the schema is multi-user ready)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User

DEFAULT_USERNAME = "local"


def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter_by(username=DEFAULT_USERNAME).one_or_none()
    if user is None:
        user = User(username=DEFAULT_USERNAME)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
