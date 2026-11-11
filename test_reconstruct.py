import io
import unittest

from github_reviews_to_csv import write_observations
from reconstruct import read_cases, reconstruct


def analyze(rows, **options):
    header = "case,stage,timestamp,sequence\n"
    cases = read_cases(io.StringIO(header + rows), "case", "stage", "timestamp",
                       order_column=options.pop("order_column", None))
    return reconstruct(cases, **options)


class ReconstructionTests(unittest.TestCase):
    def test_unsorted_export_collapses_snapshots_and_detects_return(self):
        result = analyze(
            "A,Review,2026-01-01T03:00:00Z,4\n"
            "A,Review,2026-01-01T00:00:00Z,1\n"
            "A,Review,2026-01-01T01:00:00Z,2\n"
            "A,Changes,2026-01-01T02:00:00Z,3\n"
            "B,Review,2026-01-01T01:00:00Z,1\n",
            inspect_case="A",
        )
        self.assertEqual(result["stage_returns"], {"Review": 1})
        self.assertEqual(result["cases_with_stage_returns"], 1)
        self.assertEqual([item["record"] for item in result["case"]["stage_changes"]], [3, 5, 2])
        transitions = {(item["from"], item["to"]): item for item in result["transitions"]}
        self.assertEqual(transitions["Review", "Changes"]["median_elapsed_seconds"], 7200)
        self.assertEqual(transitions["Changes", "Review"]["count"], 1)

    def test_equal_instants_need_explicit_order_for_conflicting_stages(self):
        rows = (
            "A,Review,2026-01-01T01:00:00+01:00,2\n"
            "A,Opened,2026-01-01T00:00:00Z,1\n"
        )
        ambiguous = analyze(rows, inspect_case="A")
        self.assertEqual(ambiguous["ambiguous_cases"], 1)
        self.assertEqual(ambiguous["transitions"], [])
        ordered = analyze(rows, order_column="sequence")
        self.assertEqual(ordered["ambiguous_cases"], 0)
        self.assertEqual(ordered["transitions"], [
            {"from": "Opened", "to": "Review", "count": 1, "median_elapsed_seconds": 0},
        ])

    def test_unknown_stage_does_not_bridge_a_gap(self):
        result = analyze(
            "A,Opened,2026-01-01T00:00:00Z,1\n"
            "A,?,2026-01-01T01:00:00Z,2\n"
            "A,Closed,2026-01-01T02:00:00Z,3\n",
            unknown_stages=["?"],
        )
        self.assertEqual(result["unknown_stage_cases"], 1)
        self.assertEqual(result["analyzed_cases"], 0)
        self.assertEqual(result["transitions"], [])

    def test_invalid_timestamp_fails_with_source_line(self):
        with self.assertRaisesRegex(ValueError, "CSV line 2: invalid timestamp"):
            analyze("A,Opened,2026-01-01T00:00:00,1\n")

    def test_utc_overflow_fails_with_source_line(self):
        for timestamp in ("0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-01:00"):
            with self.subTest(timestamp=timestamp):
                with self.assertRaisesRegex(ValueError, "CSV line 2: invalid timestamp"):
                    analyze(f"A,Opened,{timestamp},1\n")

    def test_evidence_tracks_record_and_starting_line_independently(self):
        stream = io.StringIO(
            'case,stage,timestamp,notes\r\n'
            'A,Opened,2026-01-01T00:00:00Z,"two\r\nlines"\r\n'
            '\r\n'
            'A,Closed,2026-01-01T01:00:00Z,done\r\n',
            newline="",
        )
        cases = read_cases(stream, "case", "stage", "timestamp")
        [transition] = reconstruct(cases, include_examples=True)["transitions"]
        self.assertEqual(
            [(item["record"], item["line"]) for item in transition["example"]["records"]],
            [(2, 2), (3, 5)],
        )

    def test_evidence_uses_longest_interval_and_retains_csv_record_numbers(self):
        result = analyze(
            "A,Queued,2026-01-01T00:00:00Z,1\n"
            "B,Running,2026-01-01T00:20:00Z,2\n"
            "A,Running,2026-01-01T00:10:00Z,2\n"
            "B,Queued,2026-01-01T00:00:00Z,1\n",
            include_examples=True,
        )
        [transition] = result["transitions"]
        self.assertEqual(transition["median_elapsed_seconds"], 900)
        self.assertEqual(transition["example"]["case"], "B")
        self.assertEqual(transition["example"]["elapsed_seconds"], 1200)
        self.assertEqual([item["record"] for item in transition["example"]["records"]], [5, 3])

    def test_github_projection_preserves_decisions_and_excludes_late_reviews(self):
        pull = {
            "number": 2, "url": "https://example.org/pull/2", "draft": False,
            "created_at": "2026-01-01T00:00:00Z", "closed_at": "2026-01-01T04:00:00Z",
            "merged_at": "2026-01-01T04:00:00Z",
            "reviews": [
                {"id": 5, "state": "APPROVED", "submitted_at": "2026-01-01T05:00:00Z"},
                {"id": 4, "state": "COMMENTED", "submitted_at": "2026-01-01T03:00:00Z"},
                {"id": 3, "state": "CHANGES_REQUESTED", "submitted_at": "2026-01-01T02:00:00Z"},
                {"id": 2, "state": "COMMENTED", "submitted_at": "2026-01-01T01:00:00Z"},
            ],
        }
        stream = io.StringIO()
        write_observations([pull], stream)
        self.assertIn("#pullrequestreview-3", stream.getvalue())
        stream.seek(0)
        result = reconstruct(read_cases(stream, "case", "stage", "timestamp"), "2")
        self.assertEqual([item["stage"] for item in result["case"]["stage_changes"]], [
            "Opened", "Review: COMMENTED", "Review: CHANGES_REQUESTED", "Merged",
        ])


if __name__ == "__main__":
    unittest.main()
