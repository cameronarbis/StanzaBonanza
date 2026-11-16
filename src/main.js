/**
 * main.js — application shell.
 *
 * Deliberately framework-free: one state object, explicit event → state →
 * render flow. The sampling math lives server-side now (GET /api/poem);
 * this file holds only UI state — including the author lottery list and
 * the per-draw recall recipes (docs/DESIGN.md §5.4, §7).
 */
import { createMoodGraph } from "./moodgraph.js";

const state = {
  target: { v: 0.5, r: 0.5 },
  tau: 0.12,
  lines: [],            // { text, author, poem }
  draws: [],            // recall recipes: params echoed by each request
  corpusVersion: null,
  usedAuthors: new Set(),
};

const $ = (sel) => document.querySelector(sel);
const poemEl = $("#poem");

function showMessage(msg) {
  poemEl.innerHTML = "";
  const p = document.createElement("p");
  p.className = "poem-empty";
  p.textContent = msg;
  poemEl.appendChild(p);
}

async function fetchPoem(n, exclude) {
  const params = new URLSearchParams({
    v: state.target.v.toFixed(3),
    a: state.target.r.toFixed(3),
    tau: String(state.tau),
    n: String(n),
  });
  for (const author of exclude) params.append("exclude", author);

  const res = await fetch(`/api/poem?${params}`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    if (res.status === 429) {
      const wait = res.headers.get("Retry-After") ?? "a few";
      throw new Error(`The muse is rate-limited — try again in ${wait} seconds.`);
    }
    throw new Error(body?.detail ?? `request failed (${res.status})`);
  }
  return res.json();
}

function renderPoem() {
  poemEl.innerHTML = "";
  if (state.lines.length === 0) {
    showMessage("Sculpt a mood, then draw a line.");
    return;
  }
  for (const line of state.lines) {
    const p = document.createElement("p");
    p.className = "poem-line";
    p.textContent = line.text;
    const attr = document.createElement("p");
    attr.className = "poem-attr";
    attr.textContent = `— ${line.author}, “${line.poem}”`;
    poemEl.append(p, attr);
  }
  poemEl.scrollTop = poemEl.scrollHeight;
}

async function drawLine() {
  try {
    const poem = await fetchPoem(1, [...state.usedAuthors]);
    if (poem.lines.length === 0) return;
    const line = poem.lines[0];
    // The server resets the lottery when every author is used; mirror
    // that by restarting our list when a repeat comes back.
    if (state.usedAuthors.has(line.author)) state.usedAuthors.clear();
    state.usedAuthors.add(line.author);
    state.lines.push(line);
    state.draws.push(poem.params);
    state.corpusVersion = poem.corpus_version;
    renderPoem();
  } catch (err) {
    showMessage(err.message);
  }
}

async function wholePoem() {
  try {
    const poem = await fetchPoem(6, []);
    state.lines = poem.lines;
    state.draws = [poem.params];
    state.corpusVersion = poem.corpus_version;
    state.usedAuthors = new Set(poem.lines.map((l) => l.author));
    renderPoem();
  } catch (err) {
    showMessage(err.message);
  }
}

function clearPoem() {
  state.lines = [];
  state.draws = [];
  state.usedAuthors.clear();
  renderPoem();
}

function poemText() {
  return state.lines
    .map((l) => `${l.text}\n    — ${l.author}, “${l.poem}”`)
    .join("\n\n");
}

async function copyPoem() {
  if (state.lines.length === 0) return;
  await navigator.clipboard.writeText(poemText());
  const btn = $("#btn-copy");
  const label = btn.textContent;
  btn.textContent = "Copied";
  setTimeout(() => { btn.textContent = label; }, 1200);
}

function download(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadTxt() {
  if (state.lines.length === 0) return;
  download("poem.txt", `${poemText()}\n\nStanzaBonanza · ${state.corpusVersion}\n`,
    "text/plain");
}

function downloadJson() {
  if (state.lines.length === 0) return;
  // The recall recipe (docs/DESIGN.md §5.4): replaying `draws` against
  // the same corpus_version regenerates this exact poem.
  const payload = {
    app: "StanzaBonanza",
    corpus_version: state.corpusVersion,
    draws: state.draws,
    lines: state.lines,
  };
  download("poem.json", JSON.stringify(payload, null, 2), "application/json");
}

async function loadCorpusNote() {
  try {
    const res = await fetch("/api/corpus");
    if (!res.ok) return;
    const info = await res.json();
    $("#corpus-note").textContent =
      `${info.lines} lines from ${info.authors} poets`;
  } catch {
    // The note is decoration; poem requests surface real errors.
  }
}

function init() {
  const graph = createMoodGraph($("#mood-graph"), (t) => { state.target = t; });
  state.target = graph.target();

  $("#btn-draw").addEventListener("click", drawLine);
  $("#btn-whole").addEventListener("click", wholePoem);
  $("#btn-clear").addEventListener("click", clearPoem);
  $("#btn-copy").addEventListener("click", copyPoem);
  $("#btn-txt").addEventListener("click", downloadTxt);
  $("#btn-json").addEventListener("click", downloadJson);
  $("#tau").addEventListener("input", (e) => {
    state.tau = parseFloat(e.target.value);
    $("#tau-out").textContent = state.tau.toFixed(2);
  });
  // #btn-remix stays disabled until v2 (per-mood Markov chains).

  loadCorpusNote();
}

init();
