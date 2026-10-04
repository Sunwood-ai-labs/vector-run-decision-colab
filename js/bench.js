import { createWorld, dangerLevel, ruleAction, scoreOf, step } from "./engine.js";
import { POLICY } from "./policy.js";
import { buildRequest, goldLabels, readDecision, scoreSample } from "./questions.js";

export function ruleDecide(world) {
  const action = ruleAction(world);
  const probabilities = { hold: 0, jump: 0, slide: 0, strike: 0 };
  probabilities[action] = 1;
  return {
    action,
    probabilities,
    commit: action !== "hold",
    danger: dangerLevel(world),
    confidence: 1,
    probeHits: null,
    probeTotal: 0,
    parsed: true,
    source: "rule",
  };
}

export function idleDecide() {
  return {
    action: "hold",
    probabilities: { hold: 1, jump: 0, slide: 0, strike: 0 },
    commit: false,
    danger: 0,
    confidence: 1,
    probeHits: null,
    probeTotal: 0,
    parsed: true,
    source: "idle",
  };
}

export function runEpisode(seed, decide, options = {}) {
  const world = createWorld(seed, options);
  const questionCount = options.questionCount ?? 3;
  const samples = [];
  while (!world.done) {
    let action = "hold";
    if (world.frame % POLICY.decisionEvery === 0) {
      const gold = goldLabels(world, questionCount);
      const started = now();
      const decision = decide(world, gold);
      const ms = now() - started;
      action = decision.action;
      samples.push({ gold, got: decision, ms, ...scoreSample(gold, decision) });
      world.telemetry = { ...decision, ms, gold };
    }
    step(world, action);
  }
  return summarizeEpisode(seed, world, samples);
}

export async function runEpisodeAsync(seed, decide, options = {}) {
  const world = createWorld(seed, options);
  const questionCount = options.questionCount ?? 3;
  const samples = [];
  while (!world.done) {
    let action = "hold";
    if (world.frame % POLICY.decisionEvery === 0) {
      const gold = goldLabels(world, questionCount);
      const started = now();
      const decision = await decide(world, gold);
      const ms = now() - started;
      action = decision.action;
      samples.push({ gold, got: decision, ms, ...scoreSample(gold, decision) });
      world.telemetry = { ...decision, ms, gold };
    }
    step(world, action);
    if (options.onFrame) options.onFrame(world);
  }
  return summarizeEpisode(seed, world, samples);
}

function now() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function summarizeEpisode(seed, world, samples) {
  const latency = samples.map((sample) => sample.ms).sort((a, b) => a - b);
  const mean = (values) => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0);
  const commits = samples.filter((sample) => sample.commitMatch != null);
  const dangers = samples.filter((sample) => sample.dangerError != null);
  const probes = samples.filter((sample) => sample.got.probeTotal > 0);
  const probeHits = probes.reduce((sum, sample) => sum + sample.got.probeHits, 0);
  const probeTotal = probes.reduce((sum, sample) => sum + sample.got.probeTotal, 0);
  return {
    seed,
    cleared: world.cleared,
    failed: world.failed,
    distance: Math.round(world.player.x),
    hits: world.player.hits,
    chips: world.player.chips,
    hearts: world.player.hearts,
    score: scoreOf(world),
    frames: world.frame,
    decisions: samples.length,
    actionAcc: mean(samples.map((sample) => (sample.actionMatch ? 1 : 0))),
    commitAcc: commits.length ? mean(commits.map((sample) => (sample.commitMatch ? 1 : 0))) : null,
    dangerMae: dangers.length ? mean(dangers.map((sample) => sample.dangerError)) : null,
    consistency: mean(
      samples
        .filter((sample) => sample.consistent != null)
        .map((sample) => (sample.consistent ? 1 : 0)),
    ),
    probeAcc: probeTotal ? probeHits / probeTotal : null,
    latencyMean: mean(latency),
    latencyP50: percentile(latency, 0.5),
    latencyP95: percentile(latency, 0.95),
    lastHit: world.lastHit,
    samples,
  };
}

function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * p) - 1);
  return sorted[Math.max(0, index)];
}

export function aggregate(rows) {
  const mean = (key) => {
    const values = rows.map((row) => row[key]).filter((value) => typeof value === "number");
    if (!values.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  };
  return {
    runs: rows.length,
    clearRate: rows.length ? rows.filter((row) => row.cleared).length / rows.length : 0,
    failRate: rows.filter((row) => row.failed).length / rows.length,
    distance: mean("distance"),
    hits: mean("hits"),
    chips: mean("chips"),
    score: mean("score"),
    actionAcc: mean("actionAcc"),
    commitAcc: mean("commitAcc"),
    dangerMae: mean("dangerMae"),
    consistency: mean("consistency"),
    probeAcc: mean("probeAcc"),
    latencyMean: mean("latencyMean"),
    latencyP95: mean("latencyP95"),
    decisions: mean("decisions"),
  };
}

export async function remoteDecide(endpoint, world, questionCount, model) {
  const request = buildRequest(world, questionCount);
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model: model || "decision-lane-mock",
      state: request.state,
      questions: request.questions,
    }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Decision endpoint ${response.status}: ${text.slice(0, 240)}`);
  }
  const payload = await response.json();
  payload.state = request.state;
  return { ...readDecision(payload), source: "remote", request };
}

export { buildRequest };
