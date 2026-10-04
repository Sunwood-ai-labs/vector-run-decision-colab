import unittest

from server.decision_adapter import invoke_system_one, system_one_inputs


class FakeSystemOne:
    def __init__(self):
        self.received = None

    def system_one(self, *, state, questions):
        self.received = (state, questions)
        return {
            "model": "fake-unit-model",
            "answers": {
                "action": {"type": "choice", "choice": "jump", "probabilities": {"wait": 0.1, "jump": 0.8, "release": 0.1}},
                "commit": {"type": "noul", "noul": 0.85},
                "danger": {"type": "score", "score": 1.2},
            },
            "usage": {"input_tokens": 7, "output_tokens": 0},
        }


class DecisionAdapterTests(unittest.TestCase):
    def test_passes_json_state_and_japanese_questions_unchanged(self):
        state = {"visible": {"runner": {"grounded": True}, "tick": 480}}
        questions = {
            "action": {"type": "choice", "criteria": {"wait": "待つ", "jump": "跳ぶ", "release": "離す"}, "instructions": "見えている状態だけで選んでください"},
            "commit": {"type": "noul", "instructions": "今すぐ行動を確定すべきですか"},
            "danger": {"type": "score", "criteria": ["低", "中", "高"], "instructions": "危険度を評価してください"},
            **{f"p{i}": {"type": "noul", "instructions": f"probe {i}"} for i in range(61)},
        }
        payload = {"model": "kai", "state": state, "questions": questions}
        self.assertIs(system_one_inputs(payload)[0], state)
        self.assertIs(system_one_inputs(payload)[1], questions)

        model = FakeSystemOne()
        response = invoke_system_one(model, payload)
        self.assertIs(model.received[0], state)
        self.assertIs(model.received[1], questions)
        self.assertEqual(len(model.received[1]), 64)
        self.assertEqual(set(model.received[1]), {"action", "commit", "danger", *(f"p{i}" for i in range(61))})
        self.assertEqual(response["answers"]["action"]["choice"], "jump")
        self.assertEqual(response["answers"]["commit"]["noul"], 0.85)
        self.assertEqual(response["answers"]["danger"]["score"], 1.2)
        self.assertEqual(response["model"], "fake-unit-model")
        self.assertEqual(response["usage"]["input_tokens"], 7)

    def test_rejects_non_object_state_and_empty_questions(self):
        with self.assertRaisesRegex(ValueError, "state must be a JSON object"):
            system_one_inputs({"state": "{}", "questions": {"action": {}}})
        with self.assertRaisesRegex(ValueError, "nonempty JSON object"):
            system_one_inputs({"state": {}, "questions": {}})


if __name__ == "__main__":
    unittest.main()
