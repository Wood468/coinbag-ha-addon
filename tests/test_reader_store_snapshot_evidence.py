"""Offline producer-evidence regression tests; no web store, credentials or HA needed."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "pogo-store-reader" / "store_snapshot.py"
spec = importlib.util.spec_from_file_location("reader_store_snapshot", PATH)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class StoreSnapshotEvidenceTests(unittest.TestCase):
    def test_stabilises_only_after_two_unchanged_passes(self):
        observations = [
            [{"name": "boxes", "count": 1}],
            [{"name": "boxes", "count": 3}],
            [{"name": "boxes", "count": 3}],
            [{"name": "boxes", "count": 3}],
        ]
        calls = []
        def read():
            return observations[len(calls) - 1]
        passes, stable, sections = snapshot.scroll_until_stable(
            read, lambda: calls.append(True), max_passes=8
        )
        self.assertEqual((passes, stable), (4, 2))
        self.assertEqual(sections, observations[-1])
        self.assertTrue(snapshot.build_completeness(passes, stable, 8, sections)["loadComplete"])

    def test_changing_cards_at_cap_must_not_claim_complete(self):
        n = [0]
        def scroll():
            n[0] += 1
        def read():
            return [{"name": "passes", "count": n[0]}]
        passes, stable, sections = snapshot.scroll_until_stable(read, scroll, max_passes=5)
        evidence = snapshot.build_completeness(passes, stable, 5, sections)
        self.assertEqual((passes, stable), (5, 0))
        self.assertFalse(evidence["loadComplete"])
        self.assertEqual(evidence["cards"], 5)
        self.assertEqual(evidence["maxPasses"], 5)

    def test_empty_and_single_pass_are_not_complete(self):
        for max_passes in (0, 1):
            passes, stable, sections = snapshot.scroll_until_stable(
                lambda: [], lambda: None, max_passes=max_passes
            )
            self.assertFalse(snapshot.build_completeness(
                passes, stable, max_passes, sections
            )["loadComplete"])
            self.assertEqual(sections, [])

    def test_evidence_preserves_section_counts_and_producer_identity(self):
        sections = [{"name": "boxes", "count": 4}, {"name": "tickets", "count": 2}]
        evidence = snapshot.build_completeness(4, 2, 20, sections)
        self.assertEqual(evidence, {
            "schema": 1, "producer": "store_snapshot.py", "loadComplete": True,
            "passes": 4, "stablePasses": 2, "maxPasses": 20,
            "cards": 6, "sections": sections,
        })

    def test_stability_requires_consecutive_unchanged_observations(self):
        counts = [2, 2, 3, 3, 3]
        index = [0]
        def scroll():
            index[0] += 1
        def read():
            return [{"name": "boxes", "count": counts[index[0] - 1]}]
        passes, stable, _ = snapshot.scroll_until_stable(read, scroll, max_passes=8)
        self.assertEqual((passes, stable), (5, 2))


if __name__ == "__main__":
    unittest.main()
