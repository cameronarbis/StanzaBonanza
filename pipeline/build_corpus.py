#!/usr/bin/env python3
"""
build_corpus.py — the build-time half of Verse Lottery.

Pipeline:  PoetryDB  →  line splitting  →  NRC-VAD scoring  →  corpus.json

Run once (or whenever you want a bigger corpus); the frontend never
touches PoetryDB or the lexicon at runtime.

Usage:
    python build_corpus.py --max-authors 40 --out ../public/corpus.json

Prerequisite:
    Download the NRC-VAD lexicon (free for non-commercial use):
    https://saifmohammad.com/WebPages/nrc-vad.html
    Save as NRC-VAD-Lexicon.txt in this directory
    (tab-separated columns: word, valence, arousal, dominance).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

POETRYDB = "https://poetrydb.org"
WORD_RE = re.compile(r"[a-z']+")

# Function words carry structure, not affect — scoring "the" or "of"
# would drag every line toward the lexicon's neutral center.
STOPWORDS = frozenset(
    """a an and are as at be but by for from had has he her his i if in is it
    its me my no nor not of on or our she so that the thee thou thy to was we
    were what when where which who will with ye you your""".split()
)


def load_lexicon(path: Path) -> dict[str, tuple[float, float]]:
    """word -> (valence, arousal), both in [0, 1]."""
    lex: dict[str, tuple[float, float]] = {}
    with path.open(encoding="utf-8") as f:
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            word, v, a = parts[0], parts[1], parts[2]
            try:
                lex[word.lower()] = (float(v), float(a))
            except ValueError:
                continue  # header row or malformed line
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


def fetch_authors(limit: int) -> list[str]:
    resp = requests.get(f"{POETRYDB}/author", timeout=30)
    resp.raise_for_status()
    return resp.json()["authors"][:limit]


def fetch_poems(author: str) -> list[dict]:
    resp = requests.get(f"{POETRYDB}/author/{author}", timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def acceptable(line: str) -> bool:
    """Filter fragments and run-ons; 3–14 words reads well as one draw."""
    n = len(line.split())
    return 3 <= n <= 14 and not line.isupper()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lexicon", type=Path, default=Path("NRC-VAD-Lexicon.txt"))
    ap.add_argument("--out", type=Path, default=Path("../public/corpus.json"))
    ap.add_argument("--max-authors", type=int, default=40)
    ap.add_argument("--max-lines-per-poem", type=int, default=12)
    args = ap.parse_args()

    if not args.lexicon.exists():
        print(f"error: lexicon not found at {args.lexicon}", file=sys.stderr)
        print("       see the docstring for download instructions", file=sys.stderr)
        return 1

    lex = load_lexicon(args.lexicon)
    print(f"lexicon: {len(lex)} words")

    authors = fetch_authors(args.max_authors)
    print(f"authors: {len(authors)}")

    lines, seen = [], set()
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
                if not acceptable(text) or text.lower() in seen:
                    continue
                scored = score_line(text, lex)
                if scored is None:
                    continue
                v, a = scored
                lines.append(
                    {"t": text, "a": author, "p": poem["title"], "v": v, "r": a}
                )
                seen.add(text.lower())
                kept += 1
                if kept >= args.max_lines_per_poem:
                    break
        time.sleep(0.3)  # be polite to a free API
        print(f"  {author}: corpus now {len(lines)} lines")

    out = {
        "meta": {"source": "PoetryDB + NRC-VAD", "count": len(lines)},
        "lines": lines,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # separators kwarg strips whitespace — meaningful at 10⁴+ entries.
    args.out.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(lines)} lines → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
