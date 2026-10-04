import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { aggregate, idleDecide, remoteDecide, runEpisodeAsync, ruleDecide } from "./js/bench.js";
import { POLICY } from "./js/policy.js";

const HELP = `VECTOR RUN real-time policy-following benchmark
node bench.mjs --agent remote|rule|idle --timing realtime --seeds 3 --questions 3
  --url http://127.0.0.1:8780/v1/systemone --model MODEL --output FILE --trace
  [--metadata FILE] [--revision REV] [--base-revision REV]
64-question stress: --seeds 1 --questions 64 (separate output).
--metadata JSON: {model:{revision,baseRevision},hardware:{gpu,dtype,quantization,dependencies}}.
Unknown metadata is null; no model or mock fallback. All agents use 60Hz wall-clock pacing.`;

function argumentsOf(args) {
  const values = {};
  const valued = new Set(["agent", "timing", "seeds", "questions", "url", "model", "output", "metadata", "revision", "base-revision"]);
  for (let index = 0; index < args.length; index += 1) {
    const key = args[index].replace(/^--/, "");
    if (args[index] !== `--${key}`) throw new Error(`Unknown argument: ${args[index]}`);
    if (["trace", "help"].includes(key)) values[key] = true;
    else if (valued.has(key) && args[index + 1] && !args[index + 1].startsWith("--")) values[key] = args[++index];
    else throw new Error(`Unknown argument or missing value: --${key}`);
  }
  return values;
}

async function main() {
  const args = argumentsOf(process.argv.slice(2));
  if (args.help) { console.log(HELP); return; }
  const agent = args.agent ?? "rule";
  const timing = args.timing ?? "realtime";
  const questions = Number(args.questions ?? 3);
  const seeds = Number(args.seeds ?? (questions === 64 ? 1 : 3));
  if (!["rule", "idle", "remote"].includes(agent)) throw new Error("--agent must be rule, idle or remote");
  if (timing !== "realtime") throw new Error("--timing must be realtime; inference must not pause physics");
  if (![3, 64].includes(questions)) throw new Error("--questions must be 3 or 64");
  if (!Number.isSafeInteger(seeds) || seeds < 1) throw new Error("--seeds must be a positive integer count (seeds 1..N)");
  if (questions === 64 && seeds !== 1) throw new Error("64-question stress must use --seeds 1, separately from the primary benchmark");
  if (agent === "remote" && !args.model) throw new Error("--model is required for remote inference");
  const endpoint = args.url ?? "http://127.0.0.1:8780/v1/systemone";
  if (agent === "remote" && !["http:", "https:"].includes(new URL(endpoint).protocol)) throw new Error("--url must be HTTP(S)");
  const metadata = args.metadata ? JSON.parse(readFileSync(args.metadata, "utf8").replace(/^\uFEFF/, "")) : {};
  const cwd = fileURLToPath(new URL(".", import.meta.url));
  let commit = null;
  let dirty = null;
  try {
    commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    dirty = Boolean(execFileSync("git", ["status", "--porcelain", "--untracked-files=no"], { cwd, encoding: "utf8" }).trim());
  } catch { /* Non-Git copies remain explicit about unavailable provenance. */ }
  const started = performance.now();
  const episodes = [];
  const decide = agent === "remote"
    ? (world, context) => remoteDecide(endpoint, world, questions, args.model, { signal: context.signal })
    : agent === "rule" ? ruleDecide : idleDecide;
  for (let seed = 1; seed <= seeds; seed += 1) {
    episodes.push(await runEpisodeAsync(seed, decide, { questionCount: questions, trace: Boolean(args.trace) }));
  }
  const responseMetadata = episodes.flatMap((episode) => episode.decisions)
    .find((decision) => decision.response?.metadata)?.response.metadata ?? {};
  const suppliedModel = { ...responseMetadata.model, ...metadata.model };
  const suppliedHardware = { ...responseMetadata.hardware, ...metadata.hardware };
  const report = {
    schemaVersion: 1,
    benchmarkType: "policy_following",
    status: episodes.every((episode) => episode.status === "measured") ? "measured"
      : episodes.some((episode) => ["measured", "partial"].includes(episode.status)) ? "partial" : "unavailable",
    agent,
    model: {
      id: agent === "remote" ? args.model : agent,
      revision: args.revision ?? suppliedModel.revision ?? null,
      baseRevision: args["base-revision"] ?? suppliedModel.baseRevision ?? null,
      baseRepo: suppliedModel.baseRepo ?? null,
    },
    hardware: {
      gpu: suppliedHardware.gpu ?? null,
      dtype: suppliedHardware.dtype ?? null,
      quantization: suppliedHardware.quantization ?? null,
      dependencies: { node: process.version, ...(suppliedHardware.dependencies ?? {}) },
    },
    game: { name: "VECTOR RUN", commit: metadata.gameCommit ?? commit, checkoutCommit: commit, dirty, policy: POLICY },
    timing,
    fps: 60,
    decisionEvery: POLICY.decisionEvery,
    questions,
    seeds: episodes.map((episode) => episode.seed),
    elapsedWallMs: performance.now() - started,
    aggregate: aggregate(episodes),
    episodes,
  };
  const json = `${JSON.stringify(report, null, 2)}\n`;
  if (args.output) {
    const output = resolve(args.output);
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, json, "utf8");
    console.log(JSON.stringify({ output, status: report.status, agent, questions, seeds: report.seeds, frames: episodes.map((episode) => episode.frameCount) }));
  } else console.log(json);
}

main().catch((error) => { console.error(error.message); process.exitCode = 1; });
