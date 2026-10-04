import { liveHazards } from "./engine.js";
import { POLICY } from "./policy.js";

const SKY = "#141816";
const HAZE = "#1d2622";
const GROUND = "#1a1c19";
const RAIL = "#c6a36a";
const INK = "#f3ecdc";
const VISOR = "#79f0dc";
const CRATE = "#d15a32";
const BEAM = "#8eabba";
const DRONE = "#e23e8c";
const CHIP = "#e2ff6a";
const PIT = "#070807";

export function drawWorld(ctx, world, width, height) {
  const camera = world.player.x - 168;
  const groundY = height * 0.72;

  ctx.fillStyle = SKY;
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = HAZE;
  ctx.fillRect(0, groundY - 150, width, 150);
  drawSkyline(ctx, camera, groundY, width);
  ctx.fillStyle = GROUND;
  ctx.fillRect(0, groundY, width, height - groundY);

  ctx.strokeStyle = RAIL;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(0, groundY);
  ctx.lineTo(width, groundY);
  ctx.stroke();

  const rivet = 28;
  ctx.fillStyle = "#8d7344";
  for (let x = -((camera % rivet) + rivet); x < width; x += rivet) {
    ctx.fillRect(x - 1, groundY + 8, 2, 6);
  }

  for (const chip of world.level.chips) {
    if (chip.taken) continue;
    const x = chip.x - camera;
    if (x < -40 || x > width + 40) continue;
    drawChip(ctx, x, groundY - chip.y - chip.h);
  }

  for (const hazard of world.level.hazards) {
    if (hazard.spent && hazard.kind !== "gap") continue;
    const x = hazard.x - camera;
    if (x < -120 || x > width + 40) continue;
    if (hazard.kind === "crate") drawCrate(ctx, x, groundY, hazard);
    else if (hazard.kind === "beam") drawBeam(ctx, x, groundY, hazard);
    else if (hazard.kind === "drone" && !hazard.spent) drawDrone(ctx, x, groundY, hazard, world.frame);
    else if (hazard.kind === "gap") drawGap(ctx, x, groundY, hazard, hazard.spent);
  }

  drawWindow(ctx, world, camera, groundY, width);
  drawRunner(ctx, world, 168, groundY);
  if (world.level.goal - camera < width + 20) drawGoal(ctx, world.level.goal - camera, groundY);
}

function drawSkyline(ctx, camera, groundY, width) {
  ctx.fillStyle = "#222a27";
  for (let index = 0; index < 18; index += 1) {
    const seed = index * 97;
    const blockW = 70 + (seed % 90);
    const blockH = 40 + (seed % 110);
    const x = ((index * 160 - camera * 0.25) % (width + 200)) - 40;
    ctx.fillRect(x, groundY - 150 - blockH + 150, blockW, blockH);
    ctx.fillStyle = "#31403a";
    for (let wy = groundY - blockH + 18; wy < groundY - 8; wy += 16) {
      ctx.fillRect(x + 10, wy, 8, 4);
    }
    ctx.fillStyle = "#222a27";
  }
}

function drawWindow(ctx, world, camera, groundY, width) {
  const nearest = liveHazards(world)[0];
  if (!nearest) return;
  const limit =
    nearest.kind === "beam" ? POLICY.slideMaxDx : nearest.kind === "drone" ? POLICY.strikeMaxDx : POLICY.jumpMaxDx;
  const x = world.player.x + limit - camera;
  if (x < 0 || x > width) return;
  ctx.strokeStyle = "rgba(226,255,106,0.45)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, groundY - 96);
  ctx.lineTo(x, groundY + 10);
  ctx.stroke();
}

function drawRunner(ctx, world, screenX, groundY) {
  const player = world.player;
  const blink = player.invuln > 0 && world.frame % 6 < 3;
  if (blink) return;
  const foot = groundY - player.y;
  ctx.save();
  ctx.translate(screenX, foot);
  ctx.fillStyle = INK;
  if (player.sliding) {
    ctx.fillRect(0, -18, 34, 14);
    ctx.fillStyle = VISOR;
    ctx.fillRect(22, -14, 10, 4);
  } else {
    const tuck = player.grounded ? 0 : 6;
    ctx.fillRect(6, -40 + tuck, 16, 24 - tuck);
    ctx.fillRect(4, -48 + tuck, 18, 10);
    ctx.fillStyle = "#2a2e28";
    ctx.fillRect(-2, -36 + tuck, 8, 14);
    ctx.fillStyle = VISOR;
    ctx.fillRect(14, -45 + tuck, 10, 4);
    ctx.strokeStyle = INK;
    ctx.lineWidth = 2;
    const step = player.grounded ? (world.frame % 12 < 6 ? 4 : -2) : 6;
    ctx.beginPath();
    ctx.moveTo(10, -16);
    ctx.lineTo(6, -2 + step);
    ctx.moveTo(18, -16);
    ctx.lineTo(22, -2 - step);
    ctx.stroke();
    if (player.striking) {
      ctx.strokeStyle = CHIP;
      ctx.beginPath();
      ctx.moveTo(22, -28);
      ctx.lineTo(22 + POLICY.strikeReach * 0.55, -24);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawCrate(ctx, x, groundY, hazard) {
  ctx.fillStyle = CRATE;
  ctx.fillRect(x, groundY - hazard.h, hazard.w, hazard.h);
  ctx.strokeStyle = "#7a2d18";
  ctx.strokeRect(x + 3, groundY - hazard.h + 3, hazard.w - 6, hazard.h - 6);
  ctx.beginPath();
  ctx.moveTo(x + 4, groundY - 4);
  ctx.lineTo(x + hazard.w - 4, groundY - hazard.h + 4);
  ctx.moveTo(x + 4, groundY - hazard.h + 4);
  ctx.lineTo(x + hazard.w - 4, groundY - 4);
  ctx.stroke();
}

function drawBeam(ctx, x, groundY, hazard) {
  ctx.strokeStyle = BEAM;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x + 8, groundY - 150);
  ctx.lineTo(x + 8, groundY - hazard.y - hazard.h);
  ctx.moveTo(x + hazard.w - 8, groundY - 150);
  ctx.lineTo(x + hazard.w - 8, groundY - hazard.y - hazard.h);
  ctx.stroke();
  ctx.fillStyle = BEAM;
  ctx.fillRect(x, groundY - hazard.y - hazard.h, hazard.w, hazard.h);
}

function drawDrone(ctx, x, groundY, hazard, frame) {
  const bob = Math.sin(frame / 6) * 2;
  const y = groundY - hazard.y - hazard.h - bob;
  ctx.fillStyle = DRONE;
  ctx.beginPath();
  ctx.moveTo(x + hazard.w / 2, y);
  ctx.lineTo(x + hazard.w, y + hazard.h / 2);
  ctx.lineTo(x + hazard.w / 2, y + hazard.h);
  ctx.lineTo(x, y + hazard.h / 2);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = "#ffd0e6";
  ctx.lineWidth = 1;
  const rotor = frame % 8 < 4 ? hazard.w + 8 : hazard.w * 0.4;
  ctx.beginPath();
  ctx.moveTo(x + hazard.w / 2 - rotor / 2, y - 3);
  ctx.lineTo(x + hazard.w / 2 + rotor / 2, y - 3);
  ctx.stroke();
}

function drawGap(ctx, x, groundY, hazard, spent) {
  ctx.fillStyle = PIT;
  ctx.fillRect(x, groundY - 1, hazard.w, 28);
  ctx.strokeStyle = spent ? "#3d4338" : "#ff5d3a";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x, groundY);
  ctx.lineTo(x + 10, groundY + 12);
  ctx.moveTo(x + hazard.w, groundY);
  ctx.lineTo(x + hazard.w - 10, groundY + 12);
  ctx.stroke();
}

function drawChip(ctx, x, y) {
  ctx.save();
  ctx.translate(x + 7, y + 7);
  ctx.rotate(Math.PI / 4);
  ctx.fillStyle = CHIP;
  ctx.fillRect(-5, -5, 10, 10);
  ctx.restore();
}

function drawGoal(ctx, x, groundY) {
  ctx.strokeStyle = "#e2ff6a";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(x, groundY);
  ctx.lineTo(x, groundY - 120);
  ctx.stroke();
  ctx.fillStyle = "#e2ff6a";
  ctx.fillRect(x, groundY - 120, 28, 16);
}
