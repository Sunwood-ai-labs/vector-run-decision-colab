import { ACTIONS, POLICY } from "./policy.js";

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function generateLevel(seed) {
  const rng = mulberry32(seed || 1);
  const kinds = ["crate", "beam", "drone", "gap"];
  const hazards = [];
  const chips = [];
  let x = POLICY.firstHazard;
  let index = 0;
  while (x < POLICY.goal - 420) {
    const kind = kinds[Math.floor(rng() * kinds.length)];
    const hazard = { id: `h${index}`, kind, x, spent: false };
    if (kind === "crate") {
      hazard.w = POLICY.crate.w;
      hazard.h = POLICY.crate.h;
    } else if (kind === "beam") {
      hazard.w = POLICY.beam.w;
      hazard.y = POLICY.beam.bottom;
      hazard.h = POLICY.beam.h;
    } else if (kind === "drone") {
      hazard.w = POLICY.drone.w;
      hazard.h = POLICY.drone.h;
      hazard.y = POLICY.drone.y;
      hazard.vx = POLICY.drone.vx;
    } else {
      hazard.w = POLICY.gapW;
      hazard.h = 0;
    }
    hazards.push(hazard);
    if (rng() < 0.62 && kind !== "gap") {
      chips.push({
        id: `c${index}`,
        x: x - 130,
        y: POLICY.chip.y,
        w: POLICY.chip.w,
        h: POLICY.chip.h,
        taken: false,
      });
    }
    index += 1;
    x += POLICY.spacingMin + Math.floor(rng() * POLICY.spacingSpan);
  }
  return { seed: seed || 1, goal: POLICY.goal, hazards, chips };
}

export function createWorld(seed, overrides = {}) {
  const level = overrides.level ?? generateLevel(seed);
  return {
    seed: seed || 1,
    frame: 0,
    level,
    done: false,
    cleared: false,
    failed: false,
    lastAction: "hold",
    lastHit: null,
    player: {
      x: 48,
      y: 0,
      vy: 0,
      w: POLICY.playerW,
      h: POLICY.playerH,
      grounded: true,
      sliding: false,
      slideLeft: 0,
      striking: false,
      strikeLeft: 0,
      hearts: POLICY.hearts,
      chips: 0,
      hits: 0,
      invuln: 0,
    },
  };
}

export function liveHazards(world) {
  const origin = world.player.x;
  return world.level.hazards
    .filter((hazard) => !hazard.spent)
    .map((hazard) => ({ ...hazard, dx: hazard.x - origin }))
    .filter((hazard) => hazard.dx > -8 && hazard.dx <= POLICY.lookahead)
    .sort((a, b) => a.dx - b.dx || a.id.localeCompare(b.id));
}

export function ruleAction(world) {
  const player = world.player;
  if (!player.grounded || player.sliding || player.striking) return "hold";
  const nearest = liveHazards(world)[0];
  if (!nearest) return "hold";
  if ((nearest.kind === "crate" || nearest.kind === "gap") && nearest.dx <= POLICY.jumpMaxDx) {
    return "jump";
  }
  if (nearest.kind === "beam" && nearest.dx <= POLICY.slideMaxDx) return "slide";
  if (nearest.kind === "drone" && nearest.dx <= POLICY.strikeMaxDx) return "strike";
  return "hold";
}

export function dangerLevel(world) {
  const nearest = liveHazards(world)[0];
  if (!nearest) return 0;
  return ruleAction(world) === "hold" ? 1 : 2;
}

function boxesOverlap(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

function playerBox(player) {
  return { x: player.x, y: player.y, w: player.w, h: player.h };
}

function hurt(world, hazard, dx) {
  hazard.spent = true;
  if (world.player.invuln > 0) return;
  world.player.hits += 1;
  world.player.hearts -= 1;
  world.player.invuln = POLICY.invulnFrames;
  world.lastHit = {
    kind: hazard.kind,
    id: hazard.id,
    dx,
    frame: world.frame,
    action: world.lastAction,
  };
  if (world.player.hearts <= 0) {
    world.done = true;
    world.failed = true;
  }
}

export function step(world, action) {
  if (world.done) return world;
  const player = world.player;
  const act = ACTIONS.includes(action) ? action : "hold";
  world.lastAction = act;

  if (player.grounded && !player.sliding && !player.striking) {
    if (act === "jump") {
      player.vy = POLICY.jumpV;
      player.grounded = false;
    } else if (act === "slide") {
      player.sliding = true;
      player.slideLeft = POLICY.slideFrames;
      player.h = POLICY.slideH;
    } else if (act === "strike") {
      player.striking = true;
      player.strikeLeft = POLICY.strikeFrames;
    }
  }

  player.x += POLICY.speed;
  if (!player.grounded) {
    player.y += player.vy;
    player.vy -= POLICY.gravity;
    if (player.y <= 0) {
      player.y = 0;
      player.vy = 0;
      player.grounded = true;
    }
  }

  for (const hazard of world.level.hazards) {
    if (hazard.kind === "drone" && !hazard.spent) hazard.x += hazard.vx;
  }

  const body = playerBox(player);
  for (const hazard of world.level.hazards) {
    if (hazard.spent) continue;
    const dx = hazard.x - player.x;
    if (hazard.kind === "gap") {
      const center = player.x + player.w / 2;
      if (player.grounded && player.y <= 0 && center > hazard.x && center < hazard.x + hazard.w) {
        hurt(world, hazard, dx);
      }
      continue;
    }
    const box =
      hazard.kind === "crate"
        ? { x: hazard.x, y: 0, w: hazard.w, h: hazard.h }
        : { x: hazard.x, y: hazard.y, w: hazard.w, h: hazard.h };
    if (hazard.kind === "drone" && player.striking) {
      const strike = {
        x: player.x + player.w,
        y: player.y + 8,
        w: POLICY.strikeReach,
        h: 28,
      };
      if (boxesOverlap(strike, box)) {
        hazard.spent = true;
        hazard.killed = true;
        continue;
      }
    }
    if (boxesOverlap(body, box)) hurt(world, hazard, dx);
  }

  for (const chip of world.level.chips) {
    if (chip.taken) continue;
    if (boxesOverlap(body, chip)) {
      chip.taken = true;
      player.chips += 1;
    }
  }

  if (player.sliding) {
    player.slideLeft -= 1;
    if (player.slideLeft <= 0) {
      player.sliding = false;
      player.h = POLICY.playerH;
    }
  }
  if (player.striking) {
    player.strikeLeft -= 1;
    if (player.strikeLeft <= 0) player.striking = false;
  }
  if (player.invuln > 0) player.invuln -= 1;

  if (player.x >= world.level.goal) {
    world.done = true;
    world.cleared = true;
  }
  world.frame += 1;
  if (world.frame > 4000) world.done = true;
  return world;
}

export function scoreOf(world) {
  return Math.round(world.player.x + world.player.chips * 40 - world.player.hits * 120);
}
