/**
 * moodgraph.js — the mood constellation.
 *
 * Emotions are anchored at their (approximate) coordinates in Russell's
 * circumplex: x = valence, y = arousal, both in [0, 1]. Clicking a star
 * cycles its activation weight 0 → 1 → 2 → 3 → 0. The target mood is the
 * activation-weighted centroid of the anchors — literally one neuron's
 * weighted sum, which is why the graph looks (honestly) neural.
 */

const EMOTIONS = [
  { name: "joy",        v: 0.85, r: 0.75, color: "#e6c15c" },
  { name: "serenity",   v: 0.80, r: 0.20, color: "#5cc9a7" },
  { name: "tenderness", v: 0.72, r: 0.45, color: "#7fd1c0" },
  { name: "awe",        v: 0.60, r: 0.85, color: "#9a8ff0" },
  { name: "melancholy", v: 0.22, r: 0.22, color: "#6f7bd9" },
  { name: "dread",      v: 0.18, r: 0.55, color: "#8f6fb8" },
  { name: "rage",       v: 0.12, r: 0.88, color: "#d96f6f" },
];

const W = 400, H = 340;           // svg viewBox
const PAD = 46;                    // keep stars off the edges
const NS = "http://www.w3.org/2000/svg";

/** valence/arousal [0,1] → svg pixel coords (arousal grows upward). */
const px = (v) => PAD + v * (W - 2 * PAD);
const py = (r) => H - PAD - r * (H - 2 * PAD);

export function createMoodGraph(svgEl, onChange) {
  // weight per emotion, index-aligned with EMOTIONS
  const weights = EMOTIONS.map(() => 1);

  function target() {
    const total = weights.reduce((s, w) => s + w, 0);
    if (total === 0) return { v: 0.5, r: 0.5 }; // neutral fallback
    let v = 0, r = 0;
    EMOTIONS.forEach((e, i) => { v += e.v * weights[i]; r += e.r * weights[i]; });
    return { v: v / total, r: r / total };
  }

  function render() {
    svgEl.innerHTML = "";
    const t = target();
    const cx = px(t.v), cy = py(t.r);

    // axes
    const mk = (tag, attrs, text) => {
      const el = document.createElementNS(NS, tag);
      for (const [k, val] of Object.entries(attrs)) el.setAttribute(k, val);
      if (text) el.textContent = text;
      svgEl.appendChild(el);
      return el;
    };
    mk("line", { class: "axis", x1: PAD, y1: H / 2, x2: W - PAD, y2: H / 2 });
    mk("line", { class: "axis", x1: W / 2, y1: PAD - 14, x2: W / 2, y2: H - PAD + 14 });
    mk("text", { class: "axis-label", x: W - PAD, y: H / 2 - 8, "text-anchor": "end" }, "valence +");
    mk("text", { class: "axis-label", x: W / 2 + 8, y: PAD - 4 }, "arousal +");

    // edges: node → centroid, thickness/opacity ∝ contribution
    const total = weights.reduce((s, w) => s + w, 0) || 1;
    EMOTIONS.forEach((e, i) => {
      if (weights[i] === 0) return;
      const share = weights[i] / total;
      mk("line", {
        class: "edge",
        x1: px(e.v), y1: py(e.r), x2: cx, y2: cy,
        "stroke-width": (0.5 + share * 4).toFixed(2),
        opacity: (0.15 + share * 0.6).toFixed(2),
      });
    });

    // stars: radius ∝ weight; click cycles 0→1→2→3→0
    EMOTIONS.forEach((e, i) => {
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "star");
      g.setAttribute("tabindex", "0");
      g.setAttribute("role", "button");
      g.setAttribute("aria-label", `${e.name}, weight ${weights[i]}`);

      const radius = 4 + weights[i] * 4;
      const halo = document.createElementNS(NS, "circle");
      halo.setAttribute("class", "halo");
      halo.setAttribute("cx", px(e.v)); halo.setAttribute("cy", py(e.r));
      halo.setAttribute("r", radius + 5);
      halo.setAttribute("stroke", e.color);
      halo.setAttribute("stroke-width", weights[i] ? "1" : "0");
      halo.setAttribute("opacity", "0.4");

      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("cx", px(e.v)); dot.setAttribute("cy", py(e.r));
      dot.setAttribute("r", radius);
      dot.setAttribute("fill", e.color);
      dot.setAttribute("opacity", weights[i] === 0 ? "0.25" : "1");

      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", px(e.v));
      label.setAttribute("y", py(e.r) + radius + 16);
      label.textContent = e.name;

      const cycle = () => {
        weights[i] = (weights[i] + 1) % 4;
        render();
        onChange(target());
      };
      g.addEventListener("click", cycle);
      g.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); cycle(); }
      });

      g.append(halo, dot, label);
      svgEl.appendChild(g);
    });

    // centroid ember — the target vector, made visible
    mk("circle", { class: "centroid-ring", cx, cy, r: 10 });
    mk("circle", { class: "centroid", cx, cy, r: 5 });
  }

  render();
  return { target };
}
