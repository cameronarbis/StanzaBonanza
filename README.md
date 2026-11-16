# StanzaBonanza (Verse Lottery)

A poetry generator. Every line is drawn from a different poet, sampled
by emotional proximity to a mood you sculpt on an interactive
valence–arousal graph. v1 is a client/server system: a Python ingestion
pipeline, Postgres, and a FastAPI sampling API serving a static
frontend. Full design: [docs/DESIGN.md](docs/DESIGN.md).

## Architecture

```
pipeline/ingest.py   (manual, Python)
  PoetryDB → split lines → NRC-VAD scoring → Postgres

server/  (FastAPI)
  GET /api/poem    softmax sampling in SQL, one author per line,
                   JSON or text/plain via content negotiation
  GET /api/corpus  corpus counts + version
  GET /api/health  liveness + db check

src/  (browser)
  moodgraph.js  emotion nodes → weighted centroid → target vector (v, a)
  main.js       UI state + API calls + recall recipes
```

Key ideas you will touch while working on this:

- **Russell's circumplex**: emotions as points in valence × arousal space.
- **Softmax temperature**: the τ slider is the same knob as LLM sampling
  temperature — low τ = greedy/coherent, high τ = uniform/chaotic. The
  draw happens in SQL via the Gumbel-max trick.
- **The lottery rule**: authors already used are excluded per poem —
  stratified sampling without replacement, enforced server-side.
- **Recall without storage**: every poem is a pure function of
  (corpus version, mood params, seed); the JSON download is a recipe
  that regenerates it exactly.

## Run it locally

You need Postgres, Python 3.12+, and Node.

```bash
# 1. database
createdb stanzabonanza

# 2. server
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABASE_URL=postgresql://localhost/stanzabonanza

# 3. corpus — bundled 26-line sample, no network needed
.venv/bin/python ../pipeline/ingest.py --sample

# 4. API
.venv/bin/uvicorn app.main:app --port 8000

# 5. frontend (second terminal; Vite proxies /api to :8000)
npm install
npm run dev
```

## Build the real corpus

1. Download the NRC-VAD lexicon v2.1 (free for non-commercial use) from
   Saif Mohammad's site: https://saifmohammad.com/WebPages/nrc-vad.html
   and unpack it at `pipeline/NRC-VAD-Lexicon-v2.1/`. It is deliberately
   not committed — its terms direct users to the source.
2. Run:

```bash
cd pipeline
pip install -r requirements.txt
DATABASE_URL=postgresql://... python ingest.py --max-authors 40
```

The script is polite to PoetryDB (rate-limited, run manually) and
idempotent — re-running converges instead of duplicating.

## Tests

```bash
cd server
.venv/bin/pip install pytest httpx requests
.venv/bin/python -m pytest tests/
```

Tests spin up a throwaway real Postgres cluster (`initdb` must be on
PATH) and never call PoetryDB.

## Deploy (Railway)

One service plus a Postgres plugin:

- Build: `npm install && npm run build` (FastAPI serves `dist/`),
  then `pip install -r server/requirements.txt`.
- Start: `cd server && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/api/health`.
- Env: `DATABASE_URL` (injected by the plugin; the app uses the private
  URL), `ALLOWED_ORIGINS` empty in production.
- Ingest from your machine via the database's **public TCP proxy** URL.

## Roadmap

- **v1**: curated retrieval behind an API you operate (this).
- **v2**: "Remix" — per-mood-quadrant Markov chains built by the
  pipeline, generating novel lines.
- **v3 (maybe)**: `/api/generate` calling an LLM, conditioned on the
  same (v, a, τ) triple.
