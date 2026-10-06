
import pytest
from fastapi.testclient import TestClient

from app.main import create_app, summarize


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "t.db", seed_path=False))


def trip(**kw):
    base = {"id": "a", "start": "2026-10-01T08:00:00+05:00", "end": "2026-10-01T08:20:00+05:00",
            "amount": 2000, "payment": "card", "commission": 300}
    return {**base, **kw}


def test_summary_math():
    s = summarize([trip(), trip(id="b", amount=1000, payment="cash", commission=150)])
    assert s["count"] == 2 and s["revenue"] == 3000 and s["commission"] == 450 and s["net"] == 2550
    assert s["cash"] == {"count": 1, "revenue": 1000} and s["card"] == {"count": 1, "revenue": 2000}


def test_summary_empty_day():
    assert summarize([])["net"] == 0


def test_duplicate_is_not_created(client):
    assert client.post("/api/trips", json=trip()).status_code == 201
    r = client.post("/api/trips", json=trip())
    assert r.status_code == 200 and r.json()["created"] is False
    assert len(client.get("/api/trips", params={"day": "2026-10-01"}).json()) == 1
    assert client.get("/api/summary", params={"day": "2026-10-01"}).json()["revenue"] == 2000


def test_same_id_different_data_conflicts(client):
    client.post("/api/trips", json=trip())
    assert client.post("/api/trips", json=trip(amount=999)).status_code == 409


def test_same_instant_other_offset_is_still_duplicate(client):
    client.post("/api/trips", json=trip())
    again = trip(start="2026-10-01T03:00:00+00:00", end="2026-10-01T03:20:00+00:00")
    assert client.post("/api/trips", json=again).status_code == 200


@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": -5}, {"end": "2026-10-01T08:00:00+05:00"},
    {"end": "2026-10-01T07:00:00+05:00"}, {"payment": "crypto"}, {"commission": 5000},
    {"start": "2026-10-01T08:00:00"},
])
def test_validation(client, bad):
    assert client.post("/api/trips", json=trip(**bad)).status_code == 422


def test_trips_filtered_by_day(client):
    client.post("/api/trips", json=trip())
    client.post("/api/trips", json=trip(id="n", start="2026-10-02T08:00:00+05:00", end="2026-10-02T09:00:00+05:00"))
    assert [t["id"] for t in client.get("/api/trips", params={"day": "2026-10-02"}).json()] == ["n"]
