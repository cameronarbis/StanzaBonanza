"""Boundaries, content negotiation, error shape, rate limiting (§5, §9)."""

import pytest

from conftest import make_client


@pytest.mark.parametrize(
    "params",
    [
        {"a": 0.5},                                  # v missing
        {"v": -0.1, "a": 0.5},
        {"v": 1.1, "a": 0.5},
        {"v": 0.5, "a": 1.5},
        {"v": 0.5, "a": 0.5, "tau": 0.005},
        {"v": 0.5, "a": 0.5, "tau": 2.5},
        {"v": 0.5, "a": 0.5, "n": 0},
        {"v": 0.5, "a": 0.5, "n": 15},
        {"v": 0.5, "a": 0.5, "seed": -1},
        {"v": 0.5, "a": 0.5, "seed": 2**31},
        {"v": 0.5, "a": 0.5, "format": "xml"},
        {"v": 0.5, "a": 0.5, "exclude": [f"A{i}" for i in range(41)]},
    ],
)
def test_validation_rejects_out_of_range(client, params):
    resp = client.get("/api/poem", params=params)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "validation_error"
    assert body["status"] == 422
    assert body["detail"]


def test_boundary_values_accepted(client):
    resp = client.get("/api/poem", params={
        "v": 0, "a": 1, "tau": 0.01, "n": 14, "seed": 2**31 - 1})
    assert resp.status_code == 200


def test_json_is_default(client):
    resp = client.get("/api/poem", params={"v": 0.5, "a": 0.5})
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["corpus_version"] == "sha256:test"
    assert len(body["lines"]) == 1
    assert {"text", "author", "poem", "valence", "arousal"} <= body["lines"][0].keys()


def test_accept_text_plain(client):
    resp = client.get("/api/poem", params={"v": 0.5, "a": 0.5, "seed": 9},
                      headers={"Accept": "text/plain"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.headers["vary"] == "Accept"
    assert "— Author" in resp.text
    assert "seed=9" in resp.text


def test_format_overrides_accept(client):
    resp = client.get("/api/poem",
                      params={"v": 0.5, "a": 0.5, "format": "text"},
                      headers={"Accept": "application/json"})
    assert resp.headers["content-type"].startswith("text/plain")


def test_quality_weights_decide(client):
    resp = client.get("/api/poem", params={"v": 0.5, "a": 0.5},
                      headers={"Accept": "application/json;q=0.4, text/plain;q=0.9"})
    assert resp.headers["content-type"].startswith("text/plain")


def test_corpus_endpoint(client):
    body = client.get("/api/corpus").json()
    assert body == {"lines": 7, "authors": 7, "corpus_version": "sha256:test",
                    "built_at": "2026-01-01T00:00:00Z", "source": "test fixture"}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "db": True}


def test_unknown_api_route_is_json_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_empty_corpus_is_503(empty_url):
    with make_client(empty_url) as c:
        resp = c.get("/api/poem", params={"v": 0.5, "a": 0.5})
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"] == "service_unavailable"
        assert "ingestion" in body["detail"]


def test_rate_limit_429_with_retry_after(seeded_url):
    with make_client(seeded_url, rate_limit_per_minute=60, rate_limit_burst=2) as c:
        assert c.get("/api/poem", params={"v": 0.5, "a": 0.5}).status_code == 200
        assert c.get("/api/poem", params={"v": 0.5, "a": 0.5}).status_code == 200
        resp = c.get("/api/poem", params={"v": 0.5, "a": 0.5})
        assert resp.status_code == 429
        assert resp.json()["error"] == "rate_limited"
        assert int(resp.headers["retry-after"]) >= 1
        # health stays exempt — Railway polls it
        assert c.get("/api/health").status_code == 200
