"""Run one pinned Decision 2.0 model against the separately pinned game CLI."""
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
import shutil
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
GAME_REPOSITORY = "https://github.com/Sunwood-ai-labs/vector-run-benchmark"
GAME_CLI = Path("scripts/decision-bench.mjs")
HANDOFF = ROOT / "handoffs/canonical-game.json"
SERIES = (("q3", 3, (101, 202, 303, 404, 505)), ("q64", 64, (101,)))
MAX_SECONDS = 30
MAX_JUMPS = 2
WINDOW_SECONDS = 1.0
NODE_VERSION = "v24.15.0"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
READY_STATUS = "ready_for_measurement"
EXPECTED_Q3_KEYS = ("action", "commit", "danger")
EXPECTED_QUESTION_KEYS = ("action", "commit", "danger", *(f"p{i}" for i in range(61)))
RUNTIME_HISTORY_FIELDS = (
    "runtimeReused", "weightsCached", "priorModelLoaded", "priorSystemOneCall",
    "priorInference", "priorPrototypeGameRun",
)
PACKAGES = (
    "torch", "transformers", "accelerate", "peft", "bitsandbytes", "sentencepiece",
    "protobuf", "safetensors", "tokenizers", "huggingface-hub", "triton",
    "causal-conv1d", "flash-linear-attention",
)


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value.lower()) is not None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def public_error(error: Any) -> str:
    """Keep result errors useful while removing credentials, URLs and VM paths."""
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
    return {
        "count": len(values),
        "mean_ms": sum(values) / len(values) if values else None,
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
    }


def environment(torch: Any | None, probe_gpu: bool = True) -> dict[str, Any]:
    versions: dict[str, str | None] = {}
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
    cuda = None
    gpu_probe_error = None
    if torch is not None and probe_gpu:
        try:
            cuda = torch.version.cuda
            if torch.cuda.is_available():
                properties = torch.cuda.get_device_properties(0)
                free, total = torch.cuda.mem_get_info(0)
                gpu = {
                    "name": properties.name,
                    "total_memory_bytes": total,
                    "free_memory_before_load_bytes": free,
                    "compute_capability": f"{properties.major}.{properties.minor}",
                    "visible_device_count": torch.cuda.device_count(),
                    "device_index": 0,
                }
        except Exception as error:
            gpu_probe_error = public_error(error)
    if probe_gpu:
        try:
            driver = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True
            ).splitlines()[0].strip()
        except (OSError, subprocess.CalledProcessError, IndexError):
            driver = None
    else:
        driver = None
    return {
        "python": platform.python_version(),
        "platform": "Linux Colab" if platform.system() == "Linux" else platform.system(),
        "node": node,
        "cuda": cuda,
        "gpu_probe_error": gpu_probe_error,
        "driver": driver,
        "gpu": gpu,
        "dependencies": versions,
    }


def model_key(model: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(model.get("name") or model.get("id") or model["repo"]).lower()).strip("-")


def select_model(models: list[dict[str, Any]], requested: str) -> dict[str, Any]:
    wanted = requested.strip().lower()
    for model in models:
        aliases = {model_key(model), str(model.get("name", "")).lower(), str(model.get("id", "")).lower(), str(model.get("repo", "")).lower()}
        if wanted in aliases:
            return model
    raise ValueError(f"Model {requested!r} did not match the audited model manifest")


def run_contract(handoff: dict[str, Any], series: str, questions: int, seeds: tuple[int, ...]) -> dict[str, Any]:
    return {
        "physicsHz": handoff.get("physicsHz"),
        "decisionEveryTicks": handoff.get("decisionEveryTicks"),
        "actions": handoff.get("actions"),
        "observationPipeline": handoff.get("observationPipeline"),
        "series": series,
        "questions": questions,
        "questionCountPerApiCall": questions,
        "seeds": list(seeds),
        "maxSeconds": MAX_SECONDS,
        "maxJumps": MAX_JUMPS,
        "runKind": "endless_time_capped",
        "timeLimitClassification": "censored; never a clear or completed collision benchmark",
    }


def validate_handoff(handoff: Any, game_commit: str) -> list[str]:
    reasons: list[str] = []
    if not isinstance(handoff, dict):
        return ["canonical game handoff must be a JSON object"]
    game = handoff.get("game") if isinstance(handoff.get("game"), dict) else {}
    repository = str(game.get("repo") or handoff.get("repository", "")).removesuffix(".git").rstrip("/")
    expected_repository = GAME_REPOSITORY.removesuffix(".git").rstrip("/")
    if repository.lower() != expected_repository.lower():
        reasons.append("canonical game handoff repository does not match vector-run-benchmark")

    status_values = (handoff.get("status"), game.get("status"))
    if READY_STATUS not in status_values:
        reasons.append(f"canonical game handoff status must explicitly be {READY_STATUS!r} after game CLI review")
    nested_measurement_commit = game.get("measurementCommit")
    root_measurement_commit = handoff.get("measurementCommit")
    if nested_measurement_commit and root_measurement_commit and str(nested_measurement_commit).lower() != str(root_measurement_commit).lower():
        reasons.append("root and game measurementCommit values disagree")
    measurement_commit = nested_measurement_commit or root_measurement_commit
    if measurement_commit is None:
        reasons.append("canonical game handoff measurementCommit is null; measurement is prohibited")
    elif not valid_sha(measurement_commit):
        reasons.append("canonical game handoff measurementCommit is not a 40-character commit SHA")
    elif measurement_commit.lower() != game_commit.lower():
        reasons.append("--game-commit does not match canonical game handoff measurementCommit")

    wire = handoff.get("wireContract")
    if not isinstance(wire, dict):
        reasons.append("canonical game handoff is missing the finalized wireContract")
    else:
        top_level_keys = wire.get("requestExactTopLevelKeys", ())
        if (
            not isinstance(top_level_keys, (list, tuple))
            or len(top_level_keys) != 3
            or not all(isinstance(key, str) for key in top_level_keys)
            or set(top_level_keys) != {"model", "state", "questions"}
        ):
            reasons.append("wireContract request top-level keys are not the approved model/state/questions envelope")
        question_keys = wire.get("questionKeysExact", ())
        if not isinstance(question_keys, (list, tuple)) or tuple(question_keys) != EXPECTED_QUESTION_KEYS:
            reasons.append("wireContract question keys do not match q3 action/commit/danger plus p0-p60")
        question_semantics = wire.get("questionsPerCall")
        if not isinstance(question_semantics, dict) or question_semantics != {
            "flagMeaning": "simultaneous_questions_per_api_call",
            "q3": list(EXPECTED_Q3_KEYS),
            "q64": list(EXPECTED_QUESTION_KEYS),
        }:
            reasons.append("wireContract questionsPerCall must exactly map q3 and q64 question IDs per API call")
        request_shape = wire.get("requestShape")
        questions_shape = request_shape.get("questions") if isinstance(request_shape, dict) else None
        state_shape = request_shape.get("state") if isinstance(request_shape, dict) else None
        response_shape = wire.get("responseShape", {}).get("answers") if isinstance(wire.get("responseShape"), dict) else None
        action = questions_shape.get("action") if isinstance(questions_shape, dict) else None
        commit = questions_shape.get("commit") if isinstance(questions_shape, dict) else None
        danger = questions_shape.get("danger") if isinstance(questions_shape, dict) else None
        probes = questions_shape.get("p0..p60") if isinstance(questions_shape, dict) else None
        if not isinstance(state_shape, dict) or state_shape.get("schema") != "vector-run-visible-state/v1":
            reasons.append("wireContract request must use the finalized visible-state schema")
        action_criteria = action.get("criteria") if isinstance(action, dict) else None
        if not isinstance(action, dict) or action.get("type") != "choice" or not isinstance(action_criteria, dict) or set(action_criteria) != {"wait", "jump", "release"}:
            reasons.append("wireContract action question must be choice with wait/jump/release criteria")
        elif not isinstance(action.get("instructions"), str) or not action["instructions"].strip() or not all(isinstance(text, str) and text.strip() for text in action_criteria.values()):
            reasons.append("wireContract action must include nonempty instructions and criteria")
        if not isinstance(commit, dict) or commit.get("type") != "noul":
            reasons.append("wireContract commit question must use noul")
        elif not isinstance(commit.get("instructions"), str) or not commit["instructions"].strip():
            reasons.append("wireContract commit question must include nonempty instructions")
        if not isinstance(danger, dict) or danger.get("type") != "score":
            reasons.append("wireContract danger question must use score")
        elif not isinstance(danger.get("criteria"), list) or len(danger["criteria"]) != 3 or not all(isinstance(value, str) and value.strip() for value in danger["criteria"]):
            reasons.append("wireContract danger question must define its three score criteria")
        elif not isinstance(danger.get("instructions"), str) or not danger["instructions"].strip():
            reasons.append("wireContract danger question must include nonempty instructions")
        if not isinstance(probes, dict) or probes.get("type") != "noul":
            reasons.append("wireContract p0-p60 probes must use noul")
        elif not isinstance(probes.get("instructions"), str) or not probes["instructions"].strip():
            reasons.append("wireContract p0-p60 probes must include nonempty instructions")
        if not isinstance(response_shape, dict):
            reasons.append("wireContract is missing the finalized responseShape.answers")
        else:
            if not isinstance(response_shape.get("action"), dict) or not {"choice", "probabilities"}.issubset(response_shape["action"]):
                reasons.append("wireContract response must include answers.action.choice and probabilities")
            if not isinstance(response_shape.get("commit"), dict) or "noul" not in response_shape["commit"]:
                reasons.append("wireContract response must include answers.commit.noul")
            if not isinstance(response_shape.get("danger"), dict) or "score" not in response_shape["danger"]:
                reasons.append("wireContract response must include answers.danger.score")
            if not isinstance(response_shape.get("p0..p60"), dict) or "noul" not in response_shape["p0..p60"]:
                reasons.append("wireContract response must include answers.p0..p60.noul")

    public_state = handoff.get("publicState")
    forbidden = public_state.get("forbiddenFromModelRequest") if isinstance(public_state, dict) else None
    if not isinstance(public_state, dict) or public_state.get("schema") != "vector-run-visible-state/v1":
        reasons.append("canonical game handoff is missing the finalized public visible-state schema")
    elif not isinstance(forbidden, list) or not all(isinstance(field, str) for field in forbidden) or not {"seed", "rng", "nextEncounter", "encounterTime"}.issubset(set(forbidden)):
        reasons.append("public-state handoff must explicitly forbid seed/RNG/future encounter fields")

    result_draft = handoff.get("resultDraft")
    if not isinstance(result_draft, dict) or not isinstance(result_draft.get("schema"), str) or not result_draft.get("schema", "").strip():
        reasons.append("canonical game handoff is missing a finalized resultDraft schema")
    else:
        if result_draft.get("validationStatus") != "passed":
            reasons.append("resultDraft validationStatus must be passed by the game trace validator")
        validator = result_draft.get("validator")
        if not isinstance(validator, dict) or validator.get("status") != "passed" or not isinstance(validator.get("command"), str) or not validator["command"].strip():
            reasons.append("resultDraft must identify a passed trace validator and its command")
    return reasons


def validate_runtime_history(value: Any, expected_model: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(value, dict):
        return None, ["runtime history must be a JSON object"]
    reasons: list[str] = []
    if str(value.get("model", "")).lower() != expected_model.lower():
        reasons.append("runtime history model does not match the selected model")
    for field in RUNTIME_HISTORY_FIELDS:
        if field not in value or not (isinstance(value[field], bool) or value[field] is None):
            reasons.append(f"runtime history {field} must be true, false, or null for unknown")
    evidence = value.get("evidence")
    if not isinstance(evidence, dict):
        reasons.append("runtime history must include an evidence object for every history field")
    else:
        for field in RUNTIME_HISTORY_FIELDS:
            if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                reasons.append(f"runtime history evidence for {field} must be a nonempty note")
            elif isinstance(value.get(field), bool) and evidence[field].strip().lower().startswith("unknown"):
                reasons.append(f"runtime history evidence for {field} cannot be unknown when its value is boolean")
    if reasons:
        return None, reasons
    return {key: value[key] for key in ("model", *RUNTIME_HISTORY_FIELDS, "evidence")}, []


def _directory_snapshot(path: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"present": path.is_dir(), "fileCount": None, "bytes": None, "scanError": None}
    if not snapshot["present"]:
        return snapshot
    count = 0
    total_bytes = 0
    try:
        for root, _directories, files in os.walk(path, followlinks=False):
            for name in files:
                try:
                    total_bytes += (Path(root) / name).stat().st_size
                    count += 1
                except OSError:
                    continue
        snapshot.update({"fileCount": count, "bytes": total_bytes})
    except OSError as error:
        snapshot["scanError"] = public_error(error)
    return snapshot


def weight_cache_observation(model: dict[str, Any]) -> dict[str, Any]:
    hf_home = Path(os.environ.get("HF_HOME") or (Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "huggingface"))
    hub_cache = Path(os.environ.get("HF_HUB_CACHE") or (hf_home / "hub")).expanduser()
    repo_cache_name = "models--" + str(model["repo"]).replace("/", "--")
    snapshot = hub_cache / repo_cache_name / "snapshots" / str(model["revision"])
    return {"pinnedSnapshot": _directory_snapshot(snapshot), "downloadActivity": "unknown; Hub transfer events are not observed by this runner"}


def runtime_cache_observation() -> dict[str, Any]:
    home = Path.home()
    configured = {
        "cudaCompiler": Path(os.environ.get("CUDA_CACHE_PATH") or (home / ".nv" / "ComputeCache")).expanduser(),
        "triton": Path(os.environ.get("TRITON_CACHE_DIR") or (home / ".triton" / "cache")).expanduser(),
        "torchExtensions": Path(os.environ.get("TORCH_EXTENSIONS_DIR") or (home / ".cache" / "torch_extensions")).expanduser(),
        "torchInductor": Path(os.environ.get("TORCHINDUCTOR_CACHE_DIR") or (home / ".cache" / "torch" / "inductor")).expanduser(),
    }
    return {
        name: _directory_snapshot(path)
        for name, path in configured.items()
    } | {"warmHistory": "unknown; directory presence does not prove cache hits or exact warm duration"}


def git_value(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=path, text=True, stderr=subprocess.STDOUT).strip()


def checkout_reasons(path: Path, expected_commit: str, label: str, expected_repository: str | None = None) -> list[str]:
    reasons: list[str] = []
    if not path.is_dir():
        return [f"{label} checkout directory does not exist"]
    try:
        actual = git_value(path, "rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return [f"{label} path is not a readable Git checkout"]
    if actual.lower() != expected_commit.lower():
        reasons.append(f"{label} HEAD does not match its immutable commit pin")
    try:
        if git_value(path, "status", "--porcelain"):
            reasons.append(f"{label} checkout has uncommitted or untracked files")
    except (OSError, subprocess.CalledProcessError):
        reasons.append(f"{label} Git working tree status could not be verified")
    if expected_repository:
        try:
            origin = git_value(path, "remote", "get-url", "origin").removesuffix(".git").rstrip("/")
            wanted = expected_repository.removesuffix(".git").rstrip("/")
            if origin.lower() != wanted.lower():
                reasons.append(f"{label} origin is not the expected external repository")
        except (OSError, subprocess.CalledProcessError):
            reasons.append(f"{label} origin could not be verified")
    return reasons


def metadata_for(
    model: dict[str, Any], env: dict[str, Any], args: argparse.Namespace,
    contract: dict[str, Any], runtime_history: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": {
            "id": model["repo"],
            "revision": model.get("revision"),
            "baseRevision": model.get("base_revision"),
            "baseRepo": model.get("base_repo"),
            "originRepo": model.get("origin_repo"),
            "originRevision": model.get("origin_revision"),
            "sourceAudit": {
                key: model.get(key)
                for key in (
                    "manifest_sha256", "model_identity_sha256", "remote_code_sha256",
                    "runtime_api_sha256", "files_sha256", "profile",
                )
                if key in model
            },
        },
        "hardware": {
            "gpu": env["gpu"]["name"] if env.get("gpu") else None,
            "dtype": model.get("dtype", args.dtype),
            "quantization": args.quantization,
            "dependencies": env.get("dependencies", {}),
        },
        "gameCommit": args.game_commit,
        "benchmarkCommit": args.benchmark_commit,
        "runContract": contract,
        "runtimeHistory": runtime_history,
    }


def blocked_report(
    model: dict[str, Any],
    metadata: dict[str, Any],
    env: dict[str, Any],
    series: str,
    questions: int,
    seeds: tuple[int, ...],
    runtime_history: dict[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "runnerSchemaVersion": 1,
        "runnerStatus": "blocked",
        "aggregateMeasurementStatus": "not_aggregated",
        "reason": "; ".join(reasons),
        "model": {"id": model.get("repo"), "revision": model.get("revision"), "baseRevision": model.get("base_revision")},
        "metadata": metadata,
        "runtimeHistory": runtime_history,
        "contract": {
            "series": series,
            "questions": questions,
            "questionCountPerApiCall": questions,
            "seeds": list(seeds),
            "maxSeconds": MAX_SECONDS,
            "maxJumps": MAX_JUMPS,
            "runKind": "endless_time_capped",
            "timeLimitClassification": "censored; never a clear or completed collision benchmark",
        },
        "runtime": {"environment": env, "inferenceRecords": [], "inferenceDrained": True},
    }


def write_blocked_reports(
    output_dir: Path,
    model: dict[str, Any],
    env: dict[str, Any],
    args: argparse.Namespace,
    handoff: dict[str, Any],
    runtime_history: dict[str, Any],
    reasons: list[str],
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for series, questions, seeds in SERIES:
        contract = run_contract(handoff, series, questions, seeds)
        metadata = metadata_for(model, env, args, contract, runtime_history)
        output = output_dir / f"{model_key(model)}-{series}.runner.json"
        write_json(output, blocked_report(model, metadata, env, series, questions, seeds, runtime_history, reasons))
        outputs.append(output)
    return outputs


class MeasuredApp:
    """Capture every transport request and model reply, including late replies."""
    def __init__(self, app: Any) -> None:
        self.app = app
        self.records: list[dict[str, Any]] = []
        self.condition = threading.Condition()
        self.active = 0
        self.series = ""
        self.series_started = time.perf_counter()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.app, name)

    def begin_series(self, series: str, timeout: float = 900) -> None:
        if not self.drain(timeout):
            raise RuntimeError("Previous model inference is still running; refusing to continue")
        self.series = series
        self.series_started = time.perf_counter()
        self.records = []

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.condition:
            self.active += 1
            index = len(self.records) + self.active
        started = time.perf_counter()
        record: dict[str, Any] = {
            "index": index,
            "phase": "first" if index == 1 else "warm" if index == 2 else "steady",
            "firstApiCallOfSeries": index == 1,
            "firstApiCallAfterModelLoad": self.series == "q3" and index == 1,
            "series": self.series,
            "windowIndex1s": max(0, int((started - self.series_started) // WINDOW_SECONDS)),
            "windowSeconds": WINDOW_SECONDS,
            "questionCount": len(payload.get("questions", {})) if isinstance(payload, dict) and isinstance(payload.get("questions"), dict) else None,
            "request": payload,
        }
        try:
            if hasattr(self.app, "answer_with_raw"):
                response, raw_response = self.app.answer_with_raw(payload)
                record["modelResponse"] = raw_response
            else:
                response = self.app.answer(payload)
                record["modelResponse"] = None
            record["response"] = response
            record.update({"status": "ok", **response.get("measurements", {})})
            answer_errors = {
                key: public_error(value["error"])
                for key, value in response.get("answers", {}).items()
                if isinstance(value, dict) and value.get("error")
            }
            if answer_errors:
                record.update({"status": "answer_error", "answerErrors": answer_errors})
            return response
        except Exception as error:
            record.update({"status": "error", "error": public_error(error)})
            raise
        finally:
            record["serverRequestMs"] = (time.perf_counter() - started) * 1000
            with self.condition:
                self.records.append(record)
                self.active -= 1
                self.condition.notify_all()

    def drain(self, timeout: float = 60) -> bool:
        with self.condition:
            return self.condition.wait_for(lambda: self.active == 0, timeout)


def timing_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    def stats(subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "systemOne": latency_stats([r["system_one_ms"] for r in subset if isinstance(r.get("system_one_ms"), (int, float))]),
            "serverRequest": latency_stats([r["serverRequestMs"] for r in subset if isinstance(r.get("serverRequestMs"), (int, float))]),
            "errors": sum(r.get("status") != "ok" for r in subset),
        }

    phases = {phase: stats([r for r in records if r.get("phase") == phase]) for phase in ("first", "warm", "steady")}
    phases["all"] = stats(records)
    windows: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        windows.setdefault(int(record.get("windowIndex1s", 0)), []).append(record)
    phases["windows1s"] = [
        {"index": index, "startMs": index * 1000, "endMs": (index + 1) * 1000, **stats(subset)}
        for index, subset in sorted(windows.items())
    ]
    return phases


def run_record(
    status: str,
    model: dict[str, Any],
    metadata: dict[str, Any],
    contract: dict[str, Any],
    env: dict[str, Any],
    runtime: dict[str, Any],
    runtime_history: dict[str, Any],
) -> dict[str, Any]:
    return {
        "runnerSchemaVersion": 1,
        "runnerStatus": status,
        "aggregateMeasurementStatus": "not_aggregated",
        "model": {"id": model.get("repo"), "revision": model.get("revision"), "baseRevision": model.get("base_revision")},
        "metadata": metadata,
        "contract": contract,
        "runtimeHistory": runtime_history,
        "runtime": {"environment": env, **runtime},
    }


def game_report_status(report: Any, json_status: str) -> dict[str, Any]:
    """Capture game-owned status fields without interpreting them as benchmark success."""
    counts: dict[str, dict[str, int]] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                normalized = re.sub(r"[^a-z]", "", str(key).lower())
                if normalized.endswith("status") and isinstance(child, (str, int, float, bool)):
                    by_value = counts.setdefault(child_path, {})
                    status_value = str(child)
                    by_value[status_value] = by_value.get(status_value, 0) + 1
                visit(child, child_path)
        elif isinstance(value, list):
            for child in value:
                visit(child, f"{path}[]")

    if json_status == "valid":
        visit(report, "$")
    fields = [
        {"path": path, "valueCounts": dict(sorted(values.items()))}
        for path, values in sorted(counts.items())
    ]
    if json_status != "valid":
        assessment = "report_not_valid_json"
    elif fields:
        assessment = "raw_status_fields_captured"
    else:
        assessment = "no_game_status_fields_reported"
    return {
        "jsonStatus": json_status,
        "statusFields": fields,
        "assessment": assessment,
        "aggregateMeasurementStatus": "not_aggregated",
    }


def _decode_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def output_ready(path: Path) -> bool:
    return not path.exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "experiments/colab/model-manifest.json")
    parser.add_argument("--game-dir", type=Path, required=True, help="External vector-run-benchmark checkout; no files are copied into this repository")
    parser.add_argument("--game-commit", required=True, help="Immutable measurement commit in the external game repository")
    parser.add_argument("--benchmark-commit", required=True, help="Immutable commit of this Colab benchmark checkout")
    parser.add_argument("--models", choices=("single",), default="single", help="Each Colab runtime measures one model")
    parser.add_argument("--model", required=True, help="One audited manifest slug or model id")
    parser.add_argument("--output-dir", type=Path, required=True, help="New, per-session output directory outside the checkout")
    parser.add_argument("--runtime-history", type=Path, required=True, help="Caller-supplied prior-runtime/cache history JSON with evidence notes")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--quantization", choices=("none",), default="none")
    parser.add_argument("--series-timeout", type=float, default=240, help="Per-series CLI timeout in seconds")
    parser.add_argument("--drain-timeout", type=float, default=900, help="Wait for late model replies after the game CLI ends")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args(argv)

    if not valid_sha(args.game_commit):
        parser.error("--game-commit must be a full 40-character lowercase or uppercase SHA")
    if not valid_sha(args.benchmark_commit):
        parser.error("--benchmark-commit must be a full 40-character lowercase or uppercase SHA")
    if args.series_timeout <= 0:
        parser.error("--series-timeout must be positive")
    if args.drain_timeout <= 0:
        parser.error("--drain-timeout must be positive")
    if not args.manifest.is_file():
        parser.error("audited model manifest is missing")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        models = manifest if isinstance(manifest, list) else manifest["models"]
        model = select_model(models, args.model)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    if not valid_sha(model.get("revision")):
        parser.error("selected model does not have a pinned Hugging Face revision")
    try:
        runtime_history_value = json.loads(args.runtime_history.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"cannot read --runtime-history JSON: {public_error(error)}")
    runtime_history, history_errors = validate_runtime_history(runtime_history_value, model_key(model))
    if history_errors:
        parser.error("; ".join(history_errors))
    assert runtime_history is not None
    output_candidates = [
        args.output_dir / f"{model_key(model)}-{series}.{suffix}"
        for series, _questions, _seeds in SERIES
        for suffix in ("runner.json", "game.json", "metadata.json")
    ]
    if not all(output_ready(path) for path in output_candidates):
        parser.error("output directory already contains this model run; choose a new per-session directory")

    handoff: dict[str, Any] = {}
    try:
        value = json.loads(HANDOFF.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            handoff = value
    except (OSError, json.JSONDecodeError):
        handoff = {}

    reasons = validate_handoff(handoff, args.game_commit)
    reasons.extend(checkout_reasons(args.game_dir.resolve(), args.game_commit, "game", GAME_REPOSITORY))
    reasons.extend(checkout_reasons(ROOT, args.benchmark_commit, "benchmark"))
    game_script = args.game_dir.resolve() / GAME_CLI
    if not game_script.is_file():
        reasons.append("pinned game checkout is missing scripts/decision-bench.mjs")
    env = environment(None, probe_gpu=False)
    if env.get("node") != NODE_VERSION:
        reasons.append(f"Node must be pinned to {NODE_VERSION}; found {env.get('node') or 'unavailable'}")
    if reasons:
        paths = write_blocked_reports(args.output_dir, model, env, args, handoff, runtime_history, reasons)
        print(json.dumps({"runnerStatus": "blocked", "files": [p.name for p in paths], "reasons": reasons}, ensure_ascii=False))
        return 1

    torch = None
    torch_error = None
    try:
        import torch as torch_module
        torch = torch_module
    except Exception as error:
        torch_error = public_error(error)
    env = environment(torch, probe_gpu=True)
    if torch_error:
        reasons.append(f"PyTorch could not be imported: {torch_error}")
    if env.get("gpu_probe_error"):
        reasons.append(f"CUDA GPU probe failed: {env['gpu_probe_error']}")
    if not env.get("gpu"):
        reasons.append("CUDA GPU unavailable; no CPU or mock benchmark attempted")
    if reasons:
        paths = write_blocked_reports(args.output_dir, model, env, args, handoff, runtime_history, reasons)
        print(json.dumps({"runnerStatus": "blocked", "files": [p.name for p in paths], "reasons": reasons}, ensure_ascii=False))
        return 1

    assert torch is not None
    from server.decision_server import App, load_model, make_handler

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fatal_drain = False
    failures = 0
    server = serving = app = model_object = None
    base_runtime: dict[str, Any] = {
        "condition": {"gpu": env["gpu"]["name"], "dtype": model.get("dtype", args.dtype), "quantization": args.quantization, "offload": "none", "singleModelPerRuntime": True},
        "modelPhaseDefinition": "loadMs measures this process's model load; q3 request 1 is the first API call after model load, request 2 is warm, request 3+ is steady; q64 request 1 is its first API call after q3 on the same loaded model. This does not establish a cold Colab runtime, GPU, filesystem, or kernel cache.",
        "windowDefinition": {"durationSeconds": WINDOW_SECONDS, "origin": "series CLI start", "latencies": "request starts grouped by elapsed window"},
        "cacheObservations": {
            "huggingFacePinnedSnapshot": {"beforeModelLoad": weight_cache_observation(model)},
            "runtimeCaches": {"beforeModelLoad": runtime_cache_observation(), "warmHistory": "unknown"},
        },
        "measuredAtUtc": datetime.now(timezone.utc).isoformat(),
    }
    load_started = time.perf_counter()
    try:
        minimum = model.get("minimum_gpu_memory_bytes") or model.get("required_gpu_memory_bytes") or model.get("memory_estimate", {}).get("minimum_bytes")
        if minimum and minimum > env["gpu"]["free_memory_before_load_bytes"]:
            raise RuntimeError(f"GPU memory preflight requires {minimum} bytes; available {env['gpu']['free_memory_before_load_bytes']} bytes")
        model_object = load_model(
            model["repo"], revision=model["revision"], base_revision=model.get("base_revision"),
            dtype=args.dtype, quantization=args.quantization,
        )
        load_ms = (time.perf_counter() - load_started) * 1000
        app = MeasuredApp(App(model_object, model["repo"], {
            "revision": model.get("revision"), "baseRevision": model.get("base_revision"),
            "dtype": model.get("dtype", args.dtype), "quantization": args.quantization,
            "device": "cuda:0", "loadMs": load_ms,
        }))
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
        server.daemon_threads = True
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        base_runtime.update({"loadMs": load_ms, "loaderMetadata": getattr(model_object, "_benchmark_metadata", {})})
        base_runtime["cacheObservations"]["huggingFacePinnedSnapshot"]["afterModelLoad"] = weight_cache_observation(model)
        base_runtime["cacheObservations"]["runtimeCaches"]["afterModelLoad"] = runtime_cache_observation()
    except Exception as error:
        failures += 1
        reason = public_error(error)
        base_runtime["cacheObservations"]["huggingFacePinnedSnapshot"]["afterModelLoadAttempt"] = weight_cache_observation(model)
        base_runtime["cacheObservations"]["runtimeCaches"]["afterModelLoadAttempt"] = runtime_cache_observation()
        for series, questions, seeds in SERIES:
            contract = run_contract(handoff, series, questions, seeds)
            metadata = metadata_for(model, env, args, contract, runtime_history)
            path = output_dir / f"{model_key(model)}-{series}.runner.json"
            write_json(path, run_record("model_load_blocked", model, metadata, contract, env, {**base_runtime, "loadAttemptMs": (time.perf_counter() - load_started) * 1000, "reason": reason, "inferenceRecords": [], "inferenceDrained": True}, runtime_history))
        print(f"model load blocked: {reason}", file=sys.stderr)
        return 1

    try:
        for series, questions, seeds in SERIES:
            if fatal_drain:
                reasons = ["previous inference did not drain; remaining series skipped"]
                contract = run_contract(handoff, series, questions, seeds)
                metadata = metadata_for(model, env, args, contract, runtime_history)
                output = output_dir / f"{model_key(model)}-{series}.runner.json"
                write_json(output, run_record("blocked", model, metadata, contract, env, {**base_runtime, "reason": "; ".join(reasons), "inferenceRecords": [], "inferenceDrained": False}, runtime_history))
                failures += 1
                continue

            app.begin_series(series, timeout=args.drain_timeout)
            torch.cuda.reset_peak_memory_stats()
            contract = run_contract(handoff, series, questions, seeds)
            metadata = metadata_for(model, env, args, contract, runtime_history)
            raw_output = output_dir / f"{model_key(model)}-{series}.game.json"
            runner_output = output_dir / f"{model_key(model)}-{series}.runner.json"
            metadata_path = output_dir / f"{model_key(model)}-{series}.metadata.json"
            write_json(metadata_path, metadata)
            command = [
                shutil.which("node") or "node",
                str(game_script),
                "--agent", "remote",
                "--seeds", ",".join(map(str, seeds)),
                "--questions", str(questions),
                "--max-seconds", str(MAX_SECONDS),
                "--max-jumps", str(MAX_JUMPS),
                "--model", model["repo"],
                "--url", f"http://127.0.0.1:{args.port}/v1/systemone",
                "--metadata", str(metadata_path),
                "--output", str(raw_output),
                "--trace",
            ]
            started = time.perf_counter()
            cli_exit = None
            cli_state = "running"
            cli_error = None
            try:
                completed = subprocess.run(
                    command, cwd=args.game_dir.resolve(), text=True, encoding="utf-8", errors="replace",
                    capture_output=True, timeout=args.series_timeout,
                )
                cli_exit = completed.returncode
                cli_state = "exited"
                if completed.returncode:
                    cli_error = public_error(completed.stderr[-2000:]) or f"game CLI exited {completed.returncode}"
            except subprocess.TimeoutExpired as error:
                cli_state = "timeout"
                cli_error = public_error(_decode_output(error.stderr)[-2000:] or f"game CLI exceeded {args.series_timeout} seconds")
            except Exception as error:
                cli_state = "launch_error"
                cli_error = public_error(error)
            drained = app.drain(timeout=args.drain_timeout)
            fatal_drain |= not drained
            game_report = None
            report_error = None
            report_sha256 = None
            report_parsed = False
            if raw_output.is_file():
                raw_bytes = raw_output.read_bytes()
                report_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                try:
                    game_report = json.loads(raw_bytes.decode("utf-8"))
                    report_parsed = True
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    report_error = public_error(error)

            report_json_status = "valid" if report_parsed else "invalid" if report_error else "missing"
            if cli_state == "timeout":
                runner_status = "cli_process_timeout"
            elif cli_state == "launch_error":
                runner_status = "cli_process_launch_error"
            elif cli_exit == 0:
                runner_status = "cli_process_exited_zero"
            else:
                runner_status = "cli_process_exited_nonzero"

            game_status = game_report_status(game_report, report_json_status)
            inference_errors = [record for record in app.records if record.get("status") != "ok"]

            runtime = {
                **base_runtime,
                "elapsedWallMs": (time.perf_counter() - started) * 1000,
                "gpuPeakAllocatedBytes": torch.cuda.max_memory_allocated(),
                "gpuPeakReservedBytes": torch.cuda.max_memory_reserved(),
                "inferenceRecords": list(app.records),
                "inferenceTimings": timing_summary(app.records),
                "inferenceDrained": drained,
                "gameTraceTimingSource": "raw game report; serverRequestMs excludes client transport",
                "cacheObservations": {
                    **base_runtime["cacheObservations"],
                    "huggingFacePinnedSnapshot": {
                        **base_runtime["cacheObservations"]["huggingFacePinnedSnapshot"],
                        f"after_{series}": weight_cache_observation(model),
                    },
                    "runtimeCaches": {
                        **base_runtime["cacheObservations"]["runtimeCaches"],
                        f"after_{series}": runtime_cache_observation(),
                        "warmHistory": "unknown; snapshots show directory state only",
                    },
                },
            }
            record = run_record(runner_status, model, metadata, contract, env, runtime, runtime_history)
            record["gameReport"] = {
                "file": raw_output.name if raw_output.is_file() else None,
                "sha256": report_sha256,
                "validJson": report_parsed,
                "jsonType": type(game_report).__name__ if report_parsed else None,
                "parseError": report_error,
            }
            record["gameReportStatus"] = game_status
            record["aggregateMeasurementStatus"] = "not_aggregated"
            record["aggregateProblems"] = [
                *(["CLI process did not exit zero"] if runner_status != "cli_process_exited_zero" else []),
                *(["game report is missing or invalid JSON"] if report_json_status != "valid" else []),
                *(["model inference errors were recorded"] if inference_errors else []),
                *(["model inference did not drain before the report window closed"] if not drained else []),
            ]
            record["cli"] = {"exitCode": cli_exit, "state": cli_state, "error": cli_error}
            write_json(runner_output, record)
            if record["aggregateProblems"]:
                failures += 1
            print(json.dumps({"model": model_key(model), "series": series, "runnerStatus": runner_status, "gameReportStatus": game_status["assessment"], "aggregateMeasurementStatus": "not_aggregated", "gameReportFile": raw_output.name if raw_output.exists() else None}, ensure_ascii=False), flush=True)
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if serving:
            serving.join(timeout=2)
        if app:
            app.app.model = None
        app = server = model_object = None
        gc.collect()
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception:
            pass
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
