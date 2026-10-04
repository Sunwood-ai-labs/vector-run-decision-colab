import { liveHazards, dangerLevel, ruleAction } from "./engine.js";
import { ACTIONS, POLICY } from "./policy.js";

const ACTION_TEXT = [
  "Decision Lane の走者を、このティックで1つだけ動かす。",
  "dx は走者の左端から障害の左端までのピクセル。走者は右へ speed_px_per_frame で進む。",
  "jump は箱（crate）と欠線（gap）を越える。接地していて、滑り中でも打撃中でもなく、最も近い障害が crate か gap で dx が jump_dx 以下のときだけ。",
  "slide は梁（beam）の下をくぐる。接地していて、最も近い障害が beam で dx が slide_dx 以下のときだけ。",
  "strike は前方のドローンを壊す。接地していて、最も近い障害が drone で dx が strike_dx 以下のときだけ。",
  "それ以外は hold。空中、滑り中、打撃中も hold。",
  "hazards は dx の昇順。dx が -8 より大きいものの先頭が最も近い。",
].join("");

export function visibleState(world, questionCount = 3) {
  const player = world.player;
  const probes =
    questionCount > 3
      ? Array.from({ length: questionCount - 3 }, (_, index) => ((world.frame * 3 + index * 5) % 2) === 0)
      : [];
  return {
    game: "decision-lane",
    frame: world.frame,
    speed_px_per_frame: POLICY.speed,
    jump_dx: POLICY.jumpMaxDx,
    slide_dx: POLICY.slideMaxDx,
    strike_dx: POLICY.strikeMaxDx,
    lookahead: POLICY.lookahead,
    runner: {
      grounded: player.grounded,
      sliding: player.sliding,
      striking: player.striking,
      airborne: !player.grounded,
      hearts: player.hearts,
      chips: player.chips,
      height: player.h,
    },
    hazards: liveHazards(world).map((hazard) => ({
      id: hazard.id,
      kind: hazard.kind,
      dx: hazard.dx,
      width: hazard.w,
    })),
    distance_to_goal: Math.max(0, Math.round(world.level.goal - player.x)),
    probes,
  };
}

export function buildRequest(world, questionCount = 3) {
  const state = visibleState(world, questionCount);
  const questions = {
    action: {
      type: "choice",
      instructions: ACTION_TEXT,
      criteria: {
        hold: "何も始めない。ルール上 jump / slide / strike の条件を満たさないとき。",
        jump: "今ジャンプを開始する。",
        slide: "今スライディングを開始する。",
        strike: "今ストライクを開始する。",
      },
    },
    commit: {
      type: "noul",
      instructions:
        "同じルールで、このティックに jump、slide、strike のいずれかが必要か。必要なときだけ true。hold が正しいなら false。",
    },
    danger: {
      type: "score",
      instructions:
        "今の危険。0 は見通し内に障害がない。1 は障害はあるが正しい行動は hold。2 は正しい行動が jump、slide、strike のいずれか。",
      criteria: [
        "calm: no hazard inside lookahead",
        "watch: hazard visible but hold is correct",
        "now: jump, slide, or strike is required",
      ],
    },
  };
  state.probes.forEach((value, index) => {
    questions[`p${index}`] = {
      type: "noul",
      instructions: `state.probes[${index}] が true なら true、false なら false。`,
    };
    void value;
  });
  return { state, questions };
}

export function goldLabels(world, questionCount = 3) {
  const action = ruleAction(world);
  const state = visibleState(world, questionCount);
  return {
    action,
    commit: action !== "hold",
    danger: dangerLevel(world),
    probes: state.probes,
  };
}

export function readDecision(payload) {
  const answers = payload?.answers ?? {};
  const choice = answers.action?.choice;
  const action = ACTIONS.includes(choice) ? choice : "hold";
  const probabilities = answers.action?.probabilities ?? null;
  const noul = answers.commit?.noul;
  const commit = typeof noul === "number" ? noul >= 0.5 : null;
  const score = answers.danger?.score;
  const danger = typeof score === "number" ? Math.max(0, Math.min(2, Math.round(score))) : null;
  let probeHits = 0;
  let probeTotal = 0;
  for (const key of Object.keys(answers)) {
    if (!/^p\d+$/.test(key)) continue;
    probeTotal += 1;
    const expected = payload?.state?.probes?.[Number(key.slice(1))];
    const got = answers[key]?.noul;
    if (typeof expected === "boolean" && typeof got === "number" && (got >= 0.5) === expected) {
      probeHits += 1;
    }
  }
  return {
    action,
    probabilities,
    commit,
    danger,
    confidence: answers.action?.confidence ?? null,
    probeHits,
    probeTotal,
    parsed: ACTIONS.includes(choice),
    model: payload?.model ?? null,
    usage: payload?.usage ?? null,
  };
}

export function scoreSample(gold, got) {
  return {
    actionMatch: got.action === gold.action,
    commitMatch: got.commit == null ? null : got.commit === gold.commit,
    dangerError: got.danger == null ? null : Math.abs(got.danger - gold.danger),
    consistent: got.commit == null ? null : got.commit === (got.action !== "hold"),
  };
}
