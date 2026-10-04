#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { access, mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { basename, dirname, extname, resolve } from 'node:path';

const argv = process.argv.slice(2);
if (argv.includes('--help')) {
  console.log('node scripts/capture-qa.mjs --input RECORDING --output videos/vector-run-3x3.mp4 [--manifest capture/manifest.json] [--capture-log videos/capture-log.json] [--validate-only]\nPreserves source timestamps, transcodes H.264 CRF 22, decodes the entire MP4, writes 3 PNGs and .qa.json. Existing outputs are not overwritten.');
  process.exit(0);
}
const options = {};
for (let i = 0; i < argv.length; i++) {
  const key = argv[i];
  if (key === '--validate-only') options.validateOnly = true;
  else if (['--input', '--output', '--manifest', '--capture-log'].includes(key) && argv[i + 1]) options[key.slice(2)] = argv[++i];
  else throw new Error(`Unknown or missing option: ${key}`);
}
if (!options.input || !options.output) throw new Error('--input and --output are required.');
const input = resolve(options.input);
const output = resolve(options.output);
if (extname(output).toLowerCase() !== '.mp4') throw new Error('Output must be an .mp4 path.');
if (!options.validateOnly && input === output) throw new Error('Input and output must differ (or use --validate-only).');
if (options.validateOnly && input !== output) throw new Error('--validate-only requires identical input/output paths.');
await stat(input);
await mkdir(dirname(output), { recursive: true });
const prefix = output.slice(0, -4);
const reportPath = `${prefix}.qa.json`;
for (const artifact of [...(!options.validateOnly ? [output] : []), reportPath, ...['start', 'middle', 'end'].map(name => `${prefix}.${name}.png`)]) {
  try {
    await access(artifact);
  } catch (error) {
    if (error.code === 'ENOENT') continue;
    throw error;
  }
  throw new Error(`Output already exists: ${artifact}. Choose a new output name.`);
}

async function command(binary, args) {
  return new Promise((resolveCommand, reject) => {
    const child = spawn(binary, args, { windowsHide: true });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', data => { stdout += data; });
    child.stderr.on('data', data => { stderr = (stderr + data).slice(-12000); });
    child.on('error', reject);
    child.on('close', exitCode => exitCode === 0 ? resolveCommand({ stdout, stderr, exitCode }) : reject(new Error(`${binary} exited ${exitCode}: ${stderr}`)));
  });
}
async function sha256(path) {
  const digest = createHash('sha256');
  for await (const chunk of createReadStream(path)) digest.update(chunk);
  return digest.digest('hex');
}
async function loadJson(path) { return JSON.parse(await readFile(resolve(path), 'utf8')); }
const toolVersions = {};
for (const binary of ['ffmpeg', 'ffprobe']) toolVersions[binary] = (await command(binary, ['-version'])).stdout.split(/\r?\n/)[0];
const manifest = options.manifest ? await loadJson(options.manifest) : null;
const captureLog = options['capture-log'] ? await loadJson(options['capture-log']) : null;
const transcodeArgs = ['-hide_banner', '-nostdin', '-n', '-i', input, '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '22', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough', '-movflags', '+faststart', output];
const report = {
  version: 1,
  generatedAt: new Date().toISOString(),
  input: { name: basename(input), sha256: await sha256(input) },
  output: { name: basename(output) },
  toolVersions,
  encoding: options.validateOnly ? null : { codec: 'libx264', crf: 22, pixelFormat: 'yuv420p', timestampPolicy: 'passthrough; no speed change', audio: 'omitted' },
  checks: {},
  representativeFrames: [],
  provenance: {
    manifestProvided: Boolean(manifest), captureLogProvided: Boolean(captureLog),
    gpuInferenceVerification: 'not verified by media QA; inspect original measured trace provenance',
    simultaneousInferenceClaim: false,
    visualQA: 'pending human or visual agent inspection of representative PNGs',
  },
};
try {
  const inputProbe = JSON.parse((await command('ffprobe', ['-v', 'error', '-show_format', '-of', 'json', input])).stdout);
  const inputDurationSeconds = Number(inputProbe.format?.duration);
  if (!options.validateOnly) await command('ffmpeg', transcodeArgs);
  Object.assign(report.output, { sha256: await sha256(output), bytes: (await stat(output)).size });
  report.ffprobe = JSON.parse((await command('ffprobe', ['-v', 'error', '-count_frames', '-show_format', '-show_streams', '-of', 'json', output])).stdout);
  report.ffprobe.format.filename = basename(output);
  const video = report.ffprobe.streams.find(stream => stream.codec_type === 'video');
  if (!video) throw new Error('Output has no video stream.');
  const durationSeconds = Number(report.ffprobe.format.duration || video.duration);
  report.checks.h264 = video.codec_name === 'h264';
  report.checks.fullHD = video.width >= 1920 && video.height >= 1080;
  report.checks.nonempty = Number(video.nb_read_frames) > 0 && Number.isFinite(durationSeconds) && durationSeconds > 0;
  report.checks.evenDimensions = video.width % 2 === 0 && video.height % 2 === 0;
  report.duration = { inputSeconds: Number.isFinite(inputDurationSeconds) ? inputDurationSeconds : null, outputSeconds: durationSeconds };
  if (Number.isFinite(inputDurationSeconds) && inputDurationSeconds > 0) {
    report.checks.durationPreserved = Math.abs(inputDurationSeconds - durationSeconds) <= 0.1;
  } else {
    report.provenance.durationVerification = 'source recording duration unavailable; 1x duration preservation requires capture log review';
  }
  const decoded = await command('ffmpeg', ['-hide_banner', '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', output, '-map', '0:v:0', '-f', 'null', '-']);
  report.checks.fullDecode = decoded.exitCode === 0 && !decoded.stderr.trim();
  const times = [0, durationSeconds / 2, Math.max(0, durationSeconds - 0.2)];
  for (let i = 0; i < times.length; i++) {
    const path = `${prefix}.${['start', 'middle', 'end'][i]}.png`;
    await command('ffmpeg', ['-hide_banner', '-nostdin', '-v', 'error', '-n', '-ss', String(times[i]), '-i', output, '-frames:v', '1', '-update', '1', path]);
    await stat(path);
    report.representativeFrames.push({ name: basename(path), atSeconds: times[i], sha256: await sha256(path) });
  }
  if (manifest) report.provenance.manifest = manifest;
  if (captureLog) {
    report.provenance.captureLog = captureLog;
    report.provenance.timingVerification = 'capture log attached; player elapsed and wall clock require review';
  }
  report.mediaPassed = Object.values(report.checks).every(value => value === true);
} catch (error) {
  report.mediaPassed = false;
  report.error = error.message;
}
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
console.log(JSON.stringify({ mediaPassed: report.mediaPassed, report: reportPath, video: output, frames: report.representativeFrames.map(frame => frame.name), gpuInferenceVerification: report.provenance.gpuInferenceVerification }));
if (!report.mediaPassed) process.exitCode = 1;
