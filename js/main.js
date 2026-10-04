import { aggregate, idleDecide, remoteDecide, ruleDecide, runEpisode, runEpisodeAsync } from "./bench.js";
import { createWorld, ruleAction, scoreOf, step } from "./engine.js";
import { POLICY } from "./policy.js";
import { drawWorld } from "./render.js";

const canvas = document.querySelector("#view");
const ctx = canvas.getContext("2d");
const statusEl = document.querySelector("#status");
const hudEl = document.querySelector("#hud");
const barsEl = document.querySelector("#bars");
const tableEl = document.querySelector("#results");
const seedEl = document.querySelector("#seed");
const endpointEl = document.querySelector("#endpoint");
const modelEl = document.querySelector("#model");
const questionsEl = document.querySelector("#questions");
const timingEl = document.querySelector("#timing");

const keys = new Set();
let mode = "rule";
let world = createWorld(1);
let runId = 0;
let paused = false;
let benching = false;
let inflight = null;
let queued = null;
let announced = false;
const seen = new Set();
let lastDraw = 0;
let acc = 0;
let viewW = 960;
let viewH = 460;

const ACTION_LABEL = { hold: "維持", jump: "跳ぶ", slide: "くぐる", strike: "打つ" };

function questionCount() {
  return Number(questionsEl.value);
}

function seedValue() {
  const seed = Number(seedEl.value);
  return Number.isFinite(seed) && seed > 0 ? Math.floor(seed) : 1;
}

function start(nextMode = mode, seed = seedValue()) {
  runId += 1;
  mode = nextMode;
  world = createWorld(seed);
  inflight = null;
  queued = null;
  announced = false;
  paused = false;
  setPressed("mode");
  setStatus(mode === "remote" ? "モデルの判断を待っています。" : "走行中。");
}

function setStatus(text) {
  statusEl.textContent = text;
}

function setPressed(group) {
  for (const button of document.querySelectorAll("[data-mode]")) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  }
  void group;
}

window.addEventListener("keydown", (event) => {
  keys.add(event.code);
  if (["Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.code)) {
    event.preventDefault();
  }
  if (event.code === "KeyP") paused = !paused;
  if (event.code === "KeyR") start(mode);
  if (event.repeat) return;
  if (["Space", "ArrowUp", "KeyW", "ArrowDown", "KeyS", "KeyJ", "KeyK"].includes(event.code)) {
    if (mode !== "human") start("human");
  }
});
window.addEventListener("keyup", (event) => {
  keys.delete(event.code);
  seen.delete(event.code);
});

for (const button of document.querySelectorAll("[data-mode]")) {
  button.addEventListener("click", () => start(button.dataset.mode));
}
document.querySelector("#restart").addEventListener("click", () => start(mode));
document.querySelector("#bench").addEventListener("click", () => runBench());
for (const button of document.querySelectorAll("[data-touch]")) {
  const code = button.dataset.touch;
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    keys.add(code);
    if (mode !== "human") start("human");
  });
  const release = () => {
    keys.delete(code);
    seen.delete(code);
  };
  button.addEventListener("pointerup", release);
  button.addEventListener("pointerleave", release);
}

function edge(code) {
  if (!keys.has(code) || seen.has(code)) return false;
  seen.add(code);
  return true;
}

function humanAction() {
  if (edge("Space") || edge("ArrowUp") || edge("KeyW") || edge("TouchJump")) return "jump";
  if (edge("ArrowDown") || edge("KeyS") || edge("TouchSlide")) return "slide";
  if (edge("KeyJ") || edge("KeyK") || edge("TouchStrike")) return "strike";
  return "hold";
}

function tick() {
  if (world.done) return;
  const deciding = world.frame % POLICY.decisionEvery === 0;
  if (mode === "remote" && deciding) {
    if (timingEl.value === "step") {
      if (!inflight && !queued) requestRemote();
      if (!queued) return;
    } else if (!inflight) {
      requestRemote();
    }
  }
  let action = "hold";
  if (mode === "human") action = humanAction();
  else if (mode === "rule" && deciding) action = ruleDecide(world).action;
  else if (mode === "idle") action = "hold";
  else if (mode === "remote" && deciding && queued) {
    action = queued.action;
    world.telemetry = queued;
    queued = null;
  }
  if (deciding && mode === "rule") world.telemetry = { ...ruleDecide(world), ms: 0 };
  if (mode === "human" && (deciding || action !== "hold")) {
    const probabilities = { hold: 0, jump: 0, slide: 0, strike: 0 };
    probabilities[action] = 1;
    world.telemetry = { action, probabilities, commit: action !== "hold", danger: null, ms: 0, source: "human" };
  }
  if (deciding && mode === "idle") world.telemetry = { ...idleDecide(), ms: 0 };
  step(world, action);
}

function requestRemote() {
  const token = runId;
  const count = questionCount();
  const endpoint = endpointEl.value.trim();
  const started = performance.now();
  inflight = remoteDecide(endpoint, world, count, modelEl.value.trim())
    .then((decision) => {
      if (token !== runId) return;
      decision.ms = performance.now() - started;
      queued = decision;
      inflight = null;
    })
    .catch((error) => {
      if (token !== runId) return;
      inflight = null;
      queued = { ...idleDecide(), source: "remote", error: error.message };
      setStatus(error.message);
    });
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  viewW = Math.max(320, rect.width);
  viewH = Math.max(220, rect.height);
  canvas.width = Math.floor(viewW * dpr);
  canvas.height = Math.floor(viewH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function paint() {
  drawWorld(ctx, world, viewW, viewH);
  const player = world.player;
  const gold = ruleAction(world);
  const telemetry = world.telemetry;
  const modelAction = telemetry?.action ?? "—";
  hudEl.innerHTML = [
    `<span>シード ${world.seed}</span>`,
    `<span>距離 ${Math.round(player.x)}</span>`,
    `<span>残り ${Math.max(0, world.level.goal - Math.round(player.x))}</span>`,
    `<span>体力 ${player.hearts}</span>`,
    `<span>チップ ${player.chips}</span>`,
    `<span>得点 ${scoreOf(world)}</span>`,
    `<span>ルール ${ACTION_LABEL[gold]}</span>`,
    `<span>モデル ${ACTION_LABEL[modelAction] ?? modelAction}</span>`,
  ].join("");
  paintBars(telemetry);
  if (!benching && world.done && !announced) {
    announced = true;
    setStatus(world.cleared ? `ゴール。得点 ${scoreOf(world)}。R で同じシードをもう一度。` : "体力が尽きました。R で再走。");
  }
}

function paintBars(telemetry) {
  const probs = telemetry?.probabilities;
  barsEl.innerHTML = ["hold", "jump", "slide", "strike"]
    .map((action) => {
      const value = probs?.[action] ?? 0;
      return `<div class="bar ${telemetry?.action === action ? "is-chosen" : ""}">
        <span>${ACTION_LABEL[action]}</span>
        <i><b style="transform:scaleX(${Math.max(0, Math.min(1, value))})"></b></i>
        <em>${probs ? value.toFixed(2) : "—"}</em>
      </div>`;
    })
    .join("");
  const extra = document.querySelector("#extra");
  if (!telemetry) {
    extra.textContent = "判断はまだありません。";
    return;
  }
  const commit = telemetry.commit == null ? "—" : telemetry.commit ? "必要" : "まだ";
  const danger = telemetry.danger == null ? "—" : ["落ち着き", "注意", "今"][telemetry.danger] ?? telemetry.danger;
  const latency = telemetry.ms == null ? "—" : `${telemetry.ms.toFixed(1)} ms`;
  extra.textContent = `commit ${commit} / 危険 ${danger} / 遅延 ${latency}`;
}

function loop(now) {
  requestAnimationFrame(loop);
  const delta = Math.min(50, now - lastDraw);
  lastDraw = now;
  if (!paused && !benching) {
    acc += delta;
    while (acc >= 1000 / 60) {
      tick();
      acc -= 1000 / 60;
      if (world.done || (mode === "remote" && timingEl.value === "step" && world.frame % POLICY.decisionEvery === 0 && !queued)) {
        break;
      }
    }
  }
  paint();
}

async function runBench() {
  if (benching) return;
  benching = true;
  paused = true;
  const seeds = Array.from({ length: 12 }, (_, index) => index + 1);
  const agents = [
    ["ルール", (seed) => runEpisode(seed, ruleDecide)],
    ["停止", (seed) => runEpisode(seed, idleDecide)],
  ];
  const endpoint = endpointEl.value.trim();
  let remoteOk = false;
  try {
    const health = await fetch(new URL("/health", endpoint));
    remoteOk = health.ok;
  } catch {
    remoteOk = false;
  }
  if (remoteOk) {
    agents.push([
      "モデル",
      (seed) =>
        runEpisodeAsync(seed, (world) => remoteDecide(endpoint, world, questionCount(), modelEl.value.trim())),
    ]);
  }
  const summaries = [];
  for (const [name, run] of agents) {
    const rows = [];
    for (const seed of seeds) {
      setStatus(`${name} ${rows.length + 1}/${seeds.length}`);
      try {
        rows.push(await run(seed));
      } catch (error) {
        setStatus(error.message);
        rows.push({
          seed,
          cleared: false,
          failed: true,
          distance: 0,
          hits: 0,
          chips: 0,
          score: 0,
          actionAcc: 0,
          commitAcc: null,
          dangerMae: null,
          consistency: null,
          probeAcc: null,
          latencyP95: null,
        });
      }
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    summaries.push({ name, ...aggregate(rows) });
    renderTable(summaries, !remoteOk);
  }
  setStatus(
    remoteOk
      ? "ベンチ完了。行動一致は、コースに書いたルールとの一致です。"
      : "ベンチ完了。モデルサーバには繋がらなかったので、ルールと停止だけ測りました。",
  );
  benching = false;
}

function renderTable(rows, skippedRemote) {
  const pct = (value) => (typeof value === "number" ? `${Math.round(value * 100)}%` : "—");
  const num = (value, digits = 0) => (typeof value === "number" ? value.toFixed(digits) : "—");
  tableEl.innerHTML = `<table>
    <thead><tr>
      <th>走者</th><th>クリア</th><th>距離</th><th>被弾</th><th>チップ</th>
      <th>行動一致</th><th>commit</th><th>危険MAE</th><th>一貫性</th><th>p95</th><th>プローブ</th>
    </tr></thead>
    <tbody>
      ${rows
        .map(
          (row) => `<tr>
            <td>${row.name}</td>
            <td>${pct(row.clearRate)}</td>
            <td>${num(row.distance)}</td>
            <td>${num(row.hits, 2)}</td>
            <td>${num(row.chips, 1)}</td>
            <td>${pct(row.actionAcc)}</td>
            <td>${pct(row.commitAcc)}</td>
            <td>${num(row.dangerMae, 2)}</td>
            <td>${pct(row.consistency)}</td>
            <td>${num(row.latencyP95, 1)}</td>
            <td>${pct(row.probeAcc)}</td>
          </tr>`,
        )
        .join("")}
    </tbody>
  </table>
  <p class="note">${skippedRemote ? "モデル列はありません。decision_server.py を起動してから、もう一度ベンチを回してください。" : "12シード。モデル列は選んだ問数（3 または 64）で測っています。"}</p>`;
}

resize();
window.addEventListener("resize", resize);
requestAnimationFrame(loop);
setPressed();
renderTable([], true);
