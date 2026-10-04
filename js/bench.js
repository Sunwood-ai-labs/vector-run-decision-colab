import { createWorld, dangerLevel, ruleAction, scoreOf, step } from "./engine.js";
import { POLICY } from "./policy.js";
import { buildRequest, goldLabels, readDecision, scoreSample } from "./questions.js";

export function ruleDecide(world, { questionCount = 3 } = {}) {
  const action = ruleAction(world);
  const probabilities = { hold: 0, jump: 0, slide: 0, strike: 0 };
  probabilities[action] = 1;
  return {
    action,
    probabilities,
    commit: action !== "hold",
    danger: dangerLevel(world),
    confidence: 1,
    probeHits: Math.max(0, questionCount - 3),
    probeTotal: Math.max(0, questionCount - 3),
    parsed: true,
    source: "rule",
  };
}

export function idleDecide(_world, { questionCount = 3 } = {}) {
  return {
    action: "hold",
    probabilities: { hold: 1, jump: 0, slide: 0, strike: 0 },
    commit: false,
    danger: 0,
    confidence: 1,
    probeHits: null,
    probeTotal: Math.max(0, questionCount - 3),
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
      const decision = decide(snapshotWorld(world), { questionCount });
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
  const world = createWorld(seed, { ...options, ...(options.level ? { level: structuredClone(options.level) } : {}) });
  const questionCount = options.questionCount ?? 3;
  const initialWorld = snapshotWorld(world);
  const frames = [];
  const decisions = [];
  const samples = [];
  const started = now();
  const frameMs = 1000 / 60;
  const controller = new AbortController();
  let pending = null;
  let pendingGold = null;
  let queued = null;
  let ended = false;
  let skippedOpportunities = 0;
  let lastOpportunity = -1;
  const elapsed = () => now() - started;

  // A response callback first advances all physics due at its arrival time.
  // Otherwise a stalled event loop could apply an action to historical frames.
  function complete(record, gold, decision, error) {
    if (ended) return;
    if (!error && (!decision || !["hold", "jump", "slide", "strike"].includes(decision.action))) {
      error = new Error("Invalid decision action");
    }
    const completionMs = elapsed();
    catchUp(completionMs);
    record.completionFrame = world.frame;
    record.completionMs = completionMs;
    record.latencyMs = completionMs - record.dispatchMs;
    record.error = error ? String(error.message ?? error) : null;
    record.status = error ? "error" : "completed";
    pending = null;
    pendingGold = null;
    if (error) {
      // Missing or invalid answers are misses, never successful idle responses.
      decision = readDecision({ state: record.request.state, answers: {} });
    }
    record.response = decision ? { ...decision, request: undefined } : null;
    record.action = decision.action;
    const sample = { gold, got: decision, ms: record.latencyMs, ...scoreSample(gold, decision) };
    samples.push(sample);
    if (!world.done && !error) queued = { record, decision };
  }

  function opportunity(canDispatch = true) {
    if (world.done || world.frame % POLICY.decisionEvery !== 0 || lastOpportunity === world.frame) return;
    lastOpportunity = world.frame;
    if (!canDispatch || pending || queued) {
      skippedOpportunities += 1;
      return;
    }
    const snapshot = snapshotWorld(world);
    const gold = goldLabels(snapshot, questionCount);
    const record = {
      id: decisions.length,
      dispatchFrame: world.frame,
      dispatchMs: elapsed(),
      completionFrame: null,
      completionMs: null,
      applicationFrame: null,
      action: null,
      latencyMs: null,
      status: "pending",
      error: null,
      request: buildRequest(snapshot, questionCount),
      response: null,
    };
    decisions.push(record);
    pending = record;
    pendingGold = gold;
    try {
      const value = decide(snapshot, { signal: controller.signal, questionCount });
      if (value && typeof value.then === "function") {
        Promise.resolve(value).then(
          (decision) => complete(record, gold, decision, null),
          (error) => complete(record, gold, null, error),
        );
      } else {
        complete(record, gold, value, null);
      }
    } catch (error) {
      complete(record, gold, null, error);
    }
  }

  function physicsFrame(wallTimeMs) {
    let action = "hold";
    if (queued) {
      action = queued.decision.action;
      queued.record.applicationFrame = world.frame;
      queued.record.status = "applied";
      world.telemetry = { ...queued.decision, ms: queued.record.latencyMs };
      queued = null;
    }
    step(world, action);
    if (options.trace) frames.push({
      frame: world.frame,
      action: world.lastAction,
      timestampMs: world.frame * frameMs,
      wallTimeMs,
      state: frameState(world),
    });
    options.onFrame?.(world);
  }

  function catchUp(wallTimeMs) {
    const due = Math.floor((wallTimeMs + 1e-7) / frameMs);
    while (!world.done && world.frame < due) {
      physicsFrame(wallTimeMs);
      // Requests during catchup see the current state, never a future state or gold.
      opportunity(world.frame >= due);
    }
  }

  opportunity();
  while (!world.done) {
    const waitMs = Math.max(0, (world.frame + 1) * frameMs - elapsed());
    await new Promise((resolve) => setTimeout(resolve, waitMs));
    catchUp(elapsed());
  }
  ended = true;
  if (pending) {
    pending.status = "cancelled_at_end";
    pending.error = "Episode ended before inference completed";
    pending.pendingMs = elapsed() - pending.dispatchMs;
    // An unanswered request contributes all its questions as misses.
    const gold = pendingGold;
    const got = readDecision({ state: pending.request.state, answers: {} });
    samples.push({ gold, got, ms: null, ...scoreSample(gold, got) });
  }
  controller.abort();
  const summary = summarizeEpisode(seed, world, samples);
  const errorCount = decisions.filter((row) => row.status === "error").length;
  const completed = decisions.filter((row) => row.status === "applied" || row.status === "completed");
  const valid = completed.filter((row) => row.response?.parsed !== false);
  return {
    ...summary,
    questions: questionCount,
    timing: "realtime",
    fps: 60,
    status: !valid.length ? (errorCount ? "unavailable" : "no_response") : errorCount ? "partial" : "measured",
    termination: world.failed ? "failed" : world.cleared ? "cleared" : "engine_frame_limit",
    elapsedWallMs: elapsed(),
    frameCount: world.frame,
    decisionCount: decisions.length,
    skippedOpportunities,
    errorCount,
    cancelledCount: decisions.filter((row) => row.status === "cancelled_at_end").length,
    initialWorld: options.trace ? initialWorld : undefined,
    frames: options.trace ? frames : undefined,
    decisions,
    finalState: frameState(world),
    result: { ...summary, samples: undefined },
  };
}

function snapshotWorld(world) {
  const { telemetry, ...physics } = world;
  return structuredClone(physics);
}

export function frameState(world) {
  return structuredClone({
    frame: world.frame,
    player: world.player,
    done: world.done,
    cleared: world.cleared,
    failed: world.failed,
    lastAction: world.lastAction,
    lastHit: world.lastHit,
    hazards: world.level.hazards,
    chips: world.level.chips,
  });
}

export function replayEpisode(episode) {
  if (!episode.initialWorld || !Array.isArray(episode.frames)) throw new Error("Replay requires --trace");
  const world = structuredClone(episode.initialWorld);
  for (const row of episode.frames) {
    if (row.frame !== world.frame + 1 || world.done) throw new Error(`Invalid replay frame ${row.frame}`);
    step(world, row.action);
    if (JSON.stringify(frameState(world)) !== JSON.stringify(row.state)) {
      throw new Error(`Replay state mismatch at frame ${row.frame}`);
    }
  }
  if (world.frame !== episode.frameCount || JSON.stringify(frameState(world)) !== JSON.stringify(episode.finalState)) {
    throw new Error("Replay final state mismatch");
  }
  return world;
}

function now() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function summarizeEpisode(seed, world, samples) {
  const latency = samples.map((sample) => sample.ms).filter(Number.isFinite).sort((a, b) => a - b);
  const mean = (values) => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0);
  const commits = samples.filter((sample) => sample.commitMatch != null);
  const dangers = samples.filter((sample) => sample.dangerError != null);
  const probeHits = samples.reduce((sum, sample) => sum + sample.probeHits, 0);
  const probeTotal = samples.reduce((sum, sample) => sum + sample.probeTotal, 0);
  const answerHits = samples.reduce((sum, sample) => sum + sample.answerHits, 0);
  const answerTotal = samples.reduce((sum, sample) => sum + sample.answerTotal, 0);
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
    answerHits,
    answerTotal,
    answerAcc: answerTotal ? answerHits / answerTotal : null,
    latencyMean: latency.length ? mean(latency) : null,
    latencyP50: percentile(latency, 0.5),
    latencyP95: percentile(latency, 0.95),
    lastHit: world.lastHit,
    samples,
  };
}

function percentile(sorted, p) {
  if (!sorted.length) return null;
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
    failRate: rows.length ? rows.filter((row) => row.failed).length / rows.length : 0,
    distance: mean("distance"),
    hits: mean("hits"),
    chips: mean("chips"),
    score: mean("score"),
    actionAcc: mean("actionAcc"),
    commitAcc: mean("commitAcc"),
    dangerMae: mean("dangerMae"),
    consistency: mean("consistency"),
    probeAcc: mean("probeAcc"),
    answerAcc: mean("answerAcc"),
    latencyMean: mean("latencyMean"),
    latencyP95: mean("latencyP95"),
    decisions: rows.length ? rows.reduce((sum, row) => sum + (row.decisionCount ?? row.decisions ?? 0), 0) / rows.length : 0,
  };
}

export async function remoteDecide(endpoint, world, questionCount, model, options = {}) {
  const request = buildRequest(world, questionCount);
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    signal: options.signal,
    body: JSON.stringify({
      model: model || undefined,
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
  return { ...readDecision(payload), source: "remote", request, rawAnswers: payload.answers ?? null, metadata: payload.metadata ?? null };
}

export { buildRequest };
