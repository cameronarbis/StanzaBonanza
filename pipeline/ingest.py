#!/usr/bin/env python3
"""
ingest.py — PoetryDB → line splitting → NRC-VAD scoring → Postgres.

The write-side half of StanzaBonanza v1 (docs/DESIGN.md §6). Runs
manually and politely; PoetryDB is never touched by user traffic.
Re-running converges instead of duplicating: inserts are idempotent
on normalized line text.

Usage:
    export DATABASE_URL=postgresql://...
    python ingest.py --max-authors 40
    python ingest.py --sample          # load the bundled 26-line corpus
    python ingest.py --wipe ...        # truncate first, then ingest

Against Railway, DATABASE_URL is the credentialed public TCP proxy URL
(the deployed app uses the private-network URL; this script runs from
your machine).

Lexicon: NRC-VAD v2.1, downloaded from
https://saifmohammad.com/WebPages/nrc-vad.html — not committed to the
repo (its terms direct users to the source). v2.1 scores live in
[-1, 1]; they are rescaled to [0, 1] here so the schema and the
sampler see one range.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import psycopg
import requests

POETRYDB = "https://poetrydb.org"
WORD_RE = re.compile(r"[a-z']+")
HERE = Path(__file__).resolve().parent

# Function words carry structure, not affect — scoring "the" or "of"
# would drag every line toward the lexicon's neutral center.
STOPWORDS = frozenset(
    """a an and are as at be but by for from had has he her his i if in is it
    its me my no nor not of on or our she so that the thee thou thy to was we
    were what when where which who will with ye you your""".split()
)


def load_lexicon(path: Path) -> dict[str, tuple[float, float]]:
    """word -> (valence, arousal), rescaled to [0, 1] if the file is v2.1."""
    lex: dict[str, tuple[float, float]] = {}
    with path.open(encoding="utf-8") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 3 or " " in parts[0]:
                continue  # malformed, or a multi-word entry we can never match
            try:
                v, a = float(parts[1]), float(parts[2])
            except ValueError:
                continue  # header row
            lex[parts[0].lower()] = (v, a)
    if lex and min(min(v, a) for v, a in lex.values()) < 0:
        lex = {w: ((v + 1) / 2, (a + 1) / 2) for w, (v, a) in lex.items()}
    return lex


def score_line(text: str, lex: dict) -> tuple[float, float] | None:
    """
    Mean VAD over content words. Returns None if fewer than 2 words hit
    the lexicon — an unscoreable line is worse than a missing one, since
    a bogus neutral score would pollute the mood space.
    """
    words = [w for w in WORD_RE.findall(text.lower()) if w not in STOPWORDS]
    hits = [lex[w] for w in words if w in lex]
    if len(hits) < 2:
        return None
    v = sum(h[0] for h in hits) / len(hits)
    a = sum(h[1] for h in hits) / len(hits)
    return round(v, 3), round(a, 3)


def acceptable(line: str) -> bool:
    """Filter fragments and run-ons; 3–14 words reads well as one draw."""
    n = len(line.split())
    return 3 <= n <= 14 and not line.isupper()


def fetch_authors(limit: int) -> list[str]:
    resp = requests.get(f"{POETRYDB}/author", timeout=30)
    resp.raise_for_status()
    return resp.json()["authors"][:limit]


def fetch_poems(author: str) -> list[dict]:
    resp = requests.get(f"{POETRYDB}/author/{author}", timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def insert_line(cur, author: str, poem: str, text: str, v: float, a: float) -> bool:
    """Idempotent insert of one line; True if it was new."""
    cur.execute(
        "INSERT INTO authors (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
        (author,),
    )
    cur.execute("SELECT id FROM authors WHERE name = %s", (author,))
    author_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO poems (author_id, title) VALUES (%s, %s)
           ON CONFLICT (author_id, title) DO NOTHING""",
        (author_id, poem),
    )
    cur.execute(
        "SELECT id FROM poems WHERE author_id = %s AND title = %s",
        (author_id, poem),
    )
    poem_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO lines (poem_id, text, text_norm, valence, arousal)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (text_norm) DO NOTHING""",
        (poem_id, text, text.lower(), v, a),
    )
    return cur.rowcount == 1


def write_meta(cur, source: str) -> str:
    """Content hash over the line set; recall's corpus identity (§5.4)."""
    cur.execute("SELECT text_norm FROM lines ORDER BY text_norm")
    digest = hashlib.sha256()
    for (norm,) in cur.fetchall():
        digest.update(norm.encode("utf-8"))
        digest.update(b"\n")
    version = f"sha256:{digest.hexdigest()[:16]}"
    for key, value in (
        ("version", version),
        ("built_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        ("source", source),
    ):
        cur.execute(
            """INSERT INTO corpus_meta (key, value) VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (key, value),
        )
    return version


def ingest_sample(cur) -> int:
    data = json.loads((HERE / "sample-corpus.json").read_text(encoding="utf-8"))
    new = 0
    for line in data["lines"]:
        new += insert_line(cur, line["a"], line["p"], line["t"], line["v"], line["r"])
    return new


def ingest_poetrydb(cur, lexicon: Path, max_authors: int, max_lines: int) -> int:
    if not lexicon.exists():
        print(f"error: lexicon not found at {lexicon}", file=sys.stderr)
        print("       see the module docstring for the download link", file=sys.stderr)
        raise SystemExit(1)
    lex = load_lexicon(lexicon)
    print(f"lexicon: {len(lex)} words")

    authors = fetch_authors(max_authors)
    print(f"authors: {len(authors)}")

    new = 0
    for author in authors:
        try:
            poems = fetch_poems(author)
        except requests.RequestException as exc:
            print(f"  skip {author}: {exc}", file=sys.stderr)
            continue
        for poem in poems:
            kept = 0
            for text in poem.get("lines", []):
                text = text.strip()
                if not acceptable(text):
                    continue
                scored = score_line(text, lex)
                if scored is None:
                    continue
                if insert_line(cur, author, poem["title"], text, *scored):
                    new += 1
                    kept += 1
                if kept >= max_lines:
                    break
        time.sleep(0.3)  # be polite to a free API
        print(f"  {author}: {new} new lines so far")
    return new


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--lexicon",
        type=Path,
        default=HERE / "NRC-VAD-Lexicon-v2.1" / "NRC-VAD-Lexicon-v2.1.txt",
    )
    ap.add_argument("--max-authors", type=int, default=40)
    ap.add_argument("--max-lines-per-poem", type=int, default=12)
    ap.add_argument("--sample", action="store_true",
                    help="load the bundled sample corpus instead of PoetryDB")
    ap.add_argument("--wipe", action="store_true",
                    help="truncate all corpus tables before ingesting")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 1

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute((HERE / "schema.sql").read_text(encoding="utf-8"))
        if args.wipe:
            cur.execute("TRUNCATE lines, poems, authors, corpus_meta")
            print("wiped existing corpus")
        if args.sample:
            new = ingest_sample(cur)
            source = "bundled sample"
        else:
            new = ingest_poetrydb(
                cur, args.lexicon, args.max_authors, args.max_lines_per_poem
            )
            source = "PoetryDB + NRC-VAD v2.1"
        version = write_meta(cur, source)
        cur.execute("SELECT count(*) FROM lines")
        total = cur.fetchone()[0]
        conn.commit()

    print(f"done: {new} new lines, {total} total, corpus {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
