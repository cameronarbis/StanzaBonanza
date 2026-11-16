"""
Test harness: a throwaway Postgres cluster per session (initdb + pg_ctl
on a unix socket), three databases — seeded, empty, and one for
ingestion tests. PoetryDB is never called (docs/DESIGN.md §9).
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline"))

from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402

SCHEMA = (Path(__file__).resolve().parents[2] / "pipeline" / "schema.sql").read_text()

# Known coordinates so distribution assertions are exact: one line at the
# center, six spread out, all distinct authors.
SEED_LINES = [
    ("Author A", "Poem A", "a line at dead center", 0.50, 0.50),
    ("Author B", "Poem B", "a bright loud line", 0.90, 0.90),
    ("Author C", "Poem C", "a dark quiet line", 0.10, 0.10),
    ("Author D", "Poem D", "a bright quiet line", 0.90, 0.10),
    ("Author E", "Poem E", "a dark loud line", 0.10, 0.90),
    ("Author F", "Poem F", "a gloomy stirring line", 0.30, 0.70),
    ("Author G", "Poem G", "a warm settling line", 0.70, 0.30),
]


@pytest.fixture(scope="session")
def pg(tmp_path_factory):
    datadir = tmp_path_factory.mktemp("pgdata")
    # Unix socket paths cap at 103 bytes and pytest's tmp dirs blow past
    # that on macOS; the socket dir must live somewhere short.
    sockdir = tempfile.mkdtemp(prefix="sbpg", dir="/tmp")
    log = datadir / "pg.log"
    subprocess.run(
        ["initdb", "-D", str(datadir), "-U", "stanza", "-A", "trust", "--no-sync"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["pg_ctl", "start", "-D", str(datadir), "-l", str(log), "-w", "-o",
         f"-c listen_addresses='' -c unix_socket_directories={sockdir} -F"],
        check=True, capture_output=True, timeout=60,
    )
    try:
        with psycopg.connect(f"postgresql://stanza@/postgres?host={sockdir}", autocommit=True) as conn:
            for db in ("stanza_seeded", "stanza_empty", "stanza_ingest"):
                conn.execute(f"CREATE DATABASE {db}")
        yield f"postgresql://stanza@/{{}}?host={sockdir}"
    finally:
        subprocess.run(["pg_ctl", "stop", "-D", str(datadir), "-m", "immediate"],
                       capture_output=True, timeout=60)
        shutil.rmtree(sockdir, ignore_errors=True)


@pytest.fixture(scope="session")
def seeded_url(pg):
    url = pg.format("stanza_seeded")
    with psycopg.connect(url) as conn:
        conn.execute(SCHEMA)
        for author, poem, text, v, a in SEED_LINES:
            conn.execute("INSERT INTO authors (name) VALUES (%s)", (author,))
            conn.execute(
                """INSERT INTO poems (author_id, title)
                   SELECT id, %s FROM authors WHERE name = %s""",
                (poem, author),
            )
            conn.execute(
                """INSERT INTO lines (poem_id, text, text_norm, valence, arousal)
                   SELECT p.id, %s, %s, %s, %s FROM poems p WHERE p.title = %s""",
                (text, text.lower(), v, a, poem),
            )
        conn.execute(
            """INSERT INTO corpus_meta (key, value) VALUES
               ('version', 'sha256:test'), ('built_at', '2026-01-01T00:00:00Z'),
               ('source', 'test fixture')"""
        )
        conn.commit()
    return url


@pytest.fixture(scope="session")
def empty_url(pg):
    url = pg.format("stanza_empty")
    with psycopg.connect(url) as conn:
        conn.execute(SCHEMA)
        conn.commit()
    return url


@pytest.fixture(scope="session")
def ingest_url(pg):
    return pg.format("stanza_ingest")


def make_client(url: str, **overrides) -> TestClient:
    settings = Settings(
        database_url=url,
        rate_limit_per_minute=overrides.pop("rate_limit_per_minute", 100_000),
        rate_limit_burst=overrides.pop("rate_limit_burst", 100_000),
        **overrides,
    )
    return TestClient(create_app(settings))


@pytest.fixture(scope="session")
def client(seeded_url):
    with make_client(seeded_url) as c:
        yield c
