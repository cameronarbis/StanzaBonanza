"""Connection pool and read queries. The server never writes (docs/DESIGN.md §2)."""

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def make_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(
        database_url,
        min_size=1,
        max_size=4,
        kwargs={"row_factory": dict_row},
        open=False,
    )


def corpus_info(conn) -> dict:
    counts = conn.execute(
        """SELECT (SELECT count(*) FROM lines)   AS lines,
                  (SELECT count(*) FROM authors) AS authors"""
    ).fetchone()
    meta = {
        row["key"]: row["value"]
        for row in conn.execute("SELECT key, value FROM corpus_meta").fetchall()
    }
    return {
        "lines": counts["lines"],
        "authors": counts["authors"],
        "corpus_version": meta.get("version", "unknown"),
        "built_at": meta.get("built_at", "unknown"),
        "source": meta.get("source", "unknown"),
    }
