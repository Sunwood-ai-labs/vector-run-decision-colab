import assert from "node:assert/strict";
import { createServer } from "node:http";
import { performance } from "node:perf_hooks";
import test from "node:test";

import { frameState, idleDecide, remoteDecide, replayEpisode, runEpisodeAsync } from "../js/bench.js";
import { createWorld } from "../js/engine.js";
import { POLICY } from "../js/policy.js";
import { buildRequest, goldLabels, readDecision, scoreSample } from "../js/questions.js";

const FRAME_MS = 1000 / 60;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const level = (frames = 24) => ({ seed: 1, goal: 48 + frames * POLICY.speed, hazards: [], chips: [] });
const decision = (action = "hold") => ({ ...idleDecide(), action, commit: action !== "hold" });

test("unresolved transport cannot pause physics or prevent an obstacle failure", { timeout: 5000 }, async () => {
  let dispatchedSnapshot;
  let context;
  const episode = await runEpisodeAsync(1, (world, options) => {
    dispatchedSnapshot = world;
    context = options;
    return new Promise(() => {});
  }, {
    trace: true,
    level: {
      seed: 1,
      goal: 800,
      hazards: [79, 324, 569].map((x, index) => ({
        id: `h${index}`, kind: "crate", x, w: POLICY.crate.w, h: POLICY.crate.h, spent: false,
      })),
      chips: [],
    },
  });
  assert.equal(episode.status, "no_response");
  assert.equal(episode.termination, "failed");
  assert.equal(episode.finalState.failed, true);
  assert.equal(episode.finalState.player.hits, 3);
  assert.ok(episode.frameCount >= 96);
  assert.equal(episode.decisionCount, 1);
  assert.ok(episode.skippedOpportunities > 0);
  assert.equal(episode.decisions[0].status, "cancelled_at_end");
  assert.equal(episode.decisions[0].applicationFrame, null);
  assert.ok(episode.frames.every((frame) => frame.action === "hold"));
  assert.equal(dispatchedSnapshot.frame, 0, "dispatch receives an immutable point-in-time copy");
  assert.equal(dispatchedSnapshot.player.x, 48);
  assert.deepEqual(Object.keys(context).sort(), ["questionCount", "signal"]);
  assert.equal(context.signal.aborted, true);
  assert.equal("gold" in dispatchedSnapshot, false);
  assert.equal("telemetry" in dispatchedSnapshot, false);
});

test("slow decisions have one outstanding request while physics continues", { timeout: 3000 }, async () => {
  let outstanding = 0;
  let maximum = 0;
  const episode = await runEpisodeAsync(1, async () => {
    outstanding += 1;
    maximum = Math.max(maximum, outstanding);
    await pause(160);
    outstanding -= 1;
    return decision();
  }, { trace: true, level: level(31) });
  assert.equal(maximum, 1);
  assert.equal(episode.frameCount, 31);
  assert.ok(episode.skippedOpportunities >= 1);
  assert.ok(episode.decisions.some((entry) => entry.completionFrame > entry.dispatchFrame));
  assert.ok(episode.frames.length > episode.decisionCount);
  // Drain the test-only fake, including any inference cancelled at the finish line.
  await pause(170);
});

test("a completed command applies once at its recorded next physical frame", { timeout: 2500 }, async () => {
  let calls = 0;
  const episode = await runEpisodeAsync(1, async () => decision(calls++ === 0 ? "jump" : "hold"), {
    trace: true, level: level(18),
  });
  const jump = episode.decisions.find((entry) => entry.response?.action === "jump");
  assert.ok(jump);
  assert.equal(jump.status, "applied");
  assert.equal(episode.frames.filter((frame) => frame.action === "jump").length, 1);
  assert.equal(episode.frames[jump.applicationFrame].action, "jump");
  assert.equal(episode.frames[jump.applicationFrame].frame, jump.applicationFrame + 1);
  assert.ok(jump.applicationFrame >= jump.completionFrame);
  for (const frame of episode.frames) {
    assert.ok(Math.abs(frame.timestampMs - frame.frame * FRAME_MS) < 1e-9);
    assert.ok(frame.wallTimeMs >= 0);
  }
});

test("event-loop stalls catch up physics without backdating a completed action", { timeout: 3000 }, async () => {
  let stalled = false;
  let stallEndedAt = 0;
  let frameTenAt = 0;
  let calls = 0;
  const episode = await runEpisodeAsync(1, async () => {
    const first = calls++ === 0;
    await pause(first ? 35 : 0);
    return decision(first ? "jump" : "hold");
  }, {
    trace: true,
    level: level(24),
    onFrame(world) {
      if (!stalled) {
        stalled = true;
        const until = performance.now() + 165;
        while (performance.now() < until) { /* Deliberately block this disposable test process. */ }
        stallEndedAt = performance.now();
      }
      if (world.frame === 10) frameTenAt = performance.now();
    },
  });
  const jump = episode.decisions.find((entry) => entry.response?.action === "jump");
  assert.ok(jump);
  assert.ok(jump.latencyMs >= 150);
  assert.ok(jump.applicationFrame >= 10, "late completion must not affect elapsed historical frames");
  assert.ok(episode.frames.slice(0, 10).every((frame) => frame.action === "hold"));
  assert.ok(frameTenAt > 0);
  assert.ok(frameTenAt - stallEndedAt < 100, "the elapsed backlog must run without 60 Hz waits per old frame");
  assert.equal(episode.frameCount, 24);
});

test("trace replay reconstructs movement, pickups and moving hazards and rejects tampering", { timeout: 2500 }, async () => {
  const customLevel = level(18);
  customLevel.hazards.push({ id: "moving", kind: "drone", x: 250, y: 16, w: 24, h: 20, vx: -1, spent: false });
  customLevel.chips.push({ id: "pickup", x: 70, y: 16, w: 14, h: 14, taken: false });
  const episode = await runEpisodeAsync(1, async () => decision(), { trace: true, level: customLevel });
  assert.equal(episode.initialWorld.level.chips[0].taken, false);
  assert.equal(episode.finalState.chips[0].taken, true);
  assert.equal(episode.finalState.hazards[0].x, 250 - episode.frameCount);
  assert.deepEqual(frameState(replayEpisode(episode)), episode.finalState);
  const tamperedState = structuredClone(episode);
  tamperedState.frames[2].state.player.x += 1;
  assert.throws(() => replayEpisode(tamperedState), /frame|state|trace|replay|mismatch/i);
  const tamperedAction = structuredClone(episode);
  tamperedAction.frames[0].action = "jump";
  assert.throws(() => replayEpisode(tamperedAction), /frame|state|trace|replay|mismatch/i);
  assert.equal(customLevel.chips[0].taken, false, "measurement must not mutate the reusable course fixture");
});

test("real local HTTP failures are recorded and physics reaches the goal", { timeout: 3000 }, async () => {
  const requests = [];
  const server = createServer((request, response) => {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      requests.push(JSON.parse(body));
      response.writeHead(503, { "content-type": "text/plain" });
      response.end("test transport unavailable");
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const endpoint = `http://127.0.0.1:${server.address().port}/v1/systemone`;
    const episode = await runEpisodeAsync(1, (world, { signal }) => remoteDecide(endpoint, world, 3, "test-only", { signal }), {
      questionCount: 3, trace: true, level: level(18),
    });
    assert.equal(episode.status, "unavailable");
    assert.equal(episode.termination, "cleared");
    assert.equal(episode.frameCount, 18);
    assert.ok(episode.errorCount >= 1);
    assert.ok(episode.decisions.some((entry) => entry.status === "error" && /503/.test(entry.error)));
    assert.ok(episode.frames.every((frame) => frame.action === "hold"));
    assert.ok(requests.length >= 1);
    assert.ok(requests.every((request) => !Object.hasOwn(request, "gold")));
    assert.ok(requests.every((request) => Object.keys(request.questions).length === 3));
  } finally {
    server.closeAllConnections();
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

test("64-question scoring counts every missing answer, including fallback hold", () => {
  const world = createWorld(1, { level: level() });
  const request = buildRequest(world, 64);
  const gold = goldLabels(world, 64);
  const missing = readDecision({ state: request.state, answers: {} });
  const emptyScore = scoreSample(gold, missing);
  assert.equal(missing.probeTotal, 61);
  assert.equal(missing.probeHits, 0);
  assert.equal(missing.missingAnswers, 64);
  assert.equal(emptyScore.answerTotal, 64);
  assert.equal(emptyScore.answerHits, 0);
  assert.equal(emptyScore.actionMatch, false, "missing action must not receive credit for fallback hold");
  const partial = readDecision({
    state: request.state,
    answers: {
      action: { choice: "hold" }, commit: { noul: 0 }, danger: { score: 0 }, p0: { noul: 1 },
    },
  });
  assert.equal(partial.probeTotal, 61);
  assert.equal(partial.probeHits, 1);
  assert.equal(partial.missingAnswers, 60);
  assert.equal(scoreSample(gold, partial).answerHits, 4);
  assert.equal(scoreSample(gold, partial).answerTotal, 64);
});
