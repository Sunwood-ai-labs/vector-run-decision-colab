import { aggregate, idleDecide, remoteDecide, runEpisode, runEpisodeAsync, ruleDecide } from "./js/bench.js";

const args = process.argv.slice(2);

function flag(name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  return args[index + 1];
}

const seeds = Number(flag("--seeds", "12"));
const questions = Number(flag("--questions", "3"));
const agent = flag("--agent", "both");
const endpoint = flag("--url", "http://127.0.0.1:8780/v1/systemone");
const model = flag("--model", "vllm-sr/Decision-2.0-Kai-0.6B");

const jobs = [];
if (agent === "rule" || agent === "both" || agent === "local") jobs.push(["rule", (seed) => runEpisode(seed, ruleDecide)]);
if (agent === "idle" || agent === "both" || agent === "local") jobs.push(["idle", (seed) => runEpisode(seed, idleDecide)]);
if (agent === "remote") {
  jobs.push([
    "remote",
    (seed) => runEpisodeAsync(seed, (world) => remoteDecide(endpoint, world, questions, model)),
  ]);
}

const report = [];
for (const [name, run] of jobs) {
  const rows = [];
  for (let seed = 1; seed <= seeds; seed += 1) rows.push(await run(seed));
  report.push({ agent: name, questions, ...aggregate(rows) });
}
console.log(JSON.stringify(report, null, 2));
