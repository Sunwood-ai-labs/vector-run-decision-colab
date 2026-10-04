"""Check notebook JSON, empty outputs and canonical-game pin consistency."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/vector_run_decision_colab.ipynb"
HANDOFF = ROOT / "handoffs/canonical-game.json"
MODEL_MANIFEST = ROOT / "experiments/colab/model-manifest.json"
SHA = re.compile(r"^[0-9a-fA-F]{40}$")
sys.path.insert(0, str(ROOT))
from experiments.colab.run_bench import validate_handoff


def _assigned_value(module: ast.Module, name: str) -> Any:
    for statement in module.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(statement.value)
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.target.id == name:
            return ast.literal_eval(statement.value)
    raise ValueError(f"notebook parameter {name} is missing")


def validate() -> list[str]:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))
    manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    if notebook.get("nbformat") != 4 or not isinstance(notebook.get("cells"), list):
        errors.append("notebook must use nbformat 4 with a cell list")
    code_cells = []
    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") == "code":
            if cell.get("outputs") != [] or cell.get("execution_count") is not None:
                errors.append(f"code cell {index} contains saved execution output")
            source = "".join(cell.get("source", []))
            try:
                code_cells.append(ast.parse(source))
            except SyntaxError as error:
                errors.append(f"code cell {index} has invalid Python: {error}")
    if not code_cells:
        errors.append("notebook has no Python code cells")
        return errors
    try:
        game_commit = _assigned_value(code_cells[0], "GAME_COMMIT")
        benchmark_commit = _assigned_value(code_cells[0], "BENCHMARK_COMMIT")
        model_choices = _assigned_value(code_cells[0], "MODEL_CHOICES")
    except (ValueError, TypeError, SyntaxError) as error:
        errors.append(str(error))
        return errors
    for name, pin in (("GAME_COMMIT", game_commit), ("BENCHMARK_COMMIT", benchmark_commit)):
        if pin is not None and (not isinstance(pin, str) or not SHA.fullmatch(pin)):
            errors.append(f"{name} must be None or a full 40-character commit SHA")
    game = handoff.get("game") if isinstance(handoff.get("game"), dict) else {}
    nested_commit = game.get("measurementCommit")
    root_commit = handoff.get("measurementCommit")
    measurement_commit = nested_commit or root_commit
    handoff_ready = isinstance(measurement_commit, str) and not validate_handoff(handoff, measurement_commit)
    if not handoff_ready:
        if game_commit is not None or benchmark_commit is not None:
            errors.append("notebook pins must stay unset until ready status, measurementCommit, wire contract and trace validator all pass")
    else:
        if not isinstance(game_commit, str) or game_commit.lower() != measurement_commit.lower():
            errors.append("notebook GAME_COMMIT must match finalized game.measurementCommit or root measurementCommit")
        if benchmark_commit is None:
            errors.append("notebook BENCHMARK_COMMIT must be pinned after the canonical measurement gate passes")
    models = manifest.get("models", [])
    if len(models) != 7:
        errors.append("audited manifest must retain all seven models")
    for model in models:
        if not SHA.fullmatch(str(model.get("revision", ""))):
            errors.append(f"model {model.get('name')} is missing its pinned model revision")
    expected_choices = tuple(re.sub(r"[^a-z0-9_-]+", "-", str(model.get("name", "")).lower()).strip("-") for model in models)
    if tuple(model_choices) != expected_choices:
        errors.append("notebook MODEL_CHOICES must match the seven audited manifest models in order")
    return errors


if __name__ == "__main__":
    failures = validate()
    if failures:
        raise SystemExit("\n".join(failures))
    print("Colab notebook JSON, empty outputs, model revisions and game pins verified")
