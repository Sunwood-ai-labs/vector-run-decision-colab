"""Sequential real-GPU VECTOR RUN benchmark; launch with uv run --no-project.

The game CLI owns physics, pacing and trace format. This runner never supplies an
action or pauses the physics. No model mock or rule fallback is available here.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SERIES = (("q3", 3, 3), ("q64", 64, 1))
PACKAGES = ("torch", "transformers", "accelerate", "peft", "bitsandbytes", "sentencepiece", "protobuf", "safetensors", "tokenizers", "huggingface-hub", "triton", "causal-conv1d", "flash-linear-attention")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def public_error(error: Any) -> str:
    # Never publish VM/session identifiers, credentials or raw authentication logs.
    message = str(error)
    message = re.sub(r"hf_[A-Za-z0-9]+", "[REDACTED]", message)
    message = re.sub(r"(?i)(bearer\s+|(?:token|secret|password|api[_-]?key)[=:]\s*)[^\s,;]+", r"\1[REDACTED]", message)
    message = re.sub(r"https?://[^\s<>]+", "[URL REDACTED]", message)
    message = re.sub(r"(?:/root|/home|/tmp|/content)/[^\s:,'\"]+", "[VM PATH]", message)
    return message[:2400]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def latency_stats(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "mean_ms": sum(values) / len(values) if values else None, "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95)}


def environment(torch: Any) -> dict[str, Any]:
    versions = {}
    for package in PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    try:
        node = subprocess.check_output(["node", "--version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        node = None
    gpu = None
    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        free, total = torch.cuda.mem_get_info(0)
        gpu = {"name": properties.name, "total_memory_bytes": total, "free_memory_before_load_bytes": free, "compute_capability": f"{properties.major}.{properties.minor}", "visible_device_count": torch.cuda.device_count(), "device_index": 0}
    try:
        driver = subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True).splitlines()[0].strip()
    except (OSError, subprocess.CalledProcessError, IndexError):
        driver = None
    return {"python": platform.python_version(), "platform": "Linux Colab" if platform.system() == "Linux" else platform.system(), "node": node, "cuda": torch.version.cuda, "driver": driver, "gpu": gpu, "dependencies": versions}


def game_identity(explicit: str | None) -> dict[str, Any]:
    commit = explicit
    if not commit:
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            commit = None
    files = [ROOT / "bench.mjs", ROOT / "policy.json", *sorted((ROOT / "js").glob("*.js"))]
    return {"commit": commit, "file_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.exists()}}


def model_key(model: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(model.get("name") or model.get("id") or model["repo"]).lower()).strip("-")


def metadata(model: dict[str, Any], env: dict[str, Any], game: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {"model": {"id": model["repo"], "revision": model.get("revision"), "baseRevision": model.get("base_revision"), "baseRepo": model.get("base_repo")}, "hardware": {"gpu": env["gpu"]["name"] if env["gpu"] else None, "dtype": model.get("dtype", args.dtype), "quantization": args.quantization, "dependencies": env["dependencies"]}, "gameCommit": game["commit"]}


class MeasuredApp:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.records: list[dict[str, Any]] = []
        self.condition = threading.Condition()
        self.active = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.app, name)

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.condition:
            self.active += 1
            index = len(self.records) + 1
        started = time.perf_counter()
        record = {"index": index, "phase": "first" if index == 1 else "warm" if index == 2 else "steady", "state_frame": payload.get("state", {}).get("frame") if isinstance(payload.get("state"), dict) else None, "question_count": len(payload.get("questions", {}))}
        try:
            result = self.app.answer(payload)
            record.update({"status": "ok", **result.get("measurements", {})})
            return result
        except Exception as error:
            record.update({"status": "error", "error": public_error(error)})
            raise
        finally:
            record["server_request_ms"] = (time.perf_counter() - started) * 1000
            with self.condition:
                self.records.append(record)
                self.active -= 1
                self.condition.notify_all()

    def drain(self, timeout: float = 60) -> bool:
        with self.condition:
            return self.condition.wait_for(lambda: self.active == 0, timeout)

    def reset(self) -> None:
        if not self.drain():
            raise RuntimeError("Previous model inference is still running; refusing concurrent GPU loads")
        self.records = []


def timing_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for phase in ("first", "warm", "steady", "all"):
        subset = records if phase == "all" else [record for record in records if record["phase"] == phase]
        result[phase] = {"system_one": latency_stats([record["system_one_ms"] for record in subset if isinstance(record.get("system_one_ms"), (int, float))]), "neural_forward_ms": None, "server_request": latency_stats([record["server_request_ms"] for record in subset]), "errors": sum(record["status"] != "ok" for record in subset)}
    return result


def failure_status(error: Any) -> str:
    text = str(error).lower()
    return "oom" if "out of memory" in text or "cuda error: memory allocation" in text else "blocked"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "experiments/colab/model-manifest.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--models", nargs="*", help="Manifest name/id/repo filters; default all, strictly sequential")
    parser.add_argument("--game-commit", help="Commit of game bundle supplied by parent after realtime harness merge")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--quantization", choices=("none", "4bit", "8bit"), default="none")
    parser.add_argument("--series-timeout", type=float, default=120, help="Upper bound for each game CLI series")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    models = manifest if isinstance(manifest, list) else manifest["models"]
    if args.models:
        wanted = {value.lower() for value in args.models}
        models = [model for model in models if any(str(value).lower() in wanted for value in (model.get("name"), model.get("id"), model.get("repo")))]
        if not models:
            parser.error("No requested models matched the manifest")
    import torch
    from server.decision_server import App, load_model, make_handler

    env = environment(torch)
    game = game_identity(args.game_commit)
    harness = (ROOT / "bench.mjs").read_text(encoding="utf-8")
    gate = None
    if not env["gpu"]:
        gate = "CUDA GPU unavailable; no CPU/mock benchmark attempted"
    elif any(flag not in harness for flag in ("--timing", "--output", "--trace", "--metadata")):
        gate = "Realtime game harness has not been merged; benchmark refused"
    elif not game["commit"]:
        gate = "Exact game commit unavailable; supply --game-commit for the transferred bundle"
    fatal_drain = False
    total_errors = 0
    for entry in models:
        key = model_key(entry)
        common = metadata(entry, env, game, args)
        runtime = {"environment": env, "game": game, "condition": {"gpu": common["hardware"]["gpu"], "dtype": common["hardware"]["dtype"], "quantization": common["hardware"]["quantization"], "offload": "none", "sequential": True}, "phase_definition": "Per question series: first=request 1, warm=request 2, steady=requests 3+. No pre-benchmark inference; q64 follows q3 on the already-loaded model.", "measured_at_utc": datetime.now(timezone.utc).isoformat()}
        model = server = serving = app = None
        status, reason = "ok", None
        start = time.perf_counter()
        try:
            blocked = gate or ("Previous inference did not drain; refusing concurrent GPU loads" if fatal_drain else None)
            if entry.get("status") in ("blocked", "unavailable"):
                blocked = blocked or entry.get("blocked_reason") or "Model manifest marks model unavailable"
            minimum = entry.get("minimum_gpu_memory_bytes") or entry.get("required_gpu_memory_bytes")
            if minimum and env["gpu"] and minimum > env["gpu"]["free_memory_before_load_bytes"]:
                blocked = f"GPU memory preflight: requires {minimum} bytes; available {env['gpu']['free_memory_before_load_bytes']} bytes. No quantization/offload applied."
            if blocked:
                raise RuntimeError(blocked)
            model = load_model(entry["repo"], revision=entry.get("revision"), base_revision=entry.get("base_revision"), dtype=args.dtype, quantization=args.quantization)
            load_ms = (time.perf_counter() - start) * 1000
            app = MeasuredApp(App(model, entry["repo"], {"model_revision": entry.get("revision"), "base_revision": entry.get("base_revision"), "dtype": common["hardware"]["dtype"], "quantization": common["hardware"]["quantization"], "device": "cuda:0", "load_ms": load_ms}))
            server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
            server.daemon_threads = True
            serving = threading.Thread(target=server.serve_forever, daemon=True)
            serving.start()
            runtime["load_ms"] = load_ms
            runtime["loader_metadata"] = getattr(model, "_benchmark_metadata", {})
        except Exception as error:
            status, reason = failure_status(error), public_error(error)
            runtime["load_attempt_ms"] = (time.perf_counter() - start) * 1000
        for series, questions, seeds in SERIES:
            output = args.output_dir / f"{key}-{series}.json"
            base = {"schemaVersion": 1, **common, "series": series, "questions": questions, "seeds": list(range(1, seeds + 1)), "agent": "remote", "timing": "realtime", "status": status, "runtime": {**runtime}}
            if status != "ok":
                base.update({"error": reason, "episodes": []})
                write_json(output, base)
                total_errors += 1
                continue
            app.reset()
            torch.cuda.reset_peak_memory_stats()
            meta_path = args.output_dir / f".{key}-{series}.metadata.json"
            write_json(meta_path, common)
            command = ["node", "bench.mjs", "--agent", "remote", "--timing", "realtime", "--seeds", str(seeds), "--questions", str(questions), "--url", f"http://127.0.0.1:{args.port}/v1/systemone", "--model", entry["repo"], "--output", str(output.resolve()), "--trace", "--metadata", str(meta_path.resolve())]
            started = time.perf_counter()
            try:
                completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=args.series_timeout)
                if completed.returncode:
                    raise RuntimeError(f"Game CLI exited {completed.returncode}: {completed.stderr[-1800:]}")
                report = json.loads(output.read_text(encoding="utf-8"))
                if not isinstance(report, dict) or not report.get("episodes"):
                    raise RuntimeError("Game CLI did not emit the required episodes/trace object")
                base = {**report, "status": "ok", "series": series, "runtime": {**runtime}}
            except Exception as error:
                base.update({"status": failure_status(error), "error": public_error(error), "episodes": []})
                total_errors += 1
            finally:
                drained = app.drain()
                fatal_drain |= not drained
                base["runtime"].update({"elapsed_wall_ms": (time.perf_counter() - started) * 1000, "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(), "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(), "inference_records": list(app.records), "inference_timings": timing_summary(app.records), "inference_drained": drained, "http_ms_source": "Game trace decisions latencyMs/end-to-end HTTP timing; server_request_ms excludes client transport"})
                if any(record["status"] != "ok" for record in app.records) and base["status"] == "ok":
                    base["status"] = "completed_with_errors"
                    total_errors += 1
                if not drained:
                    status, reason = "blocked", "Inference did not drain after game CLI; next series/model skipped"
                    base["status"] = "blocked"
                    base["error"] = reason
                write_json(output, base)
                meta_path.unlink(missing_ok=True)
            print(f"{key} {series}: {base['status']}", flush=True)
        if server:
            server.shutdown()
            server.server_close()
            serving.join(timeout=2)
        if not fatal_drain:
            if app:
                app.app.model = None
            app = server = model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
