import { drawWorld } from '../js/render.js';
import { scoreOf } from '../js/engine.js';
import { validateManifest, loadMeasuredTrace, advanceTrace } from './replay.mjs';

const canvas = document.querySelector('#comparison');
const ctx = canvas.getContext('2d', { alpha: false });
const startButton = document.querySelector('#start');
const message = document.querySelector('#message');
const params = new URLSearchParams(location.search);
if (params.has('capture')) document.body.classList.add('capture');
const palette = { background: '#0b1117', panel: '#14212b', ink: '#edf3f6', muted: '#a9bdcb', accent: '#88efcd', error: '#ffc28a' };
let manifest, tiles = [], running = false, startedAt = 0, elapsedMs = 0, complete = false, raf;
let lastPaint = 0, maxPaintGapMs = 0, paintCount = 0;

function text(value, x, y, size = 22, color = palette.ink, width = 600) {
  ctx.font = `600 ${size}px system-ui, "Yu Gothic", sans-serif`;
  ctx.fillStyle = color;
  // Explicit size reduction keeps full model names readable without clipping.
  while (ctx.measureText(String(value)).width > width && size > 16) ctx.font = `600 ${--size}px system-ui, "Yu Gothic", sans-serif`;
  ctx.fillText(String(value), x, y);
}
function paint() {
  ctx.fillStyle = palette.background; ctx.fillRect(0, 0, canvas.width, canvas.height);
  text('VECTOR RUN', 28, 47, 36);
  text('Decision 2.0 · 7 models + rule + idle', 330, 46, 28, palette.muted, 850);
  text(`共通時計 ${(elapsedMs / 1000).toFixed(2)} s / ${((manifest?.durationMs ?? 15000) / 1000).toFixed(2)} s`, 1390, 45, 25, palette.accent, 510);
  text('実測trace再生 / Colab GPU  ·  同時モデル推論ではありません', 28, 87, 25, palette.accent, 1360);
  text('seed 1 · 1× · 60 Hz · 3 questions', 1410, 86, 22, palette.muted, 480);
  for (let i = 0; i < tiles.length; i++) {
    const tile = tiles[i], x = 24 + (i % 3) * 628, y = 111 + Math.floor(i / 3) * 307, w = 616, h = 295;
    ctx.fillStyle = palette.panel; ctx.fillRect(x, y, w, h);
    text(tile.label, x + 14, y + 36, 29, palette.ink, w - 28);
    if (tile.trace) {
      const gpu = (['rule', 'idle'].includes(tile.id) ? '基準 / CPU' : `Colab GPU: ${tile.trace.report.hardware.gpu ?? '未確認'}`) + (tile.trace.episode.status === 'partial' ? ' · partial' : '');
      text(gpu, x + 14, y + 63, 17, palette.muted, w - 28);
      ctx.save(); ctx.translate(x, y + 75);
      ctx.beginPath(); ctx.rect(0, 0, w, 160); ctx.clip();
      drawWorld(ctx, tile.world, w, 160); ctx.restore();
      const world = tile.world;
      const label = world.done ? (world.cleared ? 'CLEAR / 結果保持' : '終了 / 結果保持') : `RUN · action ${world.lastAction}`;
      text(label, x + 14, y + 260, 22, world.done ? palette.accent : palette.ink, 340);
      text(`f${world.frame}/${tile.trace.episode.frameCount}`, x + 432, y + 260, 20, palette.muted, 170);
      text(`score ${scoreOf(world)}  ·  HP ${world.player.hearts}  ·  hit ${world.player.hits}  ·  chip ${world.player.chips}`, x + 14, y + 284, 18, palette.muted, w - 28);
    } else {
      text(tile.error ? '検証エラー / 再生不可' : '未測定', x + 28, y + 146, 36, tile.error ? palette.error : palette.muted, w - 56);
      text(tile.error ?? tile.note ?? '実モデルtrace未着 · 代用データなし', x + 28, y + 187, 20, palette.muted, w - 56);
      text('ゲーム映像・スコアは表示しません', x + 28, y + 263, 19, palette.muted, w - 56);
    }
  }
  text('物理時計は進行し続けます · 各ゲーム終了後も結果を保持 · 推論は実測時に非同期実行', 28, 1060, 20, palette.muted, 1850);
}
function status() {
  return { running, elapsedMs, durationMs: manifest?.durationMs ?? 15000, complete, paintCount, maxPaintGapMs,
    tiles: tiles.map(tile => ({ id: tile.id, status: tile.error ? 'invalid' : tile.trace ? (tile.world.done ? 'finished' : 'measured') : 'unmeasured', frame: tile.world?.frame ?? null, finalFrame: tile.trace?.episode.frameCount ?? null, model: tile.trace?.report.model.id ?? null, seed: tile.trace?.episode.seed ?? null, error: tile.error ?? null })) };
}
function tick(now) {
  elapsedMs = now - startedAt; // Never pause or slow the common clock for a model.
  if (lastPaint) maxPaintGapMs = Math.max(maxPaintGapMs, now - lastPaint);
  lastPaint = now; paintCount++;
  for (const tile of tiles) advanceTrace(tile, elapsedMs);
  paint();
  if (elapsedMs >= manifest.durationMs) { running = false; complete = true; startButton.disabled = false; message.textContent = '再生完了。実測した最終結果を保持しています。'; }
  else raf = requestAnimationFrame(tick);
}
function start() {
  if (!manifest || running) return status();
  cancelAnimationFrame(raf);
  for (const tile of tiles) if (tile.trace) tile.world = structuredClone(tile.trace.initialWorld);
  complete = false; elapsedMs = 0; paintCount = 0; maxPaintGapMs = 0; lastPaint = 0;
  running = true; startedAt = performance.now(); startButton.disabled = true;
  message.textContent = '共通時計で実測traceを1×再生中'; raf = requestAnimationFrame(tick); return status();
}
const ready = (async () => {
  try {
    const url = new URL(params.get('manifest') ?? './capture/manifest.json', location.href);
    const response = await fetch(url); if (!response.ok) throw new Error(`manifest HTTP ${response.status}`);
    manifest = validateManifest(await response.json());
    tiles = await Promise.all(manifest.tiles.map(async spec => {
      const tile = { ...spec, trace: null, world: null };
      if (spec.result) try {
        const response = await fetch(new URL(spec.result, url));
        if (!response.ok) throw new Error(`trace HTTP ${response.status}`);
        const bytes = await response.arrayBuffer();
        if (tile.sourceSha256) {
          const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
          if (hash !== tile.sourceSha256) throw new Error('trace SHA256 mismatch');
        }
        tile.trace = loadMeasuredTrace(JSON.parse(new TextDecoder().decode(bytes)), tile, manifest); tile.world = structuredClone(tile.trace.initialWorld);
      } catch (error) { tile.error = error.message; }
      return tile;
    }));
    paint(); startButton.disabled = false;
    message.textContent = `検証済みtrace ${tiles.filter(t => t.trace).length}/9 · 未測定は静的表示`;
    return status();
  } catch (error) { message.textContent = error.message; throw error; }
})();
window.capturePlayer = { ready, start, status };
startButton.addEventListener('click', start);
