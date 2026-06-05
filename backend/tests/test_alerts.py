from datetime import UTC, datetime

from app.engine.alerts.service import AlertService
from app.engine.loop.orchestrator import Orchestrator
from app.engine.strategies.service import StrategyService
from app.models.account import EquitySnapshot
from app.models.alert import Alert
from app.models.strategy import StrategyStatus
from app.services.users import get_or_create_default_user
from tests.factories import default_spec


def test_emit_persists_alert(db_session):
    svc = AlertService(db_session, webhook_url="")
    a = svc.emit("warning", "test", "hello", {"x": 1})
    assert a.id is not None
    assert a.delivered is False
    rows = db_session.query(Alert).all()
    assert len(rows) == 1
    assert rows[0].level == "warning"
    assert rows[0].detail == {"x": 1}


def test_emit_invokes_webhook_and_marks_delivered(db_session):
    calls = []
    svc = AlertService(
        db_session,
        webhook_url="http://hook.local",
        webhook_poster=lambda url, payload: calls.append((url, payload)),
    )
    a = svc.emit("critical", "circuit_breaker", "boom")
    assert len(calls) == 1
    assert calls[0][0] == "http://hook.local"
    assert calls[0][1]["category"] == "circuit_breaker"
    assert a.delivered is True


def test_webhook_failure_does_not_raise(db_session):
    def boom(url, payload):
        raise RuntimeError("network down")

    svc = AlertService(db_session, webhook_url="http://hook.local", webhook_poster=boom)
    a = svc.emit("info", "test", "still ok")  # must not raise
    assert a.delivered is False  # delivery failed but the alert still persisted


def test_alerts_endpoint_returns_recent(client, db_session):
    AlertService(db_session, webhook_url="").emit("critical", "circuit_breaker", "halt")
    r = client.get("/alerts")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["category"] == "circuit_breaker"
    assert body[0]["level"] == "critical"


def test_alerts_endpoint_filters_by_level(client, db_session):
    svc = AlertService(db_session, webhook_url="")
    svc.emit("info", "a", "i")
    svc.emit("critical", "b", "c")
    body = client.get("/alerts", params={"level": "critical"}).json()
    assert len(body) == 1
    assert body[0]["level"] == "critical"


def test_orchestrator_emits_circuit_breaker_alert(db_session):
    """A drawdown stop during a tick raises exactly one critical alert."""
    user = get_or_create_default_user(db_session)
    strat = StrategyService(db_session).create_strategy(user.id, "DD", default_spec())
    strat.status = StrategyStatus.simulated
    db_session.commit()

    # Seed a high prior-equity peak so this tick is a >10% drawdown from peak.
    db_session.add(
        EquitySnapshot(
            strategy_id=strat.id, ts=datetime(2025, 1, 1, 15, 0), equity=200_000.0, cash=200_000.0
        )
    )
    db_session.commit()

    orch = Orchestrator(db_session)
    prices = {"AAPL": 100.0, "MSFT": 200.0}
    # Sim wallet starts at ~100k, so equity ~100k vs 200k peak -> -50% -> drawdown stop.
    orch.run_tick(datetime(2025, 1, 2, 15, 0, tzinfo=UTC), prices, force=True)

    alerts = db_session.query(Alert).filter(Alert.category == "circuit_breaker").all()
    assert len(alerts) == 1
    assert alerts[0].level == "critical"
    assert alerts[0].detail["strategy_id"] == strat.id

    # A second tick while still blocked must not duplicate the alert.
    orch.run_tick(datetime(2025, 1, 2, 15, 5, tzinfo=UTC), prices, force=True)
    assert db_session.query(Alert).filter(Alert.category == "circuit_breaker").count() == 1
