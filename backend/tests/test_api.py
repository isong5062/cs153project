from tests.factories import default_spec


def _spec_json(**kw):
    return default_spec(**kw).model_dump(mode="json")


def test_create_and_list_strategy(client):
    r = client.post("/strategies", json={"name": "T", "spec": _spec_json()})
    assert r.status_code == 201
    sid = r.json()["id"]
    listed = client.get("/strategies").json()
    assert any(s["id"] == sid for s in listed)


def test_get_strategy_404(client):
    assert client.get("/strategies/999").status_code == 404


def test_get_spec_returns_current(client):
    sid = client.post("/strategies", json={"name": "T", "spec": _spec_json()}).json()["id"]
    r = client.get(f"/strategies/{sid}/spec")
    assert r.status_code == 200
    assert "regime_rules" in r.json()


def test_update_spec_creates_version(client):
    sid = client.post("/strategies", json={"name": "T", "spec": _spec_json()}).json()["id"]
    r = client.put(f"/strategies/{sid}/spec", json={"spec": _spec_json(universe=["TSLA"])})
    assert r.status_code == 200
    assert r.json()["version_num"] == 2


def test_promote_sets_live(client):
    sid = client.post("/strategies", json={"name": "T", "spec": _spec_json()}).json()["id"]
    client.post(f"/strategies/{sid}/status", json={"status": "simulated"})
    r = client.post(f"/strategies/{sid}/promote")
    assert r.json()["status"] == "live"


def test_settings_has_no_secret_leak(client):
    r = client.get("/settings")
    body = r.json()
    assert r.status_code == 200
    assert body["paper_only"] is True
    assert isinstance(body["alpaca_configured"], bool)
    assert "alpaca_api_key" not in r.text
    assert "anthropic_api_key" not in r.text


def test_regime_current_empty(client):
    assert client.get("/regimes/current").json() is None


def test_proposals_empty(client):
    assert client.get("/proposals").json() == []


def test_risk_status_unblocked(client):
    assert client.get("/risk/status").json()["blocked"] is False


def test_websocket_snapshot(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
