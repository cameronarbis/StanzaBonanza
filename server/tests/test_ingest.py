"""Ingestion is idempotent: re-running converges, never duplicates (§9)."""

import psycopg
import pytest

import ingest


def counts(conn):
    return conn.execute(
        """SELECT (SELECT count(*) FROM lines),
                  (SELECT count(*) FROM authors),
                  (SELECT count(*) FROM poems)"""
    ).fetchone()


def run_sample(url):
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(ingest.Path(ingest.HERE / "schema.sql").read_text())
        new = ingest.ingest_sample(cur)
        version = ingest.write_meta(cur, "test")
        conn.commit()
    return new, version


def test_sample_ingest_twice_is_idempotent(ingest_url):
    new_first, version_first = run_sample(ingest_url)
    assert new_first > 0
    with psycopg.connect(ingest_url) as conn:
        first = counts(conn)

    new_second, version_second = run_sample(ingest_url)
    assert new_second == 0
    assert version_second == version_first
    with psycopg.connect(ingest_url) as conn:
        assert counts(conn) == first


def test_load_lexicon_rescales_v21(tmp_path):
    # v2.1 files carry a header, multi-word terms, and scores in [-1, 1];
    # the loader must skip the first two and rescale the third to [0, 1].
    f = tmp_path / "lex.txt"
    f.write_text(
        "term\tvalence\tarousal\tdominance\n"
        "a battery\t0.134\t-0.298\t-0.096\n"
        "gloom\t-0.8\t-0.4\t0.0\n"
        "fire\t0.6\t0.9\t0.0\n"
    )
    lex = ingest.load_lexicon(f)
    assert "a battery" not in lex
    assert lex["gloom"] == pytest.approx((0.1, 0.3))
    assert lex["fire"] == pytest.approx((0.8, 0.95))


def test_score_line_requires_two_hits():
    lex = {"gloom": (0.1, 0.3), "fire": (0.8, 0.95)}
    assert ingest.score_line("the gloom alone", lex) is None
    v, a = ingest.score_line("gloom and fire together", lex)
    assert v == round((0.1 + 0.8) / 2, 3)
    assert a == round((0.3 + 0.95) / 2, 3)
