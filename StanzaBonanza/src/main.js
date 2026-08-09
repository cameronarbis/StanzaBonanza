/**
 * main.js — application shell.
 *
 * Deliberately framework-free: one state object, explicit event → state →
 * render flow. When you later read React docs, you'll recognize that this
 * file IS what useState + useEffect abstract away.
 */
import { sampleLine } from "./sampler.js";
import { createMoodGraph } from "./moodgraph.js";

const state = {
  corpus: [],              // loaded from /corpus.json
  target: { v: 0.5, r: 0.5 },
  tau: 0.12,
  usedAuthors: new Set(),  // the lottery constraint, reset on Clear
};

const $ = (sel) => document.querySelector(sel);
const poemEl = $("#poem");

async function loadCorpus() {
  const res = await fetch("/corpus.json");
  if (!res.ok) throw new Error(`corpus fetch failed: ${res.status}`);
  const data = await res.json();
  state.corpus = data.lines;
  console.info(`corpus loaded: ${state.corpus.length} lines`);
}

function drawLine() {
  const line = sampleLine(state.corpus, state.target, state.tau, state.usedAuthors);
  if (!line) return;

  // If the pool was exhausted and the sampler fell back to the full
  // corpus, restart the author lottery for the next round.
  if (state.usedAuthors.has(line.a)) state.usedAuthors.clear();
  state.usedAuthors.add(line.a);

  poemEl.querySelector(".poem-empty")?.remove();

  const p = document.createElement("p");
  p.className = "poem-line";
  p.textContent = line.t;

  const attr = document.createElement("p");
  attr.className = "poem-attr";
  attr.textContent = `— ${line.a}, “${line.p}”`;

  poemEl.append(p, attr);
  poemEl.scrollTop = poemEl.scrollHeight;
}

function clearPoem() {
  state.usedAuthors.clear();
  poemEl.innerHTML = '<p class="poem-empty">Sculpt a mood, then draw a line.</p>';
}

async function init() {
  await loadCorpus();

  const graph = createMoodGraph($("#mood-graph"), (t) => { state.target = t; });
  state.target = graph.target();

  $("#btn-draw").addEventListener("click", drawLine);
  $("#btn-clear").addEventListener("click", clearPoem);
  $("#tau").addEventListener("input", (e) => {
    state.tau = parseFloat(e.target.value);
    $("#tau-out").textContent = state.tau.toFixed(2);
  });
  // #btn-remix stays disabled until v2 (per-mood Markov chains).
}

init().catch((err) => {
  poemEl.innerHTML = `<p class="poem-empty">Could not load the corpus — ${err.message}</p>`;
});
