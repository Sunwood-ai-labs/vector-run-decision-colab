#!/usr/bin/env python3
"""Aggregate only pinned, replay-validated VECTOR RUN measurements."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any


GAME_COMMIT = "717f02dc9852b88c253ace32f42fcb6d780ed0d3"
BENCHMARK_COMMIT = "b2e8fcbbf4b4f68931e4f9bbfbd434023348d3f0"
SCHEMA_VERSION = "vector-run-results/v1"
TARGETS = (
    ("kai", "Kai", "model"),
    ("eos", "Eos", "model"),
    ("sol", "Sol", "model"),
    ("sol-reasoning", "Sol-Reasoning", "model"),
    ("nox", "Nox", "model"),
    ("lux", "Lux", "model"),
    ("vega", "Vega", "model"),
    ("rule", "rule", "control"),
    ("idle", "idle", "control"),
)
SLUGS = {item[0] for item in TARGETS}
AUDIT_HASH_KEYS = (
    "manifest_sha256",
    "model_identity_sha256",
    "remote_code_sha256",
    "runtime_api_sha256",
)
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FORBIDDEN_PATH_WORDS = ("prototype", "private", "excluded")


class RejectedInput(ValueError):
    """An input cannot be represented as an official benchmark result."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RejectedInput(f"cannot read JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise RejectedInput(f"JSON root is not an object: {path.name}")
    return value


def _safe_results_root(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    raw_parts = [part.lower() for part in candidate.parts]
    if any(word in part for word in FORBIDDEN_PATH_WORDS for part in raw_parts):
        raise RejectedInput("prototype/private input paths are prohibited")
    if candidate.name.lower() != "results":
        raise RejectedInput("input root must be the official results directory")
    try:
        root = candidate.resolve(strict=True)
    except OSError as exc:
        raise RejectedInput("results directory does not exist") from exc
    if not root.is_dir() or root.name.lower() != "results":
        raise RejectedInput("input root must resolve to a results directory")
    if any(word in part.lower() for word in FORBIDDEN_PATH_WORDS for part in root.parts):
        raise RejectedInput("prototype/private input paths are prohibited")
    return root


def _require_commit(actual: Any, expected: str, label: str) -> None:
    if actual != expected:
        raise RejectedInput(f"{label} pin mismatch")


def _metadata_model(data: dict[str, Any]) -> dict[str, Any]:
    model = data.get("model")
    if isinstance(model, dict):
        return model
    nested = data.get("metadata")
    model = nested.get("model") if isinstance(nested, dict) else None
    return model if isinstance(model, dict) else {}


def _verify_model_identity(
    slug: str,
    game: dict[str, Any],
    metadata: dict[str, Any],
    runner: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    if slug in ("rule", "idle"):
        agent = game.get("agent")
        if not isinstance(agent, dict) or agent.get("kind") != slug:
            raise RejectedInput("CPU control identity mismatch")
        return {"id": agent.get("model") or slug, "revision": "control"}

    game_model = _metadata_model(game)
    meta_model = _metadata_model(metadata) if metadata else game_model
    runner_meta = runner.get("metadata") if isinstance(runner, dict) else None
    runner_metadata_model = runner_meta.get("model") if isinstance(runner_meta, dict) else None
    runner_model = runner_metadata_model if isinstance(runner_metadata_model, dict) else _metadata_model(runner)
    models = [game_model, meta_model, runner_model]
    model_ids = [item.get("id") for item in models]
    revisions = [item.get("revision") for item in models]
    if not all(isinstance(value, str) and value for value in model_ids + revisions):
        raise RejectedInput("model id/revision missing")
    if len(set(model_ids)) != 1 or len(set(revisions)) != 1:
        raise RejectedInput("model identity/revision differs across artifacts")

    model_id = model_ids[0]
    revision = revisions[0]
    verify_model = verification.get("model")
    if isinstance(verify_model, dict):
        if verify_model.get("id") != model_id:
            raise RejectedInput("verification model id mismatch")
    elif isinstance(verify_model, str) and verify_model != model_id:
        raise RejectedInput("verification model id mismatch")
    verify_model_dict = verify_model if isinstance(verify_model, dict) else {}
    verify_revision = verification.get("modelRevision") or verification.get("hfRevision") or verify_model_dict.get("revision")
    if not isinstance(verify_revision, str) or len(verify_revision) < 8:
        raise RejectedInput("verification model revision missing")
    if not revision.startswith(verify_revision):
        raise RejectedInput("verification model revision mismatch")

    audits: list[dict[str, Any]] = []
    for item in models:
        audit = item.get("sourceAudit")
        if not isinstance(audit, dict) or not all(
            isinstance(audit.get(key), str) and HASH_RE.fullmatch(audit[key])
            for key in AUDIT_HASH_KEYS
        ):
            raise RejectedInput("pinned source audit hashes missing")
        audits.append({key: audit[key].lower() for key in AUDIT_HASH_KEYS})
    if any(audit != audits[0] for audit in audits[1:]):
        raise RejectedInput("source audit hashes differ across artifacts")

    return {"id": model_id, "revision": revision, "sourceAudit": audits[0]}


def _verify_report_pins(
    game: dict[str, Any],
    metadata: dict[str, Any],
    runner: dict[str, Any],
    verification: dict[str, Any],
) -> None:
    game_info = game.get("game")
    game_meta = game.get("metadata")
    runner_meta = runner.get("metadata") if isinstance(runner, dict) else None
    if not isinstance(metadata, dict):
        metadata = game_meta if isinstance(game_meta, dict) else {}
    verify_game = verification.get("game")
    verify_bench = verification.get("benchmark")
    pins = verification.get("pins")
    pin_game = pins.get("game") if isinstance(pins, dict) else None
    pin_bench = pins.get("benchmark") if isinstance(pins, dict) else None
    game_verification_pins = [
        value
        for value in (
            verification.get("gameCommit"),
            verify_game.get("commit") if isinstance(verify_game, dict) else None,
            pin_game.get("commit") if isinstance(pin_game, dict) else None,
        )
        if value is not None
    ]
    benchmark_verification_pins = [
        value
        for value in (
            verification.get("benchmarkCommit"),
            verify_bench.get("commit") if isinstance(verify_bench, dict) else None,
            pin_bench.get("commit") if isinstance(pin_bench, dict) else None,
        )
        if value is not None
    ]
    _require_commit(game.get("gameCommit"), GAME_COMMIT, "game")
    _require_commit(game_info.get("commit") if isinstance(game_info, dict) else None, GAME_COMMIT, "game.commit")
    _require_commit(game_meta.get("gameCommit") if isinstance(game_meta, dict) else None, GAME_COMMIT, "game metadata")
    _require_commit(metadata.get("gameCommit"), GAME_COMMIT, "sidecar game")
    if isinstance(runner, dict):
        _require_commit(runner_meta.get("gameCommit") if isinstance(runner_meta, dict) else None, GAME_COMMIT, "runner game")
    if not game_verification_pins:
        raise RejectedInput("verification game pin missing")
    for actual in game_verification_pins:
        _require_commit(actual, GAME_COMMIT, "verification game")
    envelope = verification.get("verification")
    pinned_validator = envelope.get("pinnedValidator") if isinstance(envelope, dict) else None
    if isinstance(pinned_validator, dict) and pinned_validator.get("gameCommit") is not None:
        _require_commit(pinned_validator.get("gameCommit"), GAME_COMMIT, "pinned validator game")

    _require_commit(game_meta.get("benchmarkCommit") if isinstance(game_meta, dict) else None, BENCHMARK_COMMIT, "game metadata benchmark")
    _require_commit(metadata.get("benchmarkCommit"), BENCHMARK_COMMIT, "sidecar benchmark")
    if isinstance(runner, dict):
        _require_commit(runner_meta.get("benchmarkCommit") if isinstance(runner_meta, dict) else None, BENCHMARK_COMMIT, "runner benchmark")
    if not benchmark_verification_pins:
        raise RejectedInput("verification benchmark pin missing")
    for actual in benchmark_verification_pins:
        _require_commit(actual, BENCHMARK_COMMIT, "verification benchmark")


def _security_was_checked(verification: dict[str, Any]) -> bool:
    envelope = verification.get("verification")
    if isinstance(envelope, dict):
        privacy = envelope.get("privacy")
        if (
            envelope.get("sourceBytesPreserved") is True
            and envelope.get("transformations") == []
            and isinstance(privacy, dict)
            and privacy.get("credentialPatternMatches") == 0
        ):
            return True
    security = verification.get("security")
    if isinstance(security, dict):
        if (
            security.get("secretAndSessionKeyScan") == "pass"
            and security.get("forbiddenKeyOrSecretMatchCount") == 0
            and security.get("rawAuthenticationLogsIncluded") is False
        ):
            return True
    validation = verification.get("validation")
    checks = validation.get("rawTraceChecks") if isinstance(validation, dict) else None
    if isinstance(checks, dict) and checks.get("credentialOrRuntimeIdPatternScan") in ("no matches", "pass"):
        return True
    sanitization = verification.get("sanitization")
    if isinstance(sanitization, dict):
        return (
            sanitization.get("credentialsAndSessionIdentifiers") == "absent"
            and sanitization.get("runnerJsonParse") == "passed"
            and sanitization.get("sensitivePatternScan") == "passed"
        )
    privacy = verification.get("privacyScan")
    if isinstance(privacy, dict):
        return privacy.get("credentialOrVMPathFindings") == 0 and privacy.get("filesWithFindings") == 0
    scan = verification.get("sessionIdOrCredentialScan")
    if isinstance(scan, str) and "no session" in scan.lower() and "credential" in scan.lower():
        return True
    safety = verification.get("artifactSafety")
    if isinstance(safety, dict):
        return safety.get("status") in ("pass", "passed", "clean")
    return False


def _validator_evidence(
    slug: str,
    series: str,
    game: dict[str, Any],
    verification: dict[str, Any],
    game_path: Path,
) -> None:
    episodes = game.get("episodes")
    runs = game.get("runs")
    if not isinstance(episodes, list) or not episodes or not isinstance(runs, list):
        raise RejectedInput("episode/run trace missing")
    q = int(series[1:])

    validation = verification.get("validation")
    item = validation.get(series) if isinstance(validation, dict) else None
    if isinstance(item, dict):
        checks = validation.get("rawTraceChecks") if isinstance(validation, dict) else None
        passed = (
            item.get("valid") is True
            and bool(item.get("validator"))
            and item.get("questionCount") == q
            and item.get("validRuns") == len(episodes)
            and item.get("runtimeGameInvalidErrors") in ([], None)
            and isinstance(checks, dict)
            and checks.get("replayInputTicksAndFinalHashVerified") is True
        )
        if passed:
            return

    evidence = verification.get("series")
    series_item = None
    if isinstance(evidence, dict):
        series_item = evidence.get(series)
    elif isinstance(evidence, list):
        series_item = next((x for x in evidence if isinstance(x, dict) and x.get("series") == series), None)
    if isinstance(evidence, list) and series_item is None:
        series_item = next((x for x in evidence if isinstance(x, dict) and x.get("file") == game_path.name), None)

    validator = verification.get("validator")
    if isinstance(validator, dict) and validator.get(f"{series}Valid") is True and validator.get(f"{series}ExitCode") == 0:
        game_runs = series_item.get("gameRuns") if isinstance(series_item, dict) else None
        if isinstance(game_runs, list) and len(game_runs) == len(episodes):
            return

    if isinstance(series_item, dict):
        envelope = verification.get("verification")
        pinned_validator = envelope.get("pinnedValidator") if isinstance(envelope, dict) else None
        if isinstance(pinned_validator, dict):
            game_sha = hashlib.sha256(game_path.read_bytes()).hexdigest()
            validator_sha = pinned_validator.get("gitBlobSha1")
            raw_artifacts = verification.get("rawArtifacts")
            raw_game_artifact = next(
                (item for item in raw_artifacts if isinstance(item, dict) and item.get("file") == game_path.name),
                None,
            ) if isinstance(raw_artifacts, list) else None
            verified_episodes = series_item.get("episodes")
            episode_fields = (
                "seed",
                "terminalStatus",
                "valid",
                "eligibleForSummary",
                "distanceMetres",
                "survivalSeconds",
                "censored",
            )
            episodes_match = (
                isinstance(verified_episodes, list)
                and len(verified_episodes) == len(episodes)
                and all(
                    isinstance(proof_episode, dict)
                    and all(proof_episode.get(key) == game_episode.get(key) for key in episode_fields)
                    for proof_episode, game_episode in zip(verified_episodes, episodes)
                )
            )
            passed = (
                pinned_validator.get("path") == "scripts/verify-decision-trace.mjs"
                and pinned_validator.get("gameCommit") == GAME_COMMIT
                and isinstance(validator_sha, str)
                and re.fullmatch(r"[0-9a-fA-F]{40}", validator_sha) is not None
                and pinned_validator.get(f"{series}Valid") is True
                and series_item.get("questionsPerRequest") == q
                and series_item.get("seeds") == [episode.get("seed") for episode in episodes]
                and series_item.get("runnerStatus") == "cli_process_exited_zero"
                and series_item.get("gameReportStatus") == "raw_status_fields_captured"
                and series_item.get("gameReportHashMatchesArtifact") is True
                and series_item.get("traceReplayValid") is True
                and series_item.get("gameReportSha256") == game_sha
                and series_item.get("artifactSha256") == game_sha
                and series_item.get("inferenceDrained") is True
                and isinstance(raw_game_artifact, dict)
                and raw_game_artifact.get("sha256") == game_sha
                and episodes_match
            )
            if passed:
                return
            raise RejectedInput("pinned replay validator evidence/hash/episode comparison failed")

        validator_result = series_item.get("validator")
        if isinstance(validator_result, dict):
            valid = validator_result.get("valid") is True or validator_result.get("passed") is True
            count = validator_result.get("questionCount", series_item.get("questionCount"))
            run_count = validator_result.get("runs", validator_result.get("runCount"))
            question_counts = series_item.get("questionsPerRequest")
            if count is None and isinstance(question_counts, int):
                count = question_counts
            if count is None and isinstance(question_counts, list) and question_counts:
                count = question_counts[0] if len(set(question_counts)) == 1 else None
            seeds = series_item.get("seeds")
            if run_count is None and isinstance(seeds, list):
                run_count = len(seeds)
            if run_count is None and isinstance(series_item.get("runs"), list):
                run_count = len(series_item["runs"])
            if valid and count == q and run_count == len(episodes):
                game_hash = hashlib.sha256(game_path.read_bytes()).hexdigest()
                downloaded_hash = validator_result.get("downloadedGameSha256") or series_item.get("gameJsonSha256")
                if downloaded_hash and downloaded_hash != game_hash:
                    raise RejectedInput("validator game SHA-256 mismatch")
                if validator_result.get("exitCode", 0) != 0:
                    raise RejectedInput("validator exited unsuccessfully")
                return
        if series_item.get("validator") == "pass" and series_item.get("validatorRuns") == len(episodes):
            if series_item.get("file") not in (None, game_path.name):
                raise RejectedInput("validator game filename mismatch")
            if series_item.get("sha256") != hashlib.sha256(game_path.read_bytes()).hexdigest():
                raise RejectedInput("validator game SHA-256 mismatch")
            return

    raise RejectedInput("replay validator evidence missing or failed")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _count_errors(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if value is None or value is False or value == 0:
        return 0
    return 1


def _episode_rows(game: dict[str, Any], question_count: int) -> list[dict[str, Any]]:
    episodes = game["episodes"]
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            raise RejectedInput("malformed episode")
        censored = episode.get("censored")
        if not isinstance(censored, bool):
            raise RejectedInput("episode censoring status missing")
        terminal = episode.get("terminalStatus") or episode.get("endReason")
        if not terminal:
            raise RejectedInput("episode terminal result missing")
        if episode.get("valid") is not True and not (censored and str(terminal).lower() in ("time_limit", "censored")):
            raise RejectedInput("invalid non-censored episode")
        rows.append(
            {
                "seed": episode.get("seed"),
                "questions": question_count,
                "terminalStatus": terminal,
                "endReason": episode.get("endReason"),
                "censored": censored,
                "eligibleForSummary": episode.get("eligibleForSummary"),
                "distanceMetres": _finite_number(episode.get("distanceMetres")),
                "survivalSeconds": _finite_number(episode.get("survivalSeconds")),
                "jumps": episode.get("jumps") if isinstance(episode.get("jumps"), int) else None,
            }
        )
    return rows


def _episode_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [row for row in rows if row["distanceMetres"] is not None and row["survivalSeconds"] is not None]
    censored_count = sum(row["censored"] for row in rows)
    result: dict[str, Any] = {
        "episodeCount": len(rows),
        "censoredCount": censored_count,
        "terminalCounts": {},
        "meanDistanceMetres": None,
        "meanObservedSurvivalSeconds": None,
        "meanJumps": None,
    }
    for row in rows:
        key = row["terminalStatus"]
        result["terminalCounts"][key] = result["terminalCounts"].get(key, 0) + 1
    if observed:
        result["meanDistanceMetres"] = statistics.mean(row["distanceMetres"] for row in observed)
        result["meanObservedSurvivalSeconds"] = statistics.mean(row["survivalSeconds"] for row in observed)
    jump_values = [row["jumps"] for row in rows if row["jumps"] is not None]
    if jump_values:
        result["meanJumps"] = statistics.mean(jump_values)
    if not censored_count:
        cleared = sum(str(row["terminalStatus"]).lower() in ("cleared", "clear", "course_cleared") for row in rows)
        result["clearRate"] = cleared / len(rows) if rows else None
    return result


def _decision_counts(game: dict[str, Any]) -> dict[str, int]:
    decisions = [
        decision
        for run in game.get("runs", [])
        if isinstance(run, dict)
        for decision in run.get("decisions", [])
        if isinstance(decision, dict)
    ]
    answered_statuses = {"answered", "late_answer_not_applied"}
    errors = {"error", "response_error", "failed", "http_error"}
    missing = 0
    for decision in decisions:
        status = str(decision.get("status", "")).lower()
        request = decision.get("rawRequest")
        questions = request.get("questions") if isinstance(request, dict) else None
        expected_keys = set(questions) if isinstance(questions, dict) else None
        if status in answered_statuses:
            answers = decision.get("answers")
            answer_keys = set(answers) if isinstance(answers, dict) else set()
            if expected_keys is not None:
                missing += len(expected_keys - answer_keys)
            else:
                count = decision.get("questionCount")
                missing += max(0, int(count) - len(answer_keys)) if isinstance(count, int) else 0
        elif status in errors:
            missing += len(expected_keys) if expected_keys is not None else int(decision.get("questionCount", 0) or 0)
    late = sum(
        str(decision.get("status", "")).lower() == "late_answer_not_applied" or bool(decision.get("lateReply"))
        for decision in decisions
    )
    return {
        "answeredResponses": sum(str(item.get("status", "")).lower() == "answered" for item in decisions),
        "skippedOutstanding": sum(str(item.get("status", "")).lower() == "skipped_outstanding" for item in decisions),
        "lateAnswers": late,
        "missingQuestionAnswers": missing,
    }


def _metadata_transform_proof(
    verification: dict[str, Any],
    filename: str,
    before_sha: str,
    after_sha: str,
) -> bool:
    proof_lists = (verification.get("artifactTransformations"), verification.get("transformations"))
    allowed_path = re.compile(r"^\$\.metadata\.runtimeHistory(?:\.[A-Za-z0-9_-]+)*(?:cache|path|root|dir)(?:[A-Za-z0-9_-]*)?(?:\.[A-Za-z0-9_-]+)*$", re.IGNORECASE)
    for proofs in proof_lists:
        if not isinstance(proofs, list):
            continue
        for proof in proofs:
            if not isinstance(proof, dict):
                continue
            artifact = proof.get("artifact") or proof.get("file") or proof.get("name")
            if Path(str(artifact)).name != filename:
                continue
            paths = proof.get("changedPaths")
            deep_diff_ok = proof.get("deepDiffVerified") is True or proof.get("onlyMetadataRuntimeHistoryCachePaths") is True
            if (
                proof.get("operation") == "normalize_runtime_history_cache_paths"
                and proof.get("beforeSha256") == before_sha
                and proof.get("afterSha256") == after_sha
                and isinstance(paths, list)
                and paths
                and all(isinstance(path, str) and allowed_path.fullmatch(path) for path in paths)
                and deep_diff_ok
            ):
                return True
    return False


def _rejection_record(
    slug: str,
    run_id: str,
    series: str,
    reason: str,
    game_path: Path | None = None,
) -> dict[str, str]:
    record = {"slug": slug, "runId": run_id, "series": series, "reason": reason}
    if game_path is None or not game_path.is_file():
        return record
    runner_path = game_path.with_name(game_path.name[:-len(".game.json")] + ".runner.json")
    if not runner_path.is_file():
        return record
    try:
        runner = _read_json(runner_path)
        report = runner.get("gameReport")
        runner_sha = report.get("sha256") if isinstance(report, dict) else None
        published_sha = hashlib.sha256(game_path.read_bytes()).hexdigest()
        if isinstance(runner_sha, str) and HASH_RE.fullmatch(runner_sha) and runner_sha.lower() != published_sha:
            record["runnerReportedGameSha256"] = runner_sha.lower()
            record["publishedGameSha256"] = published_sha
    except (OSError, RejectedInput):
        pass
    return record


def _inference_summary(runner: dict[str, Any], series: str, q3_runner: dict[str, Any] | None) -> dict[str, Any]:
    runtime = runner.get("runtime")
    if not isinstance(runtime, dict):
        raise RejectedInput("runner runtime measurements missing")
    records = runtime.get("inferenceRecords")
    if not isinstance(records, list):
        raise RejectedInput("raw inferenceRecords missing")
    valid_records = [record for record in records if isinstance(record, dict)]
    measured = [record for record in valid_records if record.get("status") == "ok" and _finite_number(record.get("system_one_ms")) is not None]
    times = [_finite_number(record.get("system_one_ms")) for record in measured]
    times = [value for value in times if value is not None]
    forward_calls = sum(
        record.get("neural_forward_calls", 0)
        for record in valid_records
        if isinstance(record.get("neural_forward_calls", 0), int)
    )
    shapes: dict[tuple[int, ...], int] = {}
    for record in valid_records:
        batches = record.get("neural_forward_batches")
        if isinstance(batches, list):
            for batch in batches:
                shape = batch.get("input_ids_shape") if isinstance(batch, dict) else None
                if isinstance(shape, list) and all(isinstance(part, int) for part in shape):
                    key = tuple(shape)
                    shapes[key] = shapes.get(key, 0) + 1

    result: dict[str, Any] = {
        "recordCount": len(valid_records),
        "errorRecordCount": sum(record.get("status") != "ok" for record in valid_records),
        "forwardCalls": forward_calls,
        "batchShapes": [
            {"inputIdsShape": list(shape), "batches": count}
            for shape, count in sorted(shapes.items())
        ],
        "systemOneP50Ms": statistics.median(times) if times else None,
        "firstSystemOneMs": None,
        "remainingSystemOneP50Ms": None,
        "sameProcessAfterQ3": None,
        "gpuPeakAllocatedBytes": _finite_number(runtime.get("gpuPeakAllocatedBytes")),
        "gpuPeakReservedBytes": _finite_number(runtime.get("gpuPeakReservedBytes")),
    }
    if series == "q3":
        first_records = [record for record in measured if record.get("firstApiCallAfterModelLoad") is True]
        if len(first_records) != 1:
            raise RejectedInput("q3 first call after model load is not uniquely marked")
        result["firstSystemOneMs"] = _finite_number(first_records[0].get("system_one_ms"))
        remaining = [
            _finite_number(record.get("system_one_ms"))
            for record in measured
            if record is not first_records[0]
        ]
        remaining = [value for value in remaining if value is not None]
        result["remainingSystemOneP50Ms"] = statistics.median(remaining) if remaining else None
    else:
        q3_runtime = q3_runner.get("runtime") if isinstance(q3_runner, dict) else None
        q3_records = q3_runtime.get("inferenceRecords") if isinstance(q3_runtime, dict) else None
        q3_first_count = sum(
            isinstance(record, dict) and record.get("firstApiCallAfterModelLoad") is True
            for record in (q3_records if isinstance(q3_records, list) else [])
        )
        after_q3 = q3_first_count == 1 and all(
            record.get("firstApiCallAfterModelLoad") is False for record in measured
        )
        result["sameProcessAfterQ3"] = after_q3
        if not after_q3:
            result["systemOneP50Ms"] = None
    return result


def _validate_series(
    slug: str,
    run_id: str,
    series: str,
    game_path: Path,
    metadata_path: Path | None,
    runner_path: Path,
    verification_path: Path,
    q3_runner: dict[str, Any] | None,
    results_root: Path,
) -> dict[str, Any]:
    game = _read_json(game_path)
    metadata = _read_json(metadata_path) if metadata_path and metadata_path.is_file() else game.get("metadata", {})
    runner = _read_json(runner_path)
    verification = _read_json(verification_path)
    _verify_report_pins(game, metadata, runner, verification)
    model_info = _verify_model_identity(slug, game, metadata, runner, verification)
    _validator_evidence(slug, series, game, verification, game_path)

    if runner.get("runnerStatus") != "cli_process_exited_zero":
        raise RejectedInput("runner did not exit successfully")
    if runner.get("aggregateProblems") not in ([], None):
        raise RejectedInput("runner reports aggregate problems")
    cli = runner.get("cli")
    if not isinstance(cli, dict) or cli.get("exitCode") != 0:
        raise RejectedInput("runner exit code missing or nonzero")
    report = runner.get("gameReport")
    if not isinstance(report, dict) or report.get("validJson") is not True:
        raise RejectedInput("runner game report integrity evidence missing")
    game_sha = hashlib.sha256(game_path.read_bytes()).hexdigest()
    runner_game_sha = report.get("sha256")
    transformed = False
    if runner_game_sha != game_sha:
        transformed = _metadata_transform_proof(verification, game_path.name, runner_game_sha, game_sha)
        if not transformed:
            raise RejectedInput("runner/published game SHA-256 mismatch; metadata-only proof pending")

    invalid_errors = _count_errors(game.get("runtimeGameInvalidErrors"))
    response_errors = _count_errors(game.get("responseErrors"))
    for run in game.get("runs", []):
        if not isinstance(run, dict):
            raise RejectedInput("malformed run trace")
        invalid_errors += _count_errors(run.get("runtimeGameInvalidErrors"))
        response_errors += _count_errors(run.get("responseErrors"))
    if invalid_errors:
        raise RejectedInput("runtimeGameInvalidErrors present")

    question_count = int(series[1:])
    episode_rows = _episode_rows(game, question_count)
    model = _metadata_model(game)
    hardware = game.get("hardware")
    if not isinstance(hardware, dict):
        raise RejectedInput("hardware metadata missing")
    runner_runtime = runner.get("runtime")
    runner_runtime = runner_runtime if isinstance(runner_runtime, dict) else {}
    condition = runner_runtime.get("condition")
    environment = runner_runtime.get("environment")
    gpu = (
        (condition.get("gpu") if isinstance(condition, dict) else None)
        or (environment.get("gpu") if isinstance(environment, dict) else None)
        or hardware.get("gpu")
    )
    if not isinstance(gpu, str) or not gpu:
        raise RejectedInput("GPU/hardware identity missing")
    game_metadata = game.get("metadata")
    game_metadata_hardware = game_metadata.get("hardware") if isinstance(game_metadata, dict) else None
    runner_meta = runner.get("metadata")
    runner_hardware = runner_meta.get("hardware") if isinstance(runner_meta, dict) else None
    if not isinstance(game_metadata_hardware, dict) or not isinstance(runner_hardware, dict):
        raise RejectedInput("embedded game/runner hardware metadata missing")
    hardware_sources = [("game", hardware), ("game metadata", game_metadata_hardware), ("runner metadata", runner_hardware)]
    if metadata_path and metadata_path.is_file():
        sidecar_hardware = metadata.get("hardware")
        if not isinstance(sidecar_hardware, dict):
            raise RejectedInput("standalone metadata hardware missing")
        hardware_sources.append(("standalone metadata", sidecar_hardware))
    for label, source in hardware_sources:
        if source.get("gpu") != gpu:
            raise RejectedInput(f"{label}/game GPU metadata mismatch")
    for key in ("dtype", "quantization"):
        values = [source.get(key) for _, source in hardware_sources]
        if any(not isinstance(value, str) or not value for value in values) or len(set(values)) != 1:
            raise RejectedInput(f"hardware {key} metadata differs or is missing")

    source_path = lambda path: path.resolve().relative_to(results_root).as_posix()
    return {
        "slug": slug,
        "runId": run_id,
        "series": series,
        "questions": question_count,
        "model": model_info,
        "hardware": {
            "gpu": gpu,
            "dtype": hardware.get("dtype"),
            "quantization": hardware.get("quantization"),
        },
        "episodes": episode_rows,
        "episodeSummary": _episode_summary(episode_rows),
        "errors": {
            "runtimeGameInvalidErrors": invalid_errors,
            "responseErrors": response_errors,
            "inferenceErrors": sum(
                isinstance(record, dict) and record.get("status") != "ok"
                for record in (runner_runtime.get("inferenceRecords") or [])
            ),
        },
        "decisions": _decision_counts(game),
        "inference": _inference_summary(runner, series, q3_runner),
        "sourceFiles": {
            "game": source_path(game_path),
            "metadata": source_path(metadata_path) if metadata_path and metadata_path.is_file() else None,
            "runner": source_path(runner_path),
            "verification": source_path(verification_path),
        },
        "integrity": {
            "runnerReportedGameSha256": runner_game_sha,
            "publishedGameSha256": game_sha,
            "metadataOnlyTransformationProven": transformed,
        },
    }


def _verification_path(run_dir: Path, slug: str, run_id: str) -> Path:
    names = (f"{run_id}-verification.json", "verification.json", ".verification.json", f"{slug}-verification.json")
    found = [run_dir / name for name in names if (run_dir / name).is_file()]
    if not found:
        found = sorted(path for path in run_dir.glob("*verification.json") if path.is_file())
    if len(found) != 1:
        raise RejectedInput("expected exactly one verification.json")
    return found[0]


def _check_availability(
    slug: str,
    run_dir: Path,
    verification_path: Path,
) -> dict[str, Any] | None:
    if slug != "sol-reasoning":
        return None
    verification = _read_json(verification_path)
    if verification.get("status") not in ("model_load_blocked_before_game_start", "model_access_blocked"):
        return None
    if any(run_dir.glob("*-q*.game.json")):
        raise RejectedInput("blocked status cannot replace an existing game measurement")
    game_pin = verification.get("game")
    benchmark_pin = verification.get("benchmark")
    _require_commit(game_pin.get("commit") if isinstance(game_pin, dict) else None, GAME_COMMIT, "blocked verification game")
    _require_commit(benchmark_pin.get("commit") if isinstance(benchmark_pin, dict) else None, BENCHMARK_COMMIT, "blocked verification benchmark")
    model_id = verification.get("model")
    revision = verification.get("modelRevision")
    model_load = verification.get("modelLoad")
    history = verification.get("runtimeHistory")
    if not isinstance(model_id, str) or not isinstance(revision, str):
        raise RejectedInput("blocked model identity missing")
    if not isinstance(model_load, dict) or model_load.get("runnerStatus") not in ("model_load_blocked", "model_access_blocked"):
        raise RejectedInput("blocked runner evidence missing")
    if model_load.get("systemOneCalls") != 0 or model_load.get("neuralForwardCalls") != 0:
        raise RejectedInput("blocked record contains inference calls")
    if not isinstance(history, dict) or history.get("weightsCached") is not False:
        raise RejectedInput("exact model cache check is missing or inconclusive")
    if re.search(r"\b401\b", str(model_load.get("reason", ""))) is None:
        raise RejectedInput("distribution HTTP 401 evidence missing")
    if not _security_was_checked(verification):
        raise RejectedInput("blocked evidence sanitization check missing")

    runner_revisions: set[str] = set()
    for series in ("q3", "q64"):
        runner_path = run_dir / f"sol-reasoning-{series}.runner.json"
        if not runner_path.is_file():
            raise RejectedInput(f"blocked {series} runner evidence missing")
        runner = _read_json(runner_path)
        if runner.get("runnerStatus") not in ("model_load_blocked", "model_access_blocked"):
            raise RejectedInput(f"blocked {series} runner status mismatch")
        runtime = runner.get("runtime")
        if not isinstance(runtime, dict) or runtime.get("inferenceRecords") != []:
            raise RejectedInput(f"blocked {series} runner has missing/unknown inference count")
        model = _metadata_model(runner)
        meta = runner.get("metadata")
        meta_model = meta.get("model") if isinstance(meta, dict) else None
        if not isinstance(meta_model, dict):
            raise RejectedInput(f"blocked {series} source metadata missing")
        if model.get("id") != model_id or model.get("revision") != revision:
            raise RejectedInput(f"blocked {series} model revision mismatch")
        if meta_model.get("id") != model_id or meta_model.get("revision") != revision:
            raise RejectedInput(f"blocked {series} metadata revision mismatch")
        _require_commit(meta.get("gameCommit") if isinstance(meta, dict) else None, GAME_COMMIT, f"blocked {series} game")
        _require_commit(meta.get("benchmarkCommit") if isinstance(meta, dict) else None, BENCHMARK_COMMIT, f"blocked {series} benchmark")
        audit = meta_model.get("sourceAudit")
        if not isinstance(audit, dict) or not all(
            isinstance(audit.get(key), str) and HASH_RE.fullmatch(audit[key])
            for key in AUDIT_HASH_KEYS
        ):
            raise RejectedInput(f"blocked {series} source audit missing")
        runner_revisions.add(model["revision"])
    if runner_revisions != {revision}:
        raise RejectedInput("blocked series revisions disagree")
    if not (run_dir / "sol-reasoning-q3.game.json").exists() and not (run_dir / "sol-reasoning-q64.game.json").exists():
        return {
            "slug": slug,
            "status": "unavailable",
            "reasonCode": "distribution_http_401",
            "model": {"id": model_id, "revision": revision},
            "evidence": {
                "httpStatus": 401,
                "weightsCached": False,
                "systemOneCalls": 0,
                "neuralForwardCalls": 0,
            },
            "sourceFiles": [
                verification_path.name,
                "sol-reasoning-q3.runner.json",
                "sol-reasoning-q64.runner.json",
            ],
        }
    raise RejectedInput("blocked evidence unexpectedly contains game measurement files")


def _candidate_run_dirs(results_root: Path, slug: str) -> list[Path]:
    slug_dir = results_root / slug
    if not slug_dir.is_dir() or slug_dir.is_symlink():
        return []
    if any(slug_dir.glob("*-q3.game.json")) or (slug_dir / "verification.json").is_file() or (slug_dir / ".verification.json").is_file():
        return [slug_dir]
    candidates = []
    for child in slug_dir.iterdir():
        if not child.is_dir() or child.is_symlink():
            continue
        lowered = child.name.lower()
        if any(word in lowered for word in FORBIDDEN_PATH_WORDS):
            continue
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}", child.name):
            continue
        candidates.append(child)
    return sorted(candidates, key=lambda path: path.name)


def _safe_inventory_path(results_root: Path, value: Any) -> Path:
    if not isinstance(value, str):
        raise RejectedInput("formal path inventory contains a non-path entry")
    candidate = Path(value)
    if any(word in part.lower() for word in FORBIDDEN_PATH_WORDS for part in candidate.parts):
        raise RejectedInput("prototype/private/excluded path in formal inventory")
    try:
        path = candidate.resolve(strict=True)
    except OSError as exc:
        raise RejectedInput("formal path inventory artifact does not exist") from exc
    try:
        relative = path.relative_to(results_root)
    except ValueError as exc:
        raise RejectedInput("formal path inventory points outside results/") from exc
    if any(word in part.lower() for word in FORBIDDEN_PATH_WORDS for part in relative.parts):
        raise RejectedInput("prototype/private path in formal inventory")
    return path


def _load_inventory(results_root: Path) -> tuple[dict[str, list[Path]], dict[str, Path]]:
    inventory_path = results_root.parent / "handoffs" / "formal-results.json"
    inventory = _read_json(inventory_path)
    _require_commit(inventory.get("gameCommit"), GAME_COMMIT, "inventory game")
    _require_commit(inventory.get("benchmarkCommit"), BENCHMARK_COMMIT, "inventory benchmark")
    entries = inventory.get("targets")
    if not isinstance(entries, dict):
        raise RejectedInput("formal path inventory targets missing")
    q3_paths: dict[str, list[Path]] = {}
    availability_paths: dict[str, Path] = {}
    for slug in SLUGS:
        item = entries.get(slug)
        if not isinstance(item, dict):
            continue
        listed = item.get("q3Paths")
        if isinstance(listed, list):
            paths = [_safe_inventory_path(results_root, path) for path in listed]
            for path in paths:
                if not path.name.endswith("-q3.game.json"):
                    raise RejectedInput(f"inventory q3 path has unexpected filename: {slug}")
                relative = path.relative_to(results_root)
                expected_prefix = "baselines" if slug in ("rule", "idle") else slug
                if not relative.parts or relative.parts[0].lower() != expected_prefix:
                    raise RejectedInput(f"inventory path is outside the target directory: {slug}")
            q3_paths[slug] = paths
        evidence = item.get("evidence")
        if slug == "sol-reasoning" and isinstance(evidence, str):
            availability_paths[slug] = _safe_inventory_path(results_root, evidence)
    return q3_paths, availability_paths


def _validate_control(
    slug: str,
    game_path: Path,
    verification_path: Path,
    results_root: Path,
) -> dict[str, Any]:
    game = _read_json(game_path)
    verification = _read_json(verification_path)
    freeze_pins = verification.get("freezePins")
    if verification.get("schema") != "vector-run-cpu-baseline-verification/v1" or not isinstance(freeze_pins, dict):
        raise RejectedInput("CPU baseline verification schema missing")
    _require_commit(freeze_pins.get("gameCommit"), GAME_COMMIT, "baseline game")
    _require_commit(freeze_pins.get("benchmarkCommit"), BENCHMARK_COMMIT, "baseline benchmark")
    if (verification.get("sourceVerification") or {}).get("match") is not True:
        raise RejectedInput("baseline source verification failed")
    if (verification.get("privacyAudit") or {}).get("status") != "passed":
        raise RejectedInput("baseline privacy audit missing")
    metadata = game.get("metadata")
    if not isinstance(metadata, dict):
        raise RejectedInput("baseline game metadata missing")
    _require_commit(game.get("gameCommit"), GAME_COMMIT, "baseline trace game")
    _require_commit((game.get("game") or {}).get("commit"), GAME_COMMIT, "baseline trace game.commit")
    _require_commit(metadata.get("gameCommit"), GAME_COMMIT, "baseline metadata game")
    _require_commit(metadata.get("benchmarkCommit"), BENCHMARK_COMMIT, "baseline metadata benchmark")
    if _count_errors(game.get("runtimeGameInvalidErrors")):
        raise RejectedInput("baseline runtimeGameInvalidErrors present")

    series_items = verification.get("series")
    item = next((x for x in series_items or [] if isinstance(x, dict) and x.get("agent") == slug), None)
    if not isinstance(item, dict):
        raise RejectedInput("baseline series verification missing")
    artifact = item.get("artifact") or {}
    expected_rel = f"baselines/{slug}-q3.game.json"
    if artifact.get("path") not in (expected_rel, f"results/{expected_rel}"):
        raise RejectedInput("baseline artifact path mismatch")
    if artifact.get("sha256") != hashlib.sha256(game_path.read_bytes()).hexdigest():
        raise RejectedInput("baseline artifact SHA-256 mismatch")
    if not isinstance(item.get("cli"), dict) or item["cli"].get("exitCode") != 0 or item["cli"].get("status") != "completed":
        raise RejectedInput("baseline CLI did not complete successfully")
    validator = item.get("traceValidator") or {}
    episodes = game.get("episodes")
    outcomes = item.get("gameOutcomes")
    if (
        validator.get("status") != "passed"
        or validator.get("script") != "scripts/verify-decision-trace.mjs"
        or validator.get("questionCount") != 3
        or validator.get("runCount") != len(episodes or [])
        or len(outcomes or []) != len(episodes or [])
    ):
        raise RejectedInput("baseline trace validator evidence failed")
    for episode, outcome in zip(episodes, outcomes):
        for field in ("seed", "censored", "terminalStatus", "endReason", "survivalSeconds"):
            if field in outcome and outcome[field] is not None and episode.get(field) != outcome[field]:
                raise RejectedInput("baseline verification outcome mismatch")
    if ((verification.get("conditions") or {}).get("gpuUsed")) is not False:
        raise RejectedInput("baseline GPU-free condition missing")
    rows = _episode_rows(game, 3)
    cpu = game.get("hardware") or {}
    if not cpu.get("cpuModel"):
        raise RejectedInput("baseline CPU hardware missing")
    source_path = lambda path: path.resolve().relative_to(results_root).as_posix()
    return {
        "slug": slug,
        "runId": "cpu-baselines",
        "series": "q3",
        "questions": 3,
        "model": {"id": (game.get("agent") or {}).get("model", slug), "revision": "control"},
        "hardware": {"gpu": None, "cpuModel": cpu["cpuModel"], "runtime": cpu.get("runtime")},
        "episodes": rows,
        "episodeSummary": _episode_summary(rows),
        "errors": {"runtimeGameInvalidErrors": 0, "responseErrors": sum(_count_errors(run.get("responseErrors")) for run in game.get("runs", []) if isinstance(run, dict)), "inferenceErrors": 0},
        "decisions": _decision_counts(game),
        "inference": {"notApplicable": True, "recordCount": 0, "forwardCalls": None, "batchShapes": [], "systemOneP50Ms": None, "firstSystemOneMs": None, "remainingSystemOneP50Ms": None, "sameProcessAfterQ3": None, "gpuPeakAllocatedBytes": None, "gpuPeakReservedBytes": None},
        "sourceFiles": {"game": source_path(game_path), "metadata": None, "runner": None, "verification": source_path(verification_path)},
    }


def collect_results(results_root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], list[dict[str, str]]]:
    series_by_slug: dict[str, list[dict[str, Any]]] = {slug: [] for slug in SLUGS}
    unavailable: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, str]] = []
    q3_paths, availability_paths = _load_inventory(results_root)
    for slug, evidence_path in availability_paths.items():
        try:
            run_dir = evidence_path.parent
            blocked = _check_availability(slug, run_dir, evidence_path)
            if not blocked:
                raise RejectedInput("blocked model evidence is not a recognized access block")
            unavailable[slug] = blocked
        except RejectedInput as exc:
            rejected.append({"slug": slug, "runId": evidence_path.parent.name, "series": "availability", "reason": str(exc)})

    for slug in (item[0] for item in TARGETS if item[0] not in ("rule", "idle", "sol-reasoning")):
        for q3_path in q3_paths.get(slug, []):
            run_dir = q3_path.parent
            run_id = run_dir.name
            try:
                verification_path = _verification_path(run_dir, slug, run_dir.name)
                verification = _read_json(verification_path)
                run_id = str(verification.get("runId") or verification.get("attemptId") or run_dir.name)
            except RejectedInput as exc:
                for series in ("q3", "q64"):
                    game_path = q3_path if series == "q3" else q3_path.with_name(q3_path.name.replace("-q3.game.json", "-q64.game.json"))
                    rejected.append(_rejection_record(slug, run_id, series, str(exc), game_path))
                continue
            q3_runner_path = q3_path.with_name(q3_path.name[:-len(".game.json")] + ".runner.json")
            try:
                q3_runner = _read_json(q3_runner_path) if q3_runner_path.is_file() else None
            except RejectedInput:
                q3_runner = None
            for series in ("q3", "q64"):
                game_path = q3_path if series == "q3" else q3_path.with_name(q3_path.name.replace("-q3.game.json", "-q64.game.json"))
                if not game_path.is_file():
                    rejected.append(_rejection_record(slug, run_id, series, "required game artifact missing"))
                    continue
                stem = game_path.name[:-len(".game.json")]
                metadata_path = game_path.with_name(stem + ".metadata.json")
                runner_path = game_path.with_name(stem + ".runner.json")
                if not runner_path.is_file():
                    rejected.append(_rejection_record(slug, run_id, series, "runner artifact missing", game_path))
                    continue
                try:
                    entry = _validate_series(
                        slug,
                        run_id,
                        series,
                        game_path,
                        metadata_path if metadata_path.is_file() else None,
                        runner_path,
                        verification_path,
                        q3_runner,
                        results_root,
                    )
                    series_by_slug[slug].append(entry)
                except RejectedInput as exc:
                    rejected.append(_rejection_record(slug, run_id, series, str(exc), game_path))

    baseline_verification = results_root / "baselines" / "verification.json"
    for slug in ("rule", "idle"):
        for game_path in q3_paths.get(slug, []):
            try:
                series_by_slug[slug].append(_validate_control(slug, game_path, baseline_verification, results_root))
            except RejectedInput as exc:
                rejected.append({"slug": slug, "runId": "cpu-baselines", "series": "q3", "reason": str(exc)})
    return series_by_slug, unavailable, rejected


def build_summary(
    series_by_slug: dict[str, list[dict[str, Any]]],
    unavailable: dict[str, dict[str, Any]],
    rejected: list[dict[str, str]],
) -> dict[str, Any]:
    targets = []
    for slug, label, category in TARGETS:
        series = sorted(series_by_slug.get(slug, []), key=lambda item: (item["runId"], item["series"]))
        pending = [item for item in rejected if item["slug"] == slug and "metadata-only proof pending" in item["reason"]]
        rejected_target = [item for item in rejected if item["slug"] == slug]
        if slug in unavailable:
            status = "unavailable"
        elif pending:
            status = "pending_verification"
        elif rejected_target:
            status = "rejected"
        elif series:
            status = "measured"
        else:
            status = "missing"
        targets.append(
            {
                "slug": slug,
                "name": label,
                "category": category,
                "status": status,
                "unavailability": unavailable.get(slug),
                "pendingVerification": pending,
                "q3": [item for item in series if item["series"] == "q3"],
                "q64": [item for item in series if item["series"] == "q64"],
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "benchmark": {
            "name": "VECTOR RUN",
            "gameCommit": GAME_COMMIT,
            "benchmarkCommit": BENCHMARK_COMMIT,
            "physicsFps": 60,
            "decisionEveryFrames": 8,
            "actionTiming": "realtime; physics continues during inference",
        },
        "targets": targets,
        "excludedInputs": rejected,
    }


def _require_complete(summary: dict[str, Any], rejected: list[dict[str, str]]) -> None:
    if rejected:
        raise RejectedInput("unverified/incomplete input exists; refusing final output")
    for target in summary["targets"]:
        if target["status"] == "missing":
            raise RejectedInput(f"required target missing: {target['slug']}")
        if target["category"] == "model" and target["status"] == "measured" and (not target["q3"] or not target["q64"]):
            raise RejectedInput(f"both q3 and q64 are required: {target['slug']}")
        if target["category"] == "control" and target["status"] == "measured" and not target["q3"]:
            raise RejectedInput(f"q3 control trace missing: {target['slug']}")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# VECTOR RUN 正式ベンチマーク結果",
        "",
        f"game `{GAME_COMMIT}` / benchmark `{BENCHMARK_COMMIT}`。60 FPS、1x共通時計、推論中も物理を進めるrealtime計測です。",
        "",
        "GPU機種が異なるため、system_one_msのモデル間速度順位は付けません。system_one_msはtokenization/wrapperを含むAPI同期時間で、純forward時間ではありません。q3の最初のAPI呼び出しと後続呼び出しを分け、q64は同一プロセスでq3後に実行した記録だけを示します。",
        "",
        "各モデルの標本数は少数です。30秒打切りepisodeは生存時間・距離の下限値として扱い、打切りが1件でもある場合はclear率を表示しません。未測定は成績0や敗北を意味しません。late answerはゲームへ適用されなかった回答数です。",
    ]
    measured = [target for target in summary["targets"] if target["status"] == "measured"]
    unavailable = [target for target in summary["targets"] if target["status"] == "unavailable"]
    for series in ("q3", "q64"):
        lines += ["", f"## {series} episode結果", "", "|対象|revision|GPU|episode|terminal|打切り|平均距離 m|平均観測生存秒|平均jump|clear率|", "|---|---|---|---:|---|---:|---:|---:|---:|---:|"]
        for target in measured:
            for item in target[series]:
                episode = item["episodeSummary"]
                terminal = ", ".join(f"{key}:{count}" for key, count in sorted(episode["terminalCounts"].items()))
                revision = item["model"].get("revision", "")
                lines.append(
                    f"|{target['name']}|`{revision}`|{item['hardware'].get('gpu') or ('CPU: ' + item['hardware'].get('cpuModel', ''))}|{episode['episodeCount']}|{terminal}|{episode['censoredCount']}|{_fmt(episode['meanDistanceMetres'])}|{_fmt(episode['meanObservedSurvivalSeconds'])}|{_fmt(episode['meanJumps'])}|{_fmt(episode.get('clearRate'))}|"
                )
        if unavailable:
            lines += ["", "未測定対象: " + "、".join(f"{target['name']}（配布元401、forward 0）" for target in unavailable)]
        lines += ["", f"## {series} 推論・エラー", "", "|対象|hardware|first system_one ms|後続/系列 p50 ms|forward calls|batch shape|late|欠落回答|response errors|runtime invalid|peak allocated GiB|peak reserved GiB|", "|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
        for target in measured:
            for item in target[series]:
                inf = item["inference"]
                first = inf["firstSystemOneMs"] if series == "q3" else None
                p50 = inf["remainingSystemOneP50Ms"] if series == "q3" else inf["systemOneP50Ms"]
                shapes = ", ".join(
                    f"{ 'x'.join(map(str, shape['inputIdsShape'])) }×{shape['batches']}"
                    for shape in inf["batchShapes"]
                ) or "—"
                alloc = inf["gpuPeakAllocatedBytes"]
                reserved = inf["gpuPeakReservedBytes"]
                lines.append(
                    f"|{target['name']}|{item['hardware'].get('gpu') or ('CPU: ' + item['hardware'].get('cpuModel', ''))}|{_fmt(first)}|{_fmt(p50)}|{inf['forwardCalls'] if inf.get('forwardCalls') is not None else '—'}|{shapes}|{item['decisions']['lateAnswers']}|{item['decisions']['missingQuestionAnswers']}|{item['errors']['responseErrors']}|{item['errors']['runtimeGameInvalidErrors']}|{_fmt(alloc / (1024**3) if alloc is not None else None)}|{_fmt(reserved / (1024**3) if reserved is not None else None)}|"
                )
    if unavailable:
        lines += ["", "## 未測定", ""]
        for target in unavailable:
            evidence = target["unavailability"]["evidence"]
            lines.append(
                f"- {target['name']}: 配布元HTTP 401、固定revisionのcacheなし、System One呼び出し {evidence['systemOneCalls']}、neural forward {evidence['neuralForwardCalls']}。スコアや敗北としては扱いません。"
            )
    lines += ["", "検証済みtraceとrunner計測から生成。公開時点の対象status:"]
    lines.extend(f"- {target['name']}: {target['status']}" for target in summary["targets"])
    return "\n".join(lines) + "\n"


def _self_test(results_root: Path) -> None:
    series, unavailable, rejected = collect_results(results_root)
    lux_q3 = [item for item in series.get("lux", []) if item["series"] == "q3"]
    if not lux_q3:
        raise RejectedInput("self-test requires the official Lux q3 fixture")
    for slug in ("eos", "sol", "nox", "lux", "vega"):
        present = {item["series"] for item in series.get(slug, [])}
        if present != {"q3", "q64"}:
            raise RejectedInput(f"self-test requires both officially verified series: {slug}")
    if "sol-reasoning" not in unavailable or unavailable["sol-reasoning"]["evidence"]["neuralForwardCalls"] != 0:
        raise RejectedInput("self-test requires the pinned HTTP 401/zero-forward evidence")
    _require_commit(GAME_COMMIT, GAME_COMMIT, "self-test game")
    try:
        _require_commit(BENCHMARK_COMMIT, "0" * 40, "self-test benchmark")
    except RejectedInput:
        pass
    else:
        raise RejectedInput("self-test failed to reject a mismatched pin")
    try:
        _safe_results_root(Path("C:/prototype/private/results"))
    except RejectedInput:
        pass
    else:
        raise RejectedInput("self-test failed to reject prototype/private path")
    try:
        _safe_inventory_path(results_root, str(results_root / "excluded" / "kai-q3.game.json"))
    except RejectedInput:
        pass
    else:
        raise RejectedInput("self-test failed to reject excluded results")
    other_rejections = [item for item in rejected if item["slug"] != "kai"]
    if other_rejections:
        raise RejectedInput("official inventory contains rejected input outside pending Kai proof")
    kai_pending = [item for item in rejected if item["slug"] == "kai"]
    if kai_pending and (
        {item["series"] for item in kai_pending} != {"q3", "q64"}
        or any("metadata-only proof pending" not in item["reason"] for item in kai_pending)
        or any(not HASH_RE.fullmatch(item.get("runnerReportedGameSha256", "")) for item in kai_pending)
        or any(not HASH_RE.fullmatch(item.get("publishedGameSha256", "")) for item in kai_pending)
    ):
        raise RejectedInput("self-test failed to retain both Kai hashes as pending verification")
    kai_series = {item["series"] for item in series.get("kai", [])}
    if not kai_pending and kai_series != {"q3", "q64"}:
        inventory = _read_json(results_root.parent / "handoffs" / "formal-results.json")
        kai_inventory = (inventory.get("targets") or {}).get("kai")
        if (
            kai_series
            or not isinstance(kai_inventory, dict)
            or kai_inventory.get("status") != "pending"
            or kai_inventory.get("q3Paths") != []
        ):
            raise RejectedInput("self-test expected Kai proof acceptance or explicit pending inventory with no trace paths")
    allowed_proof = {
        "artifactTransformations": [{
            "artifact": "trace.game.json",
            "operation": "normalize_runtime_history_cache_paths",
            "beforeSha256": "a" * 64,
            "afterSha256": "b" * 64,
            "changedPaths": ["$.metadata.runtimeHistory.cachePath"],
            "deepDiffVerified": True,
        }]
    }
    if not _metadata_transform_proof(allowed_proof, "trace.game.json", "a" * 64, "b" * 64):
        raise RejectedInput("self-test failed to accept the strict metadata-only proof shape")
    allowed_proof["artifactTransformations"][0]["changedPaths"] = ["$.runs[0].answer"]
    if _metadata_transform_proof(allowed_proof, "trace.game.json", "a" * 64, "b" * 64):
        raise RejectedInput("self-test accepted a non-metadata transformation path")
    rule_rows = [item for item in series.get("rule", []) if item["series"] == "q3"]
    if rule_rows and (rule_rows[0]["episodeSummary"]["censoredCount"] != 5 or "clearRate" in rule_rows[0]["episodeSummary"]):
        raise RejectedInput("self-test failed to preserve censored-control semantics")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--results-root", default=str(repo_root / "results"))
    parser.add_argument("--check", action="store_true", help="validate and print a compact inventory; do not write files")
    parser.add_argument("--self-test", action="store_true", help="check Lux fixture acceptance and pin/path rejection")
    parser.add_argument("--write", action="store_true", help="write results/summary.json and docs/results.md only with complete official coverage")
    args = parser.parse_args(argv)

    try:
        root = _safe_results_root(args.results_root)
        if args.self_test:
            _self_test(root)
            print("self-test: pass (official series, Vega verifier, blocked evidence, Kai hash/provenance gate, pins, paths)")
        series, unavailable, rejected = collect_results(root)
        summary = build_summary(series, unavailable, rejected)
        accepted_count = sum(len(items) for items in series.values())
        print(f"accepted series={accepted_count}; unavailable={len(unavailable)}; rejected series={len(rejected)}")
        for slug, _, _ in TARGETS:
            if series.get(slug):
                counts = {series_name: sum(item["series"] == series_name for item in series[slug]) for series_name in ("q3", "q64")}
                print(f"  {slug}: q3={counts['q3']} q64={counts['q64']}")
            elif slug in unavailable:
                print(f"  {slug}: unavailable ({unavailable[slug]['reasonCode']}, forward=0)")
        for item in rejected:
            prefix = "pending" if "metadata-only proof pending" in item["reason"] else "excluded"
            hashes = ""
            if "runnerReportedGameSha256" in item:
                hashes = f" runner-reported={item['runnerReportedGameSha256']} published={item['publishedGameSha256']}"
            print(f"  {prefix} {item['slug']}/{item['runId']} {item['series']}: {item['reason']}{hashes}")
        if args.write:
            _require_complete(summary, rejected)
            output_path = repo_root / "results" / "summary.json"
            docs_path = repo_root / "docs" / "results.md"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            docs_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            docs_path.write_text(render_markdown(summary), encoding="utf-8")
            print("wrote results/summary.json and docs/results.md")
        elif not args.check and not args.self_test:
            parser.print_help()
        return 0
    except RejectedInput as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
