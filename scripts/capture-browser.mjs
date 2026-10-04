#!/usr/bin/env node
// Fallback only after an explicit T3 preview unsupported/unavailable response.
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { loadMeasuredTrace, validateManifest } from '../capture/replay.mjs';

const args = process.argv.slice(2);
if (args.includes('--help')) {
  console.log('node scripts/capture-browser.mjs [--manifest capture/manifest.measured.json] [--url http://127.0.0.1:8787/comparison.html] [--playwright-module PATH_TO_INDEX_MJS] [--browser chrome|msedge|chromium] [--output videos/raw] [--log videos/capture-log.json] [--snapshot capture/browser-check.png] [--check-only]\nT3 unavailable fallback only. Recording requires all seven validated GPU model traces and rule/idle. Check-only creates no video and permits an unmeasured screen. Uses a real 1920x1080 browser and actual wall-clock replay; server must already be running.');
  process.exit(0);
}
const options = {};
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--check-only') options.checkOnly = true;
  else if (['--manifest', '--url', '--playwright-module', '--browser', '--output', '--log', '--snapshot'].includes(args[i]) && args[i + 1]) options[args[i].slice(2)] = args[++i];
  else throw new Error(`Unknown or missing option: ${args[i]}`);
}
const root = fileURLToPath(new URL('../', import.meta.url));
const manifestPath = resolve(options.manifest || resolve(root, 'capture/manifest.measured.json'));
const manifest = validateManifest(JSON.parse(await readFile(manifestPath, 'utf8')));
const measuredRemote = [], measuredBaselines = [], gpuRemote = [], invalid = [];
for (const tile of manifest.tiles) {
  if (!tile.result) continue;
  try {
    const resultPath = fileURLToPath(new URL(tile.result, pathToFileURL(manifestPath)));
    const bytes = await readFile(resultPath);
    if (tile.sourceSha256 && createHash('sha256').update(bytes).digest('hex') !== tile.sourceSha256) throw new Error('trace SHA256 mismatch');
    const report = JSON.parse(bytes.toString('utf8'));
    loadMeasuredTrace(report, tile, manifest);
    if (!['rule', 'idle'].includes(tile.id)) {
      measuredRemote.push(tile.id);
      const gpu = report.hardware?.gpu;
      if (typeof gpu === 'string' && gpu.trim() && !/^(none|unknown|cpu|not available|unavailable)$/i.test(gpu.trim())) gpuRemote.push(tile.id);
    } else measuredBaselines.push(tile.id);
  } catch (error) { invalid.push({ id: tile.id, error: error.message }); }
}
if (!options.checkOnly && (gpuRemote.length !== 7 || !['rule', 'idle'].every(id => measuredBaselines.includes(id)))) throw new Error('Recording refused: all seven validated GPU model traces and both rule/idle traces are required. Run --check-only for an unmeasured screen.');
const pageUrl = new URL(options.url || 'http://127.0.0.1:8787/comparison.html');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(pageUrl.hostname)) throw new Error('Capture URL must use the local loopback server.');
const manifestRelative = relative(root, manifestPath).split(sep).join('/');
if (manifestRelative.startsWith('../') || manifestRelative === '..') throw new Error('Manifest must be inside the served repository root.');
pageUrl.searchParams.set('manifest', `/${manifestRelative}`);
pageUrl.searchParams.set('capture', '1');
const playwright = options['playwright-module'] ? await import(pathToFileURL(resolve(options['playwright-module'])).href) : await import('playwright');
const browserName = options.browser || 'chrome';
if (!['chrome', 'msedge', 'chromium'].includes(browserName)) throw new Error('Browser must be chrome, msedge or chromium.');
const logPath = resolve(options.log || (options.checkOnly ? 'capture/browser-check.json' : 'videos/capture-log.json'));
const snapshotPath = resolve(options.snapshot || 'capture/browser-check.png');
await mkdir(dirname(logPath), { recursive: true });
await mkdir(dirname(snapshotPath), { recursive: true });
if (!options.checkOnly) await mkdir(resolve(options.output || 'videos/raw'), { recursive: true });
const browser = await playwright.chromium.launch({ headless: true, ...(browserName === 'chromium' ? {} : { channel: browserName }) });
let context, page, recordingPath;
const log = { version: 1, mode: options.checkOnly ? 'screen-check-no-recording' : 'measured-trace-replay-recording', transport: 'playwright-fallback-after-T3-unavailable', viewport: { width: 1920, height: 1080 }, speed: 1, measuredRemote, measuredBaselines, gpuRemote, invalid, simultaneousInferenceClaim: false, checks: {}, consoleErrors: [] };
try {
  log.browserVersion = browser.version();
  context = await browser.newContext({ viewport: log.viewport, deviceScaleFactor: 1, ...(options.checkOnly ? {} : { recordVideo: { dir: resolve(options.output || 'videos/raw'), size: log.viewport } }) });
  page = await context.newPage();
  page.on('pageerror', error => log.consoleErrors.push(error.message));
  await page.goto(pageUrl.href, { waitUntil: 'networkidle' });
  log.initial = await page.evaluate(async () => { await window.capturePlayer.ready; await document.fonts.ready; return window.capturePlayer.status(); });
  log.checks.nineTiles = log.initial.tiles.length === 9;
  log.checks.noInvalidTiles = !log.initial.tiles.some(tile => tile.status === 'invalid');
  if (!options.checkOnly && (!gpuRemote.every(id => log.initial.tiles.some(tile => tile.id === id && tile.status === 'measured')) || !measuredBaselines.every(id => log.initial.tiles.some(tile => tile.id === id && tile.status === 'measured')))) throw new Error('Recording refused: required measured traces did not load in the real browser.');
  const startedAt = Date.now();
  log.started = await page.evaluate(() => window.capturePlayer.start());
  // This waits on the real rAF common clock. No seeking, virtual-time advance,
  // frame synthesis, pause or speed change is used.
  await page.waitForFunction(() => window.capturePlayer.status().complete, null, { timeout: manifest.durationMs + 10000, polling: 100 });
  log.wallElapsedMs = Date.now() - startedAt;
  log.final = await page.evaluate(() => window.capturePlayer.status());
  log.checks.realWallClock = log.wallElapsedMs >= manifest.durationMs && Math.abs(log.wallElapsedMs - log.final.elapsedMs) < 1000;
  log.checks.complete = log.final.complete && !log.final.running;
  const measuredTiles = log.final.tiles.filter(tile => tile.finalFrame !== null);
  log.checks.finalFramesHeld = measuredTiles.length ? measuredTiles.every(tile => tile.frame === tile.finalFrame) : null;
  log.measuredGameplayVerification = measuredTiles.length ? 'measured final frames checked' : 'not performed: no measured gameplay traces';
  log.checks.animationProgressed = log.final.paintCount > 1 && log.final.elapsedMs >= manifest.durationMs;
  log.checks.noPageErrors = log.consoleErrors.length === 0;
  await page.screenshot({ path: snapshotPath, fullPage: false });
  log.snapshot = relative(root, snapshotPath).split(sep).join('/');
  const video = page.video();
  await context.close();
  if (video) {
    recordingPath = await video.path();
    log.recording = relative(root, recordingPath).split(sep).join('/');
  }
  log.passed = Object.values(log.checks).every(value => value === true || value === null);
} catch (error) {
  log.passed = false;
  log.error = error.message;
} finally {
  await browser.close();
  await writeFile(logPath, `${JSON.stringify(log, null, 2)}\n`);
}
console.log(JSON.stringify({ passed: log.passed, checkOnly: Boolean(options.checkOnly), wallElapsedMs: log.wallElapsedMs ?? null, playerElapsedMs: log.final?.elapsedMs ?? null, recording: log.recording ?? null, log: relative(root, logPath).split(sep).join('/'), snapshot: log.snapshot ?? null, gpuRemote }));
if (!log.passed) process.exitCode = 1;
