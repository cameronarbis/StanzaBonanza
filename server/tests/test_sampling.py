"""The distribution, the lottery rule, and determinism (docs/DESIGN.md §9)."""

from collections import Counter


def draw(client, **params):
    resp = client.get("/api/poem", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_deterministic_per_seed(client):
    a = draw(client, v=0.5, a=0.5, n=5, seed=42)
    b = draw(client, v=0.5, a=0.5, n=5, seed=42)
    assert a == b
    assert a["params"]["seed"] == 42


def test_different_seeds_can_differ(client):
    # High tau: near-uniform, so 10 lines across two seeds colliding
    # exactly is (1/7)^-ish improbable; a flaky pass here would need
    # both sequences identical.
    a = draw(client, v=0.5, a=0.5, tau=2.0, n=7, seed=1)
    b = draw(client, v=0.5, a=0.5, tau=2.0, n=7, seed=2)
    assert a["lines"] != b["lines"]


def test_lottery_rule_no_author_repeats(client):
    poem = draw(client, v=0.5, a=0.5, tau=2.0, n=7)
    authors = [line["author"] for line in poem["lines"]]
    assert len(authors) == 7
    assert len(set(authors)) == 7


def test_lottery_resets_when_pool_exhausts(client):
    # 7 authors, 14 lines requested: the exclusion set must reset rather
    # than truncate the poem.
    poem = draw(client, v=0.5, a=0.5, tau=2.0, n=14)
    assert len(poem["lines"]) == 14


def test_exclude_is_honored(client):
    poem = draw(client, v=0.5, a=0.5, tau=2.0, n=6,
                exclude=["Author A", "Author B"])
    authors = {line["author"] for line in poem["lines"]}
    assert "Author A" not in authors
    assert "Author B" not in authors


def test_low_tau_is_nearly_greedy(client):
    # Target sits exactly on Author A's line; nearest competitor is
    # ~0.28 away, so at tau=0.02 its weight ratio is exp(-14) ≈ 1e-6.
    counts = Counter(
        draw(client, v=0.5, a=0.5, tau=0.02, n=1, seed=s)["lines"][0]["author"]
        for s in range(100)
    )
    assert counts["Author A"] >= 98


def test_high_tau_approaches_uniform(client):
    counts = Counter(
        draw(client, v=0.5, a=0.5, tau=2.0, n=1, seed=s)["lines"][0]["author"]
        for s in range(300)
    )
    assert len(counts) == 7                  # every line reachable
    assert max(counts.values()) <= 300 * 0.35  # none dominates
