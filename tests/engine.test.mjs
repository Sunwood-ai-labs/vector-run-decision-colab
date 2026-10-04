import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { aggregate, idleDecide, runEpisode, ruleDecide } from "../js/bench.js";
import { createWorld, generateLevel, ruleAction, step } from "../js/engine.js";
import { POLICY } from "../js/policy.js";
import { buildRequest, readDecision } from "../js/questions.js";

test("policy.js matches policy.json", () => {
  const json = JSON.parse(readFileSync(new URL("../policy.json", import.meta.url), "utf8"));
  for (const key of Object.keys(json)) {
    assert.deepEqual(POLICY[key], json[key], key);
  }
});

test("one of each hazard is clearable by the written rule", () => {
  for (const kind of ["crate", "beam", "drone", "gap"]) {
    const episode = runEpisode(1, ruleDecide, {
      level: {
        seed: 1,
        goal: 1600,
        hazards: [hazard(kind, 720)],
        chips: [],
      },
    });
    assert.equal(episode.hits, 0, `${kind} hit ${JSON.stringify(episode.lastHit)}`);
    assert.equal(episode.cleared, true, kind);
  }
});

test("generated courses are deterministic and the rule usually clears them", () => {
  const left = generateLevel(7);
  const right = generateLevel(7);
  assert.deepEqual(left, right);
  const rows = [];
  for (let seed = 1; seed <= 24; seed += 1) rows.push(runEpisode(seed, ruleDecide));
  const summary = aggregate(rows);
  const misses = rows.filter((row) => !row.cleared || row.hits > 0);
  assert.equal(
    summary.clearRate,
    1,
    `clear ${summary.clearRate} example ${JSON.stringify(misses[0]?.lastHit)} seed ${misses[0]?.seed}`,
  );
  assert.equal(summary.hits, 0, JSON.stringify(misses[0]?.lastHit));
  assert.equal(summary.actionAcc, 1);
  assert.equal(summary.commitAcc, 1);
  assert.equal(summary.dangerMae, 0);
});

test("idle crashes and scores below the rule", () => {
  const rule = aggregate([1, 2, 3, 4, 5].map((seed) => runEpisode(seed, ruleDecide)));
  const idle = aggregate([1, 2, 3, 4, 5].map((seed) => runEpisode(seed, idleDecide)));
  assert.equal(idle.clearRate, 0);
  assert.ok(idle.hits > rule.hits);
  assert.ok(rule.score > idle.score);
});

test("a 64-question request is one state plus action, commit, danger and probes", () => {
  const world = createWorld(3);
  const request = buildRequest(world, 64);
  assert.equal(Object.keys(request.questions).length, 64);
  assert.equal(request.state.probes.length, 61);
  assert.equal(request.questions.action.type, "choice");
  assert.equal(request.questions.commit.type, "noul");
  assert.equal(request.questions.danger.type, "score");
  assert.deepEqual(request.questions.danger.criteria.length, 3);
});

test("System One answers parse back into a legal action", () => {
  const world = createWorld(2);
  step(world, "hold");
  const request = buildRequest(world, 8);
  const parsed = readDecision({
    model: "vllm-sr/Decision-2.0-Kai-0.6B",
    state: request.state,
    answers: {
      action: {
        type: "choice",
        choice: "slide",
        probabilities: { hold: 0.05, jump: 0.1, slide: 0.8, strike: 0.05 },
        confidence: 0.4,
      },
      commit: { type: "noul", noul: 0.91 },
      danger: { type: "score", score: 1.8, probabilities: { 0: 0.05, 1: 0.1, 2: 0.85 } },
      p0: { type: "noul", noul: request.state.probes[0] ? 0.99 : 0.01 },
    },
  });
  assert.equal(parsed.action, "slide");
  assert.equal(parsed.commit, true);
  assert.equal(parsed.danger, 2);
  assert.equal(parsed.probeHits, 1);
  assert.equal(ruleAction(world), "hold");
});

test("mock decision server follows the same windows", async () => {
  const python = process.platform === "win32" ? "py" : "python";
  const args = process.platform === "win32"
    ? ["-3", "server/decision_server.py", "--mock", "--port", "8791"]
    : ["server/decision_server.py", "--mock", "--port", "8791"];
  const child = spawn(python, args, {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    stdio: "ignore",
  });
  try {
    await waitFor("http://127.0.0.1:8791/health");
    const response = await fetch("http://127.0.0.1:8791/v1/systemone", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        model: "decision-lane-mock",
        state: {
          runner: { grounded: true, sliding: false, striking: false },
          hazards: [{ id: "h", kind: "crate", dx: 80 }],
          probes: [true],
        },
        questions: {
          action: { type: "choice", instructions: "act", criteria: { hold: "h", jump: "j", slide: "s", strike: "t" } },
          commit: { type: "noul", instructions: "now?" },
          p0: { type: "noul", instructions: "probe" },
        },
      }),
    });
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.answers.action.choice, "jump");
    assert.ok(body.answers.commit.noul > 0.5);
    assert.ok(body.answers.p0.noul > 0.5);
  } finally {
    child.kill();
  }
});

async function waitFor(url) {
  const started = Date.now();
  let last = "not started";
  while (Date.now() - started < 8000) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      last = String(response.status);
    } catch (error) {
      last = error.message;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`server did not start: ${last}`);
}

function hazard(kind, x) {
  if (kind === "crate") return { id: "h", kind, x, w: POLICY.crate.w, h: POLICY.crate.h, spent: false };
  if (kind === "beam") {
    return { id: "h", kind, x, w: POLICY.beam.w, y: POLICY.beam.bottom, h: POLICY.beam.h, spent: false };
  }
  if (kind === "drone") {
    return {
      id: "h",
      kind,
      x,
      w: POLICY.drone.w,
      h: POLICY.drone.h,
      y: POLICY.drone.y,
      vx: POLICY.drone.vx,
      spent: false,
    };
  }
  return { id: "h", kind, x, w: POLICY.gapW, h: 0, spent: false };
}
