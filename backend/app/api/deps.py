"""Shared API dependencies. Auth is a single-local-user stub for v1."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services.users import get_or_create_default_user


def current_user(db: Session = Depends(get_db)) -> User:
    return get_or_create_default_user(db)
