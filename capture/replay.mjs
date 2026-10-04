import { createWorld, step } from '../js/engine.js';

export const TILE_IDS = ['kai', 'eos', 'sol', 'sol-reasoning', 'nox', 'lux', 'vega', 'rule', 'idle'];
const actions = new Set(['hold', 'jump', 'slide', 'strike']);
const stateKeys = ['frame', 'player', 'done', 'cleared', 'failed', 'lastAction', 'lastHit', 'hazards', 'chips'];
const clone = value => structuredClone(value);
function invariant(condition, message) { if (!condition) throw new Error(message); }

// Compare recorded fields without depending on JSON object key order.
function compare(actual, expected, path) {
  if (expected && typeof expected === 'object') {
    invariant(actual && typeof actual === 'object', `${path}: state mismatch`);
    if (Array.isArray(expected)) invariant(Array.isArray(actual) && actual.length === expected.length, `${path}: length mismatch`);
    invariant(Object.keys(actual).length === Object.keys(expected).length && Object.keys(actual).every(key => key in expected), `${path}: incomplete or unexpected state keys`);
    for (const key of Object.keys(expected)) compare(actual[key], expected[key], `${path}.${key}`);
  } else invariant(Object.is(actual, expected), `${path}: state mismatch`);
}

export function validateManifest(manifest) {
  invariant(manifest.version === 1 && manifest.seed === 1 && manifest.questions === 3, 'manifest: seed 1 / questions 3 required');
  invariant(Number.isFinite(manifest.durationMs) && manifest.durationMs >= 15000, 'manifest: duration >= 15000 ms required');
  invariant(manifest.tiles?.length === 9 && manifest.tiles.every((tile, i) => tile.id === TILE_IDS[i]), 'manifest: ordered nine tiles required');
  return manifest;
}

export function loadMeasuredTrace(report, tile, manifest) {
  invariant(report.schemaVersion === 1, 'schemaVersion 1 required');
  invariant(report.game?.name === 'VECTOR RUN' && typeof report.game.commit === 'string', 'game commit required');
  invariant(report.timing === 'realtime' && report.fps === 60, 'realtime / 60 fps required');
  invariant(typeof report.model?.id === 'string' && report.hardware && Number.isFinite(report.elapsedWallMs), 'measurement metadata required');
  const baseline = ['rule', 'idle'].includes(tile.id);
  invariant(baseline ? report.model.id === tile.id : report.model.id === tile.modelId, 'model / tile identity mismatch');
  const episode = report.episodes?.find(row => row.seed === manifest.seed && row.questions === manifest.questions);
  invariant(episode?.initialWorld && Array.isArray(episode.frames) && episode.frames.length > 0, 'seed 1 / questions 3 measured trace required');
  invariant(['measured', 'partial'].includes(episode.status), '未測定: episode unavailable / no_response');
  invariant(episode.initialWorld.seed === 1 && episode.initialWorld.frame === 0 && !episode.initialWorld.done, 'initialWorld must start at frame 0 / seed 1');
  compare(createWorld(1), episode.initialWorld, 'initialWorld');
  invariant(episode.frameCount === episode.frames.length, 'frameCount mismatch');
  invariant(episode.frameCount * 1000 / 60 <= manifest.durationMs - 2000, 'duration must retain final results for >= 2 seconds');
  const world = clone(episode.initialWorld);
  for (let i = 0; i < episode.frames.length; i++) {
    const frame = episode.frames[i];
    invariant(frame.frame === i + 1 && actions.has(frame.action) && !world.done, `frame ${i + 1}: missing, repeated or invalid step`);
    invariant(Math.abs(frame.timestampMs - frame.frame * 1000 / 60) < .001 && Number.isFinite(frame.wallTimeMs), `frame ${i + 1}: invalid timing`);
    invariant(frame.state && stateKeys.every(key => key in frame.state), `frame ${i + 1}: incomplete state`);
    step(world, frame.action);
    const state = { frame: world.frame, player: world.player, done: world.done, cleared: world.cleared, failed: world.failed, lastAction: world.lastAction, lastHit: world.lastHit, hazards: world.level.hazards, chips: world.level.chips };
    compare(state, frame.state, `frame ${frame.frame}`);
  }
  invariant(world.done && episode.result, 'completed episode result required');
  invariant(episode.finalState, 'finalState required');
  compare({ frame: world.frame, player: world.player, done: world.done, cleared: world.cleared, failed: world.failed, lastAction: world.lastAction, lastHit: world.lastHit, hazards: world.level.hazards, chips: world.level.chips }, episode.finalState, 'finalState');
  invariant(Array.isArray(episode.decisions), 'measured decisions required');
  invariant(baseline || episode.decisions.some(decision => ['applied', 'completed'].includes(decision.status) && decision.response?.parsed === true), '実モデル推論成功なし / 未測定');
  return { report, episode, initialWorld: clone(episode.initialWorld), finalWorld: clone(world) };
}

export function advanceTrace(tile, elapsedMs) {
  if (!tile.trace) return;
  const target = Math.min(tile.trace.episode.frames.length, Math.floor(elapsedMs * 60 / 1000));
  while (tile.world.frame < target) step(tile.world, tile.trace.episode.frames[tile.world.frame].action);
}
