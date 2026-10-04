import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from experiments.colab.run_bench import (
    GAME_REPOSITORY,
    READY_STATUS,
    RUNTIME_HISTORY_FIELDS,
    SERIES,
    MeasuredApp,
    blocked_report,
    environment,
    game_report_status,
    timing_summary,
    valid_sha,
    validate_handoff,
    validate_runtime_history,
    write_blocked_reports,
)


def ready_handoff(commit="a" * 40):
    question_keys = ["action", "commit", "danger", *(f"p{i}" for i in range(61))]
    return {
        "status": READY_STATUS,
        "game": {"repo": GAME_REPOSITORY, "sourceCommit": "b" * 40, "measurementCommit": commit},
        "publicState": {
            "schema": "vector-run-visible-state/v1",
            "forbiddenFromModelRequest": ["seed", "rng", "nextEncounter", "encounterTime"],
        },
        "wireContract": {
            "requestExactTopLevelKeys": ["model", "state", "questions"],
            "questionKeysExact": question_keys,
            "questionsPerCall": {
                "flagMeaning": "simultaneous_questions_per_api_call",
                "q3": ["action", "commit", "danger"],
                "q64": question_keys,
            },
            "requestShape": {"state": {"schema": "vector-run-visible-state/v1"}, "questions": {
                "action": {"type": "choice", "instructions": "日本語", "criteria": {"wait": "日本語", "jump": "日本語", "release": "日本語"}},
                "commit": {"type": "noul", "instructions": "日本語"},
                "danger": {"type": "score", "instructions": "日本語", "criteria": ["safe", "caution", "danger"]},
                "p0..p60": {"type": "noul", "instructions": "真偽値を質問"},
            }},
            "responseShape": {"answers": {
                "action": {"type": "choice", "choice": "wait|jump|release", "probabilities": "object"},
                "commit": {"type": "noul", "noul": "number"},
                "danger": {"type": "score", "score": "number"},
                "p0..p60": {"type": "noul", "noul": "number"},
            }},
        },
        "resultDraft": {
            "schema": "vector-run-decision-bench/v1",
            "validationStatus": "passed",
            "validator": {"status": "passed", "command": "node scripts/verify-decision-trace.mjs"},
        },
    }


class ColabRunnerTests(unittest.TestCase):
    def test_full_sha_validation(self):
        self.assertTrue(valid_sha("a" * 40))
        self.assertTrue(valid_sha("A" * 40))
        self.assertFalse(valid_sha("a" * 39))
        self.assertFalse(valid_sha("not-a-commit"))

    def test_measurement_null_blocks_and_matching_pin_is_allowed(self):
        handoff = ready_handoff()
        handoff["game"]["measurementCommit"] = None
        reasons = validate_handoff(handoff, "a" * 40)
        self.assertTrue(any("measurementCommit is null" in reason for reason in reasons))

        handoff["game"]["measurementCommit"] = "a" * 40
        self.assertEqual(validate_handoff(handoff, "a" * 40), [])
        self.assertTrue(validate_handoff(handoff, "b" * 40))

    def test_root_measurement_pin_is_supported_but_never_source_commit(self):
        handoff = ready_handoff()
        handoff["measurementCommit"] = handoff["game"].pop("measurementCommit")
        self.assertEqual(validate_handoff(handoff, "a" * 40), [])

        handoff["game"]["measurementCommit"] = "a" * 40
        handoff["measurementCommit"] = "c" * 40
        self.assertTrue(any("disagree" in reason for reason in validate_handoff(handoff, "a" * 40)))

    def test_source_commit_and_unreviewed_handoff_never_enable_measurement(self):
        handoff = {
            "status": "design_in_progress_not_ready_for_measurement",
            "game": {"repo": GAME_REPOSITORY, "sourceCommit": "a" * 40},
        }
        reasons = validate_handoff(handoff, "a" * 40)
        self.assertTrue(any("ready_for_measurement" in reason for reason in reasons))
        self.assertTrue(any("measurementCommit is null" in reason for reason in reasons))

    def test_handoff_requires_structured_question_contract_and_trace_validator(self):
        handoff = ready_handoff()
        handoff["wireContract"]["questionsPerCall"]["q3"] = ["action", "commit"]
        handoff["resultDraft"]["validationStatus"] = "pending"
        reasons = validate_handoff(handoff, "a" * 40)
        self.assertTrue(any("questionsPerCall" in reason for reason in reasons))
        self.assertTrue(any("validationStatus must be passed" in reason for reason in reasons))

    def test_runtime_history_requires_tri_state_values_and_evidence(self):
        history = {"model": "kai", **{field: None for field in RUNTIME_HISTORY_FIELDS}}
        history["evidence"] = {field: "unknown; no session record supplied" for field in RUNTIME_HISTORY_FIELDS}
        normalized, errors = validate_runtime_history(history, "kai")
        self.assertEqual(errors, [])
        self.assertIsNone(normalized["weightsCached"])
        history["runtimeReused"] = 0
        normalized, errors = validate_runtime_history(history, "kai")
        self.assertIsNone(normalized)
        self.assertTrue(any("runtimeReused" in error for error in errors))

    def test_cuda_probe_exception_is_recorded_instead_of_raising(self):
        class BrokenCuda:
            @staticmethod
            def is_available():
                raise RuntimeError("driver probe failed")

        fake_torch = SimpleNamespace(version=SimpleNamespace(cuda="13.0"), cuda=BrokenCuda())
        env = environment(fake_torch)
        self.assertIsNone(env["gpu"])
        self.assertIn("driver probe failed", env["gpu_probe_error"])

    def test_game_report_statuses_are_captured_without_aggregate_success(self):
        status = game_report_status({"status": "partial", "episodes": [{"terminalStatus": "unavailable"}, {"status": "invalid"}]}, "valid")
        self.assertEqual(status["assessment"], "raw_status_fields_captured")
        values = {value for field in status["statusFields"] for value in field["valueCounts"]}
        self.assertEqual(values, {"partial", "unavailable", "invalid"})
        self.assertEqual(status["aggregateMeasurementStatus"], "not_aggregated")

    def test_gpu_unavailable_report_is_blocked_and_never_a_game_result(self):
        model = {"repo": "example/model", "revision": "a" * 40}
        metadata = {"gameCommit": "b" * 40, "benchmarkCommit": "c" * 40}
        runtime_history = {"model": "example-model", **{field: None for field in RUNTIME_HISTORY_FIELDS}, "evidence": {field: "unknown" for field in RUNTIME_HISTORY_FIELDS}}
        report = blocked_report(
            model, metadata, {"gpu": None}, "q3", 3, (101, 202, 303, 404, 505),
            runtime_history,
            ["CUDA GPU unavailable; no CPU or mock benchmark attempted"],
        )
        self.assertEqual(report["runnerStatus"], "blocked")
        self.assertEqual(report["contract"]["timeLimitClassification"], "censored; never a clear or completed collision benchmark")
        self.assertNotIn("gameReport", report)
        self.assertNotIn("episodes", report)

    def test_blocked_preflight_writes_both_series(self):
        args = SimpleNamespace(game_commit="a" * 40, benchmark_commit="b" * 40, dtype="bfloat16", quantization="none")
        model = {"name": "Kai", "repo": "vllm-sr/Decision-2.0-Kai-0.6B", "revision": "c" * 40}
        with tempfile.TemporaryDirectory() as temporary:
            runtime_history = {"model": "kai", **{field: None for field in RUNTIME_HISTORY_FIELDS}, "evidence": {field: "unknown" for field in RUNTIME_HISTORY_FIELDS}}
            paths = write_blocked_reports(
                Path(temporary), model, {"gpu": None}, args,
                {"physicsHz": 120, "decisionEveryTicks": 16, "actions": ["wait", "jump", "release"]},
                runtime_history,
                ["canonical game handoff measurementCommit is null; measurement is prohibited"],
            )
            self.assertEqual([p.name for p in paths], ["kai-q3.runner.json", "kai-q64.runner.json"])
            for path, (_series, questions, seeds) in zip(paths, SERIES):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["runnerStatus"], "blocked")
                self.assertEqual(payload["contract"]["questions"], questions)
                self.assertEqual(payload["contract"]["questionCountPerApiCall"], questions)
                self.assertEqual(payload["contract"]["seeds"], list(seeds))

    def test_measured_wrapper_keeps_raw_request_and_late_model_response(self):
        class Adapter:
            def answer_with_raw(self, request):
                raw = {"answers": {"action": {"type": "choice", "choice": "wait"}}}
                return {**raw, "measurements": {"system_one_ms": 12.5}}, raw

        request = {"state": {"tick": 16}, "questions": {"action": {"instructions": "待つべきですか"}}}
        measured = MeasuredApp(Adapter())
        measured.begin_series("q3")
        served = measured.answer(request)
        self.assertEqual(served["answers"]["action"]["choice"], "wait")
        self.assertTrue(measured.records[0]["firstApiCallAfterModelLoad"])
        self.assertIs(measured.records[0]["request"], request)
        self.assertEqual(measured.records[0]["modelResponse"], {"answers": {"action": {"type": "choice", "choice": "wait"}}})

    def test_timing_summary_keeps_first_warm_steady_and_second_windows(self):
        records = [
            {"phase": "first", "windowIndex1s": 0, "system_one_ms": 10, "serverRequestMs": 12, "status": "ok"},
            {"phase": "warm", "windowIndex1s": 0, "system_one_ms": 8, "serverRequestMs": 9, "status": "ok"},
            {"phase": "steady", "windowIndex1s": 1, "system_one_ms": 7, "serverRequestMs": 8, "status": "ok"},
        ]
        summary = timing_summary(records)
        self.assertEqual(summary["first"]["systemOne"]["count"], 1)
        self.assertEqual(summary["warm"]["systemOne"]["count"], 1)
        self.assertEqual(summary["steady"]["systemOne"]["count"], 1)
        self.assertEqual([window["index"] for window in summary["windows1s"]], [0, 1])


if __name__ == "__main__":
    unittest.main()
