# Colab benchmark coordination

Final user scope: existing external VECTOR RUN game, notebook-centred public benchmark repository, official Google Colab CLI, one model per parallel thread/worktree/runtime, GPT-6-Luna with max reasoning for worker runs, real-time 3x3 video.

- Canonical game: https://github.com/Sunwood-ai-labs/vector-run-benchmark . Game source, 120Hz physics, jump/release input, structured visible observation, headless benchmark and video capture belong to that repository. Never copy/vendor a second game into the notebook repository.
- Benchmark repository: https://github.com/Sunwood-ai-labs/vector-run-decision-colab . It owns notebooks, audited model registry/loader, Colab CLI orchestration, result JSON and MP4/PNG verification artifacts.
- Previous local Decision Lane prototype at 87d41b9904b20b298467caa7cc892500959f7c65 is excluded from all formal VECTOR RUN scores/videos. Its original source is preserved in Git history and an external backup. Prototype model traces remain private/untracked.
- Game integration owner: canonical game branch bench/colab-realtime-api; recorder owner: game branch bench/colab-tiled-capture. Their shared interface/commit is handoffs/canonical-game.json; missing measurementCommit means measurement is forbidden.
- Notebook/core owner: branch bench/notebook-canonical, notebooks/*, experiments/colab/*, server/*, CI/tests and removal of obsolete copied game/capture/baseline files. Parent owns README.md, NOTICE.md, COORDINATION.md, final report/publication/integration.
- Each model worker owns experiments/models/<slug>/*, docs/models/<slug>.md and results/<slug>/*.json; no credentials, Colab identifiers, weights, authentication logs or prototype results in Git.
- Formal model input: JSON of currently visible game state plus Japanese question instructions. No hidden future course state, teacher/gold labels or reflex override. This is structured-visible-state-v1, a distinct pipeline from pixel observations.
- Preserve actual Engine/RealtimeClock semantics: 120Hz physics, decision opportunity every 16 ticks, one outstanding inference, apply returned wait/jump/release once after receipt, no pause. Clock gaps above 100ms invalidate a run under the game protocol.
- Primary comparison: double-jump rule, seeds 101/202/303/404/505, 3 questions. Stress: seed101, 64 questions. Endless game max30seconds is censored survival, never a clear or a completed collision benchmark.
- Save game and benchmark commits, source file hashes, model/base revisions, GPU, mixed BF16/FP32 loading, dependency versions, end-to-end/system_one timing scope, actual neural forward count/batch shapes, every model reply including post-terminal replies, input application ticks and replay/final-state proof.
- Dedicated Colab runtimes only; never stop unrelated sessions. Quota/entitlement failures are bounded and logged accurately. On completion download/verify results, stop that dedicated runtime, notify parent for slot reuse.
- 3x3 video is equal-speed playback capture of individually measured canonical game traces, with the seven models plus rule/idle. Same seed101/common clock, terminal tiles held, missing/invalid cells explicit, no rule fallback. It is not synchronized simultaneous model inference. Require replay consistency, real wall-clock capture, ffprobe, full decode and representative-frame visual QA.
- Workers commit only owned files and send short commit/interface/results/limitations reports. Parent handles push and any PR publication/registration. No long logs or source dumps in final reports.

