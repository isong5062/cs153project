"""Verifies DB wiring: a row round-trips."""

from app.models import User


def test_user_round_trip(db_session):
    db_session.add(User(username="local"))
    db_session.commit()

    user = db_session.query(User).filter_by(username="local").one()
    assert user.id is not None
    assert user.created_at is not None
