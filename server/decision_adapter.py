"""Pure-Python adapter for the public Decision System One model API."""
from __future__ import annotations

from typing import Any


def system_one_inputs(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the transport envelope without interpreting game state or questions."""
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    state = payload.get("state")
    questions = payload.get("questions")
    if not isinstance(state, dict):
        raise ValueError("state must be a JSON object")
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a nonempty JSON object")
    if any(not isinstance(key, str) or not key for key in questions):
        raise ValueError("question ids must be nonempty strings")
    return state, questions


def invoke_system_one(model: Any, payload: Any) -> dict[str, Any]:
    """Pass the game-owned visible state and question text through unchanged."""
    state, questions = system_one_inputs(payload)
    response = model.system_one(state=state, questions=questions)
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("system_one must return a JSON object with an answers object")
    return response
