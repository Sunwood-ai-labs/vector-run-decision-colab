"""HTTP adapter and pinned real-GPU loader for Decision System One models.

The game repository owns observations, Japanese questions, pacing and traces.
This service accepts their JSON object unchanged and never supplies fallback actions.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from typing import Any

from server.decision_adapter import invoke_system_one


class App:
    def __init__(self, model: Any, model_name: str, metadata: dict[str, Any] | None = None) -> None:
        self.model = model
        self.model_name = model_name
        self.metadata = metadata or {}
        self.lock = threading.Lock()
        self.request_index = 0
        self.neural_forward_calls = 0
        self.neural_forward_batches: list[dict[str, Any]] = []
        runtime = getattr(model, "runtime", None)
        backend = getattr(runtime, "backend", None)
        neural_model = getattr(backend, "model", None)
        self.forward_hook = (
            neural_model.register_forward_pre_hook(self._count_forward, with_kwargs=True)
            if hasattr(neural_model, "register_forward_pre_hook")
            else None
        )

    def _count_forward(self, module: Any, inputs: Any, kwargs: dict[str, Any]) -> None:
        self.neural_forward_calls += 1
        input_ids = kwargs.get("input_ids")
        shape = list(input_ids.shape) if hasattr(input_ids, "shape") else None
        self.neural_forward_batches.append({
            "input_ids_shape": shape,
            "batch_size": shape[0] if shape else None,
            "padded_tokens_per_question": shape[1] if shape and len(shape) > 1 else None,
        })

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        served, _raw = self.answer_with_raw(payload)
        return served

    def answer_with_raw(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        import torch

        with self.lock, torch.inference_mode():
            cuda = torch.cuda.is_available()
            if cuda:
                torch.cuda.synchronize()
            started = time.perf_counter()
            self.neural_forward_calls = 0
            self.neural_forward_batches = []
            result = invoke_system_one(self.model, payload)
            if cuda:
                torch.cuda.synchronize()
            elapsed = (time.perf_counter() - started) * 1000
            self.request_index += 1
            measured = dict(result)
            measured["measurements"] = {
                "system_one_ms": elapsed,
                "timing_scope": "synchronized system_one call including tokenization and wrapper; not isolated neural forward",
                "neural_forward_calls": self.neural_forward_calls if self.forward_hook else None,
                "neural_forward_batches": list(self.neural_forward_batches) if self.forward_hook else None,
                "request_index": self.request_index,
                "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated() if cuda else None,
                "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved() if cuda else None,
            }
            return measured, result


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def end(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self.end(200, {"ok": True, "model": app.model_name, "metadata": app.metadata})
            elif path == "/v1/models":
                self.end(200, {"data": [{"id": app.model_name}]})
            else:
                self.end(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/v1/systemone":
                self.end(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("content-length") or "0")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self.end(200, app.answer(payload))
            except Exception as error:  # API errors are returned to the game CLI.
                self.end(400, {"error": str(error)})

    return Handler


def load_model(
    repo: str,
    revision: str | None = None,
    base_revision: str | None = None,
    dtype: str = "bfloat16",
    quantization: str = "none",
):
    from transformers import AutoModel

    if not revision:
        raise ValueError("A pinned Hugging Face commit revision is required")
    if dtype != "bfloat16" or quantization != "none":
        raise ValueError("Audited Decision loader requires mixed BF16/FP32 resident weights; external quantization/offload is unsupported")
    if repo.endswith("Vega-27B") and base_revision != "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0":
        raise ValueError("Vega requires the audited Qwen/Qwen3.8-27B base revision")
    print(f"loading {repo}@{revision} on cuda:0", file=sys.stderr)
    model = AutoModel.from_pretrained(
        repo,
        revision=revision,
        trust_remote_code=True,
        device_map={"": "cuda:0"},
        dtype="auto",
        bf16_resident=True,
    )
    if hasattr(model, "eval"):
        model.eval()
    return model
