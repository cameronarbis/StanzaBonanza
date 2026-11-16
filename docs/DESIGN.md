# StanzaBonanza v1 — Design Document

Status: **approved 2026-11-15** — open questions resolved by the owner, see §10.
Scope: v1 as shaped — client-side scaffold becomes a client/server system.
Audience: implementers; reviewed by a second agent (◇ marks its findings).

> 2026-11-15 merge note: a parallel design effort for the same v1 was
> retired in favor of this document (owner's decision). Its
> builder-review findings are merged in below, marked ◇. The owner's
> stated intent, for the record: the project exists so they can **learn
> to design, build, and operate an API** — including validation, error
> handling, rate limiting, and security — with the poetry generator as
> the vehicle. Where this design offers a choice, prefer the option
> that teaches the most while staying proportionate for a hobby-scale,
> non-commercial service.

## 1. Summary

v1 turns the static Verse Lottery scaffold into a three-part system:

1. **Ingestion** (`pipeline/ingest.py`) — the existing PoetryDB → line
   splitting → NRC-VAD scoring pipeline, retargeted to load a Postgres
   database instead of writing `corpus.json`. Run manually, politely;
   PoetryDB is never touched by user traffic.
2. **API server** (`server/`, FastAPI) — the client sends mood parameters
   (valence, arousal, temperature, line count); the server runs the
   sampling — softmax over emotional distance, one author per line — and
   returns the poem with attributions. Nothing is stored per user; every
   request is a read.
3. **Frontend** (`src/`, unchanged UI) — the moodgraph stays exactly as it
   is, rewired to call the API instead of loading a local JSON.

One Railway deployment: FastAPI serves both the API and the built
frontend, with Postgres alongside. The unglamorous parts are first-class:
Pydantic validation, honest error responses, per-client rate limiting,
CORS locked down.

## 2. Goals and non-goals

**Goals**

- Server-side sampling with the exact semantics of today's `sampler.js`:
  P(line) ∝ exp(−‖line − target‖₂ / τ), authors drawn without replacement.
- A stateless, read-only API: no sessions, no per-user storage.
- Exact poem recall without storage (see §5.4 — seeded determinism).
- One poem resource, two representations: `application/json` (the data)
  and `text/plain` (the readable poem) via content negotiation.
- Production manners: validation, error shape, rate limiting, CORS.

**Non-goals (v1)**

- No accounts, no auth, no saved poems.
- No v2 Markov "Remix", no LLM endpoint (roadmap unchanged).
- No admin API — ingestion is a manually run script with DB credentials.

## 3. Repository layout (target)

```
StanzaBonanza/
  docs/DESIGN.md          this document
  pipeline/ingest.py      PoetryDB → NRC-VAD scoring → Postgres (manual)
  server/
    app/
      main.py             FastAPI app factory, static mount, middleware
      api.py              routes
      schemas.py          Pydantic request/response models
      sampling.py         the draw: SQL weighted sampling, lottery rule
      db.py               connection pool, queries
      settings.py         env-driven config (pydantic-settings)
    tests/
    requirements.txt
  src/                    frontend (moodgraph.js stays; sampler.js retires)
  public/                 static assets (corpus.json deleted after cutover)
```

`src/sampler.js` is deleted once the API is live — the math moves server-side
and two implementations of the same distribution is a bug factory.

## 4. Data model (Postgres)

Normalized to mirror the domain: an author writes poems, a poem has lines.

```sql
CREATE TABLE authors (
  id   SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE poems (
  id        SERIAL PRIMARY KEY,
  author_id INTEGER NOT NULL REFERENCES authors(id),
  title     TEXT NOT NULL,
  UNIQUE (author_id, title)
);

CREATE TABLE lines (
  id        SERIAL PRIMARY KEY,
  poem_id   INTEGER NOT NULL REFERENCES poems(id),
  text      TEXT NOT NULL,
  text_norm TEXT NOT NULL UNIQUE,   -- lowercased; cross-corpus dedupe
  valence   REAL NOT NULL CHECK (valence BETWEEN 0 AND 1),
  arousal   REAL NOT NULL CHECK (arousal BETWEEN 0 AND 1)
);

CREATE TABLE corpus_meta (
  key   TEXT PRIMARY KEY,           -- 'version', 'built_at', 'source'
  value TEXT NOT NULL
);
```

`corpus_meta.version` is a content hash over the line set, written by
ingestion. It is returned with every poem so a recalled poem can detect
that the corpus has changed underneath it (§5.4).

The CHECK constraints are boundary discipline: scores outside [0, 1] are a
pipeline bug and should fail loudly at insert, not skew sampling silently.

## 5. API design

### 5.1 The poem resource

One endpoint. A poem is a **pure function of its parameters** — corpus
version, mood target, temperature, line count, seed, exclusions — so it
is addressed by `GET` with query parameters: cacheable, shareable,
bookmarkable, honest about being a read.

```
GET /api/poem?v=0.62&a=0.55&tau=0.12&n=6&seed=843021&exclude=Emily+Dickinson
```

| param     | type    | default  | constraints                  |
|-----------|---------|----------|------------------------------|
| `v`       | float   | required | 0 ≤ v ≤ 1 (target valence)   |
| `a`       | float   | required | 0 ≤ a ≤ 1 (target arousal)   |
| `tau`     | float   | 0.12     | 0.01 ≤ tau ≤ 2.0             |
| `n`       | int     | 1        | 1 ≤ n ≤ 14                   |
| `seed`    | int     | random   | 0 ≤ seed < 2³¹; echoed back  |
| `exclude` | string… | none     | repeatable; ≤ 40 authors     |

`n=1` plus `exclude` is how the existing line-by-line "Draw" button keeps
working: the client holds its own used-author list (pure UI state) and
passes it back, so the server stays stateless while the lottery rule
spans a whole poem. `n>1` draws a complete poem in one request, applying
the same rule internally.

**JSON representation** (`Accept: application/json`, the default):

```json
{
  "params": { "v": 0.62, "a": 0.55, "tau": 0.12, "n": 6, "seed": 843021,
              "exclude": [] },
  "corpus_version": "sha256:ab12…",
  "lines": [
    { "text": "…", "author": "…", "poem": "…", "valence": 0.61, "arousal": 0.57 }
  ]
}
```

**Plain-text representation** (`Accept: text/plain`):

```
A poem of the hour

<line>
    — Author, “Poem Title”
…

StanzaBonanza · v=0.62 a=0.55 τ=0.12 seed=843021
```

Content negotiation via the `Accept` header is the primary mechanism.
`?format=text` is also accepted as an override, because an
`<a download>` link cannot set request headers — a real-world concession
worth having in the codebase on purpose. `Vary: Accept` is set so caches
behave.

### 5.2 Supporting endpoints

```
GET /api/health        → 200 {"status":"ok","db":true}
GET /api/corpus        → counts, author count, corpus_version, built_at
```

`/api/corpus` lets the frontend show "N lines from M poets" and lets a
recalled poem check whether its corpus_version still matches.

### 5.3 Sampling, server-side

The draw happens **in SQL**, one query per line, via the Gumbel-max form
of weighted sampling. Softmax sampling with weight w = exp(−d/τ) is
equivalent to minimizing `d + τ·ln(−ln(u))` with u ~ U(0,1) per row:

```sql
SELECT l.id, l.text, l.valence, l.arousal, a.name AS author, p.title
FROM lines l
JOIN poems p   ON p.id = l.poem_id
JOIN authors a ON a.id = p.author_id
WHERE a.name <> ALL(:exclude)
ORDER BY sqrt((l.valence - :v)^2 + (l.arousal - :a)^2)
         + :tau * ln(-ln(random()))
LIMIT 1;
```

This is numerically stable at tiny τ (no exp underflow, so the
log-sum-exp shift in `sampler.js` is no longer needed), it never
materializes the corpus in application memory, and it keeps Postgres as
the single source of truth. For n lines, the server runs n draws in one
transaction, appending each drawn author to the exclusion set — the
lottery rule. If the pool empties mid-poem (small corpus, long poem), the
exclusion set resets, mirroring today's client behavior.

### 5.4 Exact recall without storage

"Nothing is ever stored per user" and "recall this exact poem" coexist
through determinism: each request runs `SELECT setseed(:derived_seed)` at
the top of its transaction, so the same (corpus_version, v, a, tau, n,
seed, exclude) always yields the same poem. The JSON representation is
therefore a complete recipe for its own regeneration — download the JSON,
and the URL to re-fetch the identical poem (or its text/plain twin) can
be reconstructed from `params`. If the corpus has been re-ingested since,
corpus_version won't match and the API can't promise the same poem; the
response is still valid, just a new draw, and the client may say so.

◇ **Recall wrinkle (from builder review):** a poem built line by line is
not one parameter set — the user can move the mood graph and τ between
draws, so no single `GET /api/poem?n=…&seed=…` reproduces what's on
screen. Recall for an accumulated poem is therefore the **sequence** of
per-draw parameter sets: the client records each draw's
`{v, a, tau, seed, exclude}` (plus `corpus_version`), and the JSON
download is built client-side as that array alongside the lines.
Replaying the sequence of `n=1` calls regenerates the poem exactly. The
single-URL recall of this section applies as-is only to poems generated
in one request (`n>1` with fixed parameters).

### 5.5 Validation and errors

All query parameters are a single Pydantic model (FastAPI `Depends`),
so range violations are rejected before any code runs. Error responses
use one shape everywhere, loosely following RFC 9457:

```json
{ "error": "validation_error",
  "detail": "tau must be between 0.01 and 2.0",
  "status": 422 }
```

| status | when                                                  |
|--------|-------------------------------------------------------|
| 422    | parameter out of range / wrong type                   |
| 404    | unknown route (JSON body, not HTML)                   |
| 429    | rate limit exceeded; includes `Retry-After` header    |
| 503    | database unreachable (health check fails loudly too)  |

No stack traces, no FastAPI default HTML errors in production. "Honest"
means: the message states what was wrong with the request, not what broke
inside the server.

### 5.6 Rate limiting

Per-client token bucket keyed by IP, in-process (no Redis — one Railway
instance, and the limit is a courtesy fence, not a security boundary).
Proposed: **30 requests/minute per IP, burst 10**. Railway sits behind a
proxy, so the client IP comes from the rightmost trusted hop of
`X-Forwarded-For` — never the leftmost, which the client controls.
Implementation: `slowapi`, or ~40 lines of middleware if the dependency
pulls more than it carries.

### 5.7 CORS

The frontend is served by the same FastAPI app, so production needs **no
cross-origin allowance at all** — the API refuses cross-origin browser
calls by default. The one exception is development, where Vite runs on
its own port: `ALLOWED_ORIGINS` (env var) defaults to empty and is set to
`http://localhost:5173` locally. Locked down means exactly that list, no
`*`, credentials disallowed.

## 6. Ingestion

`pipeline/ingest.py` evolves from `build_corpus.py`, keeping its filters
(3–14 words, ≥2 lexicon hits, dedupe, 0.3 s sleeps between authors) and
changing the sink:

- Writes authors/poems/lines with `INSERT … ON CONFLICT DO NOTHING`
  (idempotent — re-running converges instead of duplicating).
- Computes and writes `corpus_meta.version` (hash over sorted
  `text_norm` set) and `built_at` at the end of each run.
- Takes `DATABASE_URL` from the environment; same flags as today
  (`--max-authors`, `--max-lines-per-poem`) plus `--wipe` to rebuild
  from scratch.
- Runs manually from a developer machine (or a Railway one-off job),
  never from request handlers.
- ◇ **Connectivity (from builder review):** Railway's private network is
  unreachable from a laptop, so local ingestion connects via Railway's
  credentialed **public TCP proxy** for Postgres — the standard Railway
  pattern. The app itself keeps using the private-network
  `DATABASE_URL`; the proxy URL and password live only in the owner's
  local `.env`, never in the repo.

## 7. Frontend changes

Minimal, by design:

- `loadCorpus()` and `sampler.js` go away.
- "Draw a line" → `GET /api/poem?n=1&v=…&a=…&tau=…&exclude=…` with the
  client's running author list; response appends one line, exactly the
  current UX.
- "Clear" resets the client-side author list, as now.
- New "Whole poem" button: one `GET /api/poem?n=6&…` request; the
  response replaces the current poem and its URL is the recall handle.
- New "Copy" button: client-side clipboard write of the poem text. Free.
- New "Download" control: for a poem accumulated line by line, both
  `.txt` and `.json` are built **client-side** from the page's own state
  (◇ see the recall wrinkle in §5.4 — no single URL reproduces a
  multi-draw poem). The JSON carries the per-draw parameter sets as the
  recall recipe. The `<a download href="/api/poem?…&format=text">` form
  remains correct for single-request poems.
- Errors surface in the existing `.poem-empty` slot ("The muse is
  rate-limited — try again in a moment" beats a silent failure).

## 8. Deployment (Railway)

- One service: `uvicorn app.main:app`, `PORT` from Railway.
- Build: `npm run build`, then FastAPI mounts `dist/` via `StaticFiles`
  (API routes under `/api/*` take precedence; `/` serves the SPA).
- Postgres: Railway plugin; `DATABASE_URL` injected.
- Config via env only: `DATABASE_URL`, `ALLOWED_ORIGINS`, `RATE_LIMIT`.
- Health check path: `/api/health`.
- ◇ **Free tier is the ceiling for now** (owner's words: "free tier is
  fine for now"). The SQL-side sampling helps here — no in-process
  corpus cache eating the small memory allowance. Keep the corpus
  modest (`--max-authors` is the knob); outgrowing the free plan later
  is an ops change, not a redesign.

## 9. Testing

- **Sampling**: against a seeded test corpus, assert (a) determinism per
  seed, (b) the lottery rule (no author repeats within a poem), (c) the
  distribution — at low τ the nearest line dominates over many draws, at
  high τ draws approach uniform (χ² sanity bound, not exact).
- **API**: parameter boundary tests (both sides of every limit), content
  negotiation (`Accept` and `?format`), error shape, 429 behavior.
- **Ingestion**: idempotency — ingest a fixture twice, count rows once.
- PoetryDB is never called in tests; fixtures only.

## 10. Resolved questions (owner decisions, 2026-11-15)

1. **Draw UX — both.** Line-by-line "Draw" stays as today (`n=1` + client
   exclusion list), and a "Whole poem" button fetches `n=6` in one
   request — which also gets the clean single-URL recall of §5.4.
2. **Recall via seed — accepted**, with the ◇ wrinkle in §5.4: client-built
   downloads for accumulated poems, single-URL recall for one-shot poems.
3. **Rate limit — 30 req/min per IP, burst 10**, revisit if it annoys.
4. **Repo layout — flatten** to the repo root in a dedicated commit before
   feature work.
5. **Content negotiation — keep** (it is exactly the kind of API lesson
   this project exists for).
6. ◇ **Lexicon — untrack going forward**: `git rm --cached` the
   `pipeline/NRC-VAD-Lexicon-v2.1/` directory, add it to `.gitignore`,
   keep the local copy; no history rewrite. The README's download link
   remains the way to obtain it.

## 11. Decisions already taken (for the record)

- `GET` over `POST` for poems: a poem is a deterministic read, and GET
  buys cacheability, shareable recall URLs, and honest semantics.
- Sampling in SQL (Gumbel-max) over in-memory Python: single source of
  truth, stable at tiny τ, no corpus cache to invalidate after ingestion.
- One endpoint for lines and poems (`n` parameter) over separate
  `/line` and `/poem` routes: same resource, same math, less surface.
- In-process rate limiting over Redis: one instance, courtesy fence.
- `?format=` override alongside `Accept`: download links can't set headers.
