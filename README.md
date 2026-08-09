# Verse Lottery

A single-page poetry generator. Every line is drawn from a different poet,
sampled by emotional proximity to a mood you sculpt on an interactive
valence–arousal graph. No server, no LLM — a static corpus and a softmax.

## Architecture

```
pipeline/build_corpus.py   (runs once, Python)
  PoetryDB → split lines → NRC-VAD scoring → public/corpus.json

src/  (runs in the browser)
  moodgraph.js  emotion nodes → weighted centroid → target vector (v, a)
  sampler.js    P(line) ∝ exp(−‖line − target‖ / τ), authors w/o replacement
  main.js       state + event wiring + DOM rendering
```

Key ideas you will touch while working on this:

- **Precompute vs runtime**: all NLP happens in the build step; the client
  only does arithmetic over a static JSON.
- **Russell's circumplex**: emotions as points in valence × arousal space.
- **Softmax temperature**: the τ slider is literally the same knob as LLM
  sampling temperature — low τ = greedy/coherent, high τ = uniform/chaotic.
- **Stratified sampling without replacement**: the "lottery" rule — each
  draw excludes authors already used in the current poem.

## Run it

```bash
npm install
npm run dev        # Vite dev server, uses the bundled sample corpus
```

The repo ships with `public/corpus.json` containing ~24 hand-scored
public-domain lines so the app works immediately.

## Build the real corpus

1. Download the NRC-VAD lexicon (free for non-commercial use) from
   Saif Mohammad's site: https://saifmohammad.com/WebPages/nrc-vad.html
2. Place the lexicon text file at `pipeline/NRC-VAD-Lexicon.txt`
   (tab-separated: `word  valence  arousal  dominance`).
3. Run:

```bash
cd pipeline
pip install -r requirements.txt
python build_corpus.py --max-authors 40 --out ../public/corpus.json
```

## Deploy

Push to GitHub, import the repo in Vercel. Framework preset: **Vite**.
Build command `npm run build`, output directory `dist`. Nothing else —
it is a fully static site.

## Roadmap

- **v1**: curated retrieval (this scaffold).
- **v2**: "Remix" button — per-mood-quadrant Markov chains built by the
  pipeline (`--markov` flag reserved), generating novel lines client-side.
- **v3 (maybe)**: serverless `/api/generate` calling an LLM, conditioned
  on the same (v, a, τ) triple.
