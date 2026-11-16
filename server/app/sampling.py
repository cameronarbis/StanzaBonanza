"""
The draw: softmax sampling over emotional distance, in SQL.

P(line) ∝ exp(−‖line − target‖₂ / τ) is sampled via the Gumbel-max
trick: picking the row minimizing  d + τ·ln(−ln(u)),  u ~ U(0,1), is
exactly one draw from that distribution — stable at tiny τ (no exp
underflow) and never materializes the corpus in app memory
(docs/DESIGN.md §5.3).
"""

from .schemas import PoemLine, PoemQuery

# greatest(random(), 1e-300): random() may return exactly 0, and
# ln(-ln(0)) is undefined.
DRAW_SQL = """
SELECT l.text, l.valence, l.arousal, a.name AS author, p.title AS poem
FROM lines l
JOIN poems p   ON p.id = l.poem_id
JOIN authors a ON a.id = p.author_id
WHERE NOT (a.name = ANY(%(exclude)s))
ORDER BY sqrt(power(l.valence - %(v)s, 2) + power(l.arousal - %(a)s, 2))
         + %(tau)s * ln(-ln(greatest(random(), 1e-300)))
LIMIT 1
"""


def draw_poem(conn, q: PoemQuery, seed: int) -> list[PoemLine]:
    """
    n sequential draws in one transaction, each excluding authors already
    drawn — the lottery rule. setseed makes the whole sequence a pure
    function of (corpus, params, seed): recall without storage (§5.4).
    """
    lines: list[PoemLine] = []
    with conn.transaction():
        conn.execute("SELECT setseed(%s)", (seed / 2**31,))
        exclude = list(q.exclude)
        for _ in range(q.n):
            params = {"v": q.v, "a": q.a, "tau": q.tau, "exclude": exclude}
            row = conn.execute(DRAW_SQL, params).fetchone()
            if row is None and len(exclude) > len(q.exclude):
                # Pool exhausted (small corpus, long poem): restart the
                # author lottery — but only for authors drawn here; the
                # request's explicit exclusions are a contract.
                exclude = list(q.exclude)
                row = conn.execute(DRAW_SQL, {**params, "exclude": exclude}).fetchone()
            if row is None:
                break  # nothing drawable (empty corpus, or all excluded)
            lines.append(PoemLine(**row))
            exclude.append(row["author"])
    return lines
