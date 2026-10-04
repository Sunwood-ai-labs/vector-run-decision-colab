"""Decision Lane の System One エンドポイント。

--mock（既定）はコースに書いたルールで答えます。GPU も transformers も要りません。
--model vllm-sr/Decision-2.0-Kai-0.6B で公開モデルをその場で読みます。
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "policy.json").read_text(encoding="utf-8"))
ACTIONS = ("hold", "jump", "slide", "strike")


def rule_action(state: dict[str, Any], policy: dict[str, Any] | None = None) -> str:
    policy = POLICY if policy is None else policy
    runner = state.get("runner") or {}
    if not runner.get("grounded") or runner.get("sliding") or runner.get("striking"):
        return "hold"
    hazards = [hazard for hazard in state.get("hazards") or [] if hazard.get("dx", 0) > -8]
    hazards.sort(key=lambda hazard: (hazard.get("dx", 0), str(hazard.get("id", ""))))
    if not hazards:
        return "hold"
    nearest = hazards[0]
    kind = nearest.get("kind")
    dx = nearest.get("dx", 0)
    if kind in ("crate", "gap") and dx <= policy["jumpMaxDx"]:
        return "jump"
    if kind == "beam" and dx <= policy["slideMaxDx"]:
        return "slide"
    if kind == "drone" and dx <= policy["strikeMaxDx"]:
        return "strike"
    return "hold"


def _unit(chosen: str) -> dict[str, float]:
    share = 0.02
    probs = {action: share for action in ACTIONS}
    probs[chosen] = 1 - share * (len(ACTIONS) - 1)
    return probs


def mock_answers(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    action = rule_action(state)
    answers: dict[str, Any] = {}
    if "action" in questions:
        answers["action"] = {
            "type": "choice",
            "choice": action,
            "probabilities": _unit(action),
            "confidence": 0.86,
        }
    if "commit" in questions:
        answers["commit"] = {"type": "noul", "noul": 0.97 if action != "hold" else 0.04}
    if "danger" in questions:
        if not state.get("hazards"):
            score = 0.04
        elif action == "hold":
            score = 1.02
        else:
            score = 1.96
        answers["danger"] = {"type": "score", "score": score}
    probes = state.get("probes") or []
    for key, question in questions.items():
        if not (isinstance(key, str) and key.startswith("p") and key[1:].isdigit()):
            continue
        if not isinstance(question, dict) or question.get("type") != "noul":
            continue
        index = int(key[1:])
        value = bool(probes[index]) if index < len(probes) else False
        answers[key] = {"type": "noul", "noul": 0.99 if value else 0.01}
    return answers


def self_test() -> None:
    runner = {"grounded": True, "sliding": False, "striking": False}
    cases = [
        ({"runner": runner, "hazards": [{"id": "h", "kind": "crate", "dx": 80}]}, "jump"),
        ({"runner": runner, "hazards": [{"id": "h", "kind": "crate", "dx": 200}]}, "hold"),
        ({"runner": runner, "hazards": [{"id": "h", "kind": "beam", "dx": 70}]}, "slide"),
        ({"runner": runner, "hazards": [{"id": "h", "kind": "drone", "dx": 90}]}, "strike"),
        ({"runner": runner, "hazards": [{"id": "h", "kind": "gap", "dx": 40}]}, "jump"),
        ({"runner": {**runner, "grounded": False}, "hazards": [{"id": "h", "kind": "crate", "dx": 40}]}, "hold"),
        ({"runner": {**runner, "sliding": True}, "hazards": [{"id": "h", "kind": "beam", "dx": 10}]}, "hold"),
        ({"runner": runner, "hazards": []}, "hold"),
    ]
    for state, expected in cases:
        got = rule_action(state)
        if got != expected:
            raise SystemExit(f"self-test failed: {state} -> {got}, expected {expected}")
    answers = mock_answers(
        {"runner": runner, "hazards": [{"id": "h", "kind": "drone", "dx": 40}], "probes": [True, False]},
        {"action": {}, "commit": {}, "danger": {}, "p0": {"type": "noul"}, "p1": {"type": "noul"}},
    )
    if answers["action"]["choice"] != "strike" or answers["p0"]["noul"] < 0.5 or answers["p1"]["noul"] >= 0.5:
        raise SystemExit(f"mock answers failed: {answers}")
    print("decision_server self-test ok")


class App:
    def __init__(self, model: Any, model_name: str) -> None:
        self.model = model
        self.model_name = model_name

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = payload.get("state")
        questions = payload.get("questions")
        if isinstance(state, str):
            state = json.loads(state)
        if not isinstance(state, dict) or not isinstance(questions, dict) or not questions:
            raise ValueError("state object and nonempty questions are required")
        if self.model is None:
            return {
                "model": self.model_name,
                "answers": mock_answers(state, questions),
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
        return self.model.system_one(state=state, questions=questions)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def end(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("content-length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self.end(200, {"ok": True, "model": app.model_name, "mock": app.model is None})
                return
            if path == "/v1/models":
                self.end(200, {"data": [{"id": app.model_name}]})
                return
            self.end(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("content-length") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            if path != "/v1/systemone":
                self.end(404, {"error": "not found"})
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                self.end(200, app.answer(payload))
            except Exception as error:  # noqa: BLE001 - return the model or JSON error to the bench
                self.end(400, {"error": str(error)})

    return Handler


def load_model(repo: str):
    from transformers import AutoModel

    print(f"loading {repo}", file=sys.stderr)
    return AutoModel.from_pretrained(repo, trust_remote_code=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Decision Lane System One server")
    parser.add_argument("--model", default="", help="Hugging Face repo, for example vllm-sr/Decision-2.0-Kai-0.6B")
    parser.add_argument("--mock", action="store_true", help="Answer with the written course rule")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.model and not args.mock:
        model = load_model(args.model)
        name = args.model
    else:
        model = None
        name = "decision-lane-mock"
    app = App(model, name)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"Decision Lane listening on http://{args.host}:{args.port} ({name})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
