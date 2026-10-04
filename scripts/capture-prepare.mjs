#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadMeasuredTrace, validateManifest } from '../capture/replay.mjs';

const args = process.argv.slice(2);
if (args.includes('--help')) {
  console.log('node scripts/capture-prepare.mjs --results results --output capture/manifest.measured.json [--template capture/manifest.json]\nValidates existing <tile-id>/<tile-id>-q3.json through the game replay verifier. Capture requires all seven GPU model traces plus rule/idle. Missing/blocked/invalid results remain unmeasured; no source trace is modified.');
  process.exit(0);
}
const options = {};
for (let i = 0; i < args.length; i += 2) {
  if (!['--results', '--output', '--template'].includes(args[i]) || !args[i + 1]) throw new Error(`Unknown or missing option: ${args[i]}`);
  options[args[i].slice(2)] = args[i + 1];
}
if (!options.results || !options.output) throw new Error('--results and --output are required.');
const root = fileURLToPath(new URL('../', import.meta.url));
const resultDirectory = resolve(options.results);
const output = resolve(options.output);
const templatePath = resolve(options.template || resolve(root, 'capture/manifest.json'));
if (output === templatePath) throw new Error('Output must differ from the unmeasured template.');
const manifest = validateManifest(JSON.parse(await readFile(templatePath, 'utf8')));
const summary = { measuredRemote: [], measuredBaselines: [], unmeasured: [], gpuRemote: [], gpuUnverifiedRemote: [], readyForCapture: false, baselinesReady: false };
const failureStatuses = new Set(['blocked', 'capacity_blocked', 'load_failed', 'auth_required', 'failure', 'failed', 'error', 'unavailable', 'unmeasured']);
for (const tile of manifest.tiles) {
  tile.result = null;
  delete tile.sourceSha256;
  tile.note = '未測定';
  const resultPath = resolve(resultDirectory, ['rule', 'idle'].includes(tile.id) ? 'baselines' : tile.id, `${tile.id}-q3.json`);
  let bytes;
  try {
    bytes = await readFile(resultPath);
  } catch (error) {
    if (error.code !== 'ENOENT') tile.note = '未測定: 結果ファイルを読み込めません';
    summary.unmeasured.push({ id: tile.id, note: tile.note });
    continue;
  }
  try {
    const report = JSON.parse(bytes.toString('utf8'));
    if (failureStatuses.has(report.status)) {
      tile.note = `未測定: ${report.status}`;
      summary.unmeasured.push({ id: tile.id, note: tile.note });
      continue;
    }
    loadMeasuredTrace(report, tile, manifest);
    tile.result = relative(dirname(output), resultPath).split(sep).map(encodeURIComponent).join('/');
    tile.sourceSha256 = createHash('sha256').update(bytes).digest('hex');
    delete tile.note;
    if (['rule', 'idle'].includes(tile.id)) summary.measuredBaselines.push(tile.id);
    else {
      summary.measuredRemote.push(tile.id);
      const gpu = report.hardware?.gpu;
      if (typeof gpu === 'string' && gpu.trim() && !/^(none|unknown|cpu|not available|unavailable)$/i.test(gpu.trim())) summary.gpuRemote.push(tile.id);
      else {
        summary.gpuUnverifiedRemote.push(tile.id);
        tile.note = '実測 trace / GPU 未確認';
      }
    }
  } catch (error) {
    // Replay errors contain schema/physics field names; never publish raw loader logs.
    const detail = error instanceof SyntaxError ? '結果 JSON が不正です' : error.message.replace(/[\r\n]+/g, ' ').slice(0, 180);
    tile.note = `未測定: ${detail}`;
    summary.unmeasured.push({ id: tile.id, note: tile.note });
  }
}
summary.baselinesReady = ['rule', 'idle'].every(id => summary.measuredBaselines.includes(id));
summary.readyForCapture = summary.gpuRemote.length === 7 && summary.baselinesReady;
await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify({ output: options.output, ...summary }));
