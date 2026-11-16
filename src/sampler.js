/**
 * sampler.js — the mathematical heart of the app.
 *
 * Every line in the corpus carries a mood vector (v = valence, r = arousal),
 * both in [0, 1]. Given a target vector and a temperature τ, we sample:
 *
 *   P(line) ∝ exp( −‖line − target‖₂ / τ )
 *
 * This is a Boltzmann / softmax distribution over negative distance.
 * τ → 0   : argmin distance (greedy — always the closest-mood line)
 * τ → ∞   : uniform over the corpus (pure lottery)
 *
 * The "lottery rule": authors already used in the current poem are
 * excluded, so every line comes from a different voice. This is
 * stratified sampling without replacement at the author level.
 */

/** Euclidean distance in valence–arousal space. */
export function vadDistance(line, target) {
  return Math.hypot(line.v - target.v, line.r - target.r);
}

/**
 * Draw one line.
 * @param {Array}  lines       corpus lines: { t, a, p, v, r }
 * @param {Object} target      { v, r } from the mood graph centroid
 * @param {number} tau         softmax temperature
 * @param {Set}    usedAuthors authors to exclude (lottery constraint)
 * @returns {Object|null}      the sampled line
 */
export function sampleLine(lines, target, tau, usedAuthors) {
  // Lottery constraint: filter, but degrade gracefully if we exhaust
  // every author (small corpus, long poem).
  let pool = lines.filter((l) => !usedAuthors.has(l.a));
  if (pool.length === 0) pool = lines;
  if (pool.length === 0) return null;

  // Numerical-stability note: exp(−d/τ) with tiny τ underflows toward 0
  // for far lines — harmless here, but subtracting the min distance
  // first (the classic log-sum-exp trick) keeps weights well-scaled.
  const dists = pool.map((l) => vadDistance(l, target));
  const dMin = Math.min(...dists);
  const weights = dists.map((d) => Math.exp(-(d - dMin) / tau));

  // Inverse-transform sampling over the discrete distribution:
  // pick u ~ U(0, Σw), walk the cumulative sum until it crosses u.
  const total = weights.reduce((s, w) => s + w, 0);
  let u = Math.random() * total;
  for (let i = 0; i < pool.length; i++) {
    u -= weights[i];
    if (u <= 0) return pool[i];
  }
  return pool[pool.length - 1]; // float-rounding fallback
}
