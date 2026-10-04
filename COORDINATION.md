# VECTOR RUN benchmark coordination

Parent owns README.md, docs summary, public GitHub publication and integration.
Three ordinary parallel T3 threads each have a T3-bound independent Git worktree.

## Shared measurement contract
- Preserve physics and existing seeded courses. Name the game VECTOR RUN.
- Actions: hold, jump, slide, strike. 60 physics frames/second, decision opportunity each 8 frames, one outstanding inference, no reflex assistance or action candidate restriction.
- Real-time is required: inference runs asynchronously while physics continues. Apply returned action once at the next physics frame; do not repeat jump/strike commands. Record dispatch frame, completion frame, application frame, end-to-end latency, skipped opportunities, errors and actual frame/action/state trace.
- Model GPU inference can be sequential to avoid resource contention; comparisons use identical seeds, settings, hardware and actual real-time pacing. Do not claim simultaneous inference from a montage.
- Primary benchmark: 3 questions, seeds 1,2,3. 64-question stress uses the same configuration for seed 1, separately reported.
- Result file format: versioned JSON, model/revision/base revision, GPU/dtype/quantization/dependencies, game commit, elapsed wall time, episode summary and frames/decisions sufficient for replay. Failure and unavailable models must be explicit, never replaced with mocks.
- CLI ownership harness thread: bench.mjs --agent remote --timing realtime --seeds 3 --questions 3 --url http://127.0.0.1:8780/v1/systemone --model MODEL --output FILE --trace. Baselines use --agent rule|idle with same timing/output/trace.
- Colab worker owns model loader/server integration and notebooks, experiments/colab, results/*.json. No credentials, notebook outputs with session identifiers, weights or raw authentication logs in public repo.
- Video worker owns capture/, comparison.html, scripts/capture*, videos/. 3x3 tiles: Kai, Eos, Sol, Sol-Reasoning, Nox, Lux, Vega, rule, idle. Model-only real measured traces at 1x, clear labels for replay and unavailable cells; never show a rule fallback as a model. Capture a real-time browser replay of measured traces when simultaneous live model capture is impractical. This records measured decisions; it is not renewed simultaneous inference. Public MP4 + representative PNG + ffprobe/full-decode QA required.
- All thread owners commit only owned files, report commit SHA plus concise validation/results. Parent merges. Do not push or create PRs independently.
