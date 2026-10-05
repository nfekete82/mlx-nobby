import json
import tempfile
import unittest
from pathlib import Path

from agent import model_evaluations


class ModelEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "model-evaluations.json"

    def test_record_persists_metrics_and_latest_decision(self):
        first = model_evaluations.record(
            "owner/model",
            kind="chat",
            status="candidate",
            reason="Worth testing",
            metrics={"generation_tps": 30.5},
            source="model-scout",
            path=self.path,
        )
        second = model_evaluations.record(
            "owner/model",
            kind="chat",
            status="rejected",
            reason="Slower on this Mac",
            compared_to="owner/baseline",
            metrics={"generation_delta_pct": -4.2, "quality_equal": True},
            source="manual-benchmark",
            path=self.path,
        )

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["evaluations"]), 2)
        self.assertEqual(model_evaluations.latest("OWNER/MODEL", kind="chat", path=self.path), second)
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(model_evaluations.is_rejected("owner/model", kind="chat", path=self.path))

    def test_kind_specific_decisions_do_not_collide(self):
        model_evaluations.record(
            "owner/shared",
            kind="chat",
            status="keep",
            reason="Best chat model",
            path=self.path,
        )
        model_evaluations.record(
            "owner/shared",
            kind="coding",
            status="rejected",
            reason="Weak coding result",
            path=self.path,
        )

        self.assertEqual(
            model_evaluations.latest("owner/shared", kind="chat", path=self.path)["status"],
            "keep",
        )
        self.assertEqual(
            model_evaluations.latest("owner/shared", kind="coding", path=self.path)["status"],
            "rejected",
        )
        latest = model_evaluations.list_latest(path=self.path)
        self.assertEqual({(item["kind"], item["status"]) for item in latest}, {("chat", "keep"), ("coding", "rejected")})

    def test_corrupt_file_degrades_to_empty_registry(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(model_evaluations.load(self.path), [])

    def test_invalid_status_kind_and_metric_are_rejected(self):
        with self.assertRaises(ValueError):
            model_evaluations.record("owner/model", kind="unknown", status="keep", reason="x", path=self.path)
        with self.assertRaises(ValueError):
            model_evaluations.record("owner/model", kind="chat", status="unknown", reason="x", path=self.path)
        with self.assertRaises(ValueError):
            model_evaluations.record(
                "owner/model",
                kind="chat",
                status="tested",
                reason="x",
                metrics={"nested": {"bad": True}},
                path=self.path,
            )


if __name__ == "__main__":
    unittest.main()
