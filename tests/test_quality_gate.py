import unittest

from quality_gate import completion_result, evaluate_quality, score_report


def full_report(**changes):
    report = {
        "decision": "PASS",
        "evidence": 5,
        "intent_match": 5,
        "usefulness": 5,
        "structure": 5,
        "title_seo": 5,
        "originality": 5,
        "specificity": 5,
        "factual_risk": False,
        "topic_drift": False,
        "generic_ai_style": False,
    }
    report.update(changes)
    return report


class QualityGateTests(unittest.TestCase):
    def test_perfect_report_is_100_points(self):
        self.assertEqual(score_report(full_report()), 100)

    def test_all_fours_fail_90_point_floor(self):
        report = full_report(**{k: 4 for k in (
            "evidence", "intent_match", "usefulness",
            "structure", "title_seo", "originality", "specificity"
        )})
        passed, score, reasons = evaluate_quality(report, [], True, True)
        self.assertEqual(score, 80)
        self.assertFalse(passed)
        self.assertTrue(any("総合スコア不足" in reason for reason in reasons))

    def test_fact_risk_is_not_ignored_even_when_grounded(self):
        passed, _, reasons = evaluate_quality(
            full_report(factual_risk=True), [], True, True
        )
        self.assertFalse(passed)
        self.assertTrue(any("factual_risk" in reason for reason in reasons))

    def test_missing_practical_audit_blocks_publication(self):
        passed, _, reasons = evaluate_quality(full_report(), [], True, False)
        self.assertFalse(passed)
        self.assertTrue(any("操作完走性" in reason for reason in reasons))

    def test_missing_grounding_blocks_publication(self):
        passed, _, _ = evaluate_quality(full_report(), [], False, True)
        self.assertFalse(passed)

    def test_editor_revize_blocks_publication(self):
        passed, _, _ = evaluate_quality(
            full_report(decision="REVISE"), [], True, True
        )
        self.assertFalse(passed)

    def test_missing_or_bad_scores_fail_closed(self):
        for value in (None, True, 5.0, 6, -1, "5"):
            report = full_report(evidence=value)
            passed, _, _ = evaluate_quality(report, [], True, True)
            self.assertFalse(passed)

    def test_specificity_must_reach_four(self):
        passed, _, _ = evaluate_quality(
            full_report(specificity=3), [], True, True
        )
        self.assertFalse(passed)

    def test_completion_audit_catches_missing_file_creation(self):
        result, reasons = completion_result({
            "pass": False,
            "blocking_gaps": ["hello.pyを作成する手順がない"],
        })
        self.assertFalse(result)
        self.assertIn("hello.py", reasons[0])

    def test_completion_audit_fail_closed(self):
        for item in (None, {}, {"pass": True}, {
            "pass": True, "blocking_gaps": ["実行結果が不明"],
        }):
            self.assertFalse(completion_result(item)[0])

    def test_complete_article_passes(self):
        self.assertTrue(completion_result({
            "pass": True, "blocking_gaps": []
        })[0])
        self.assertTrue(evaluate_quality(full_report(), [], True, True)[0])


if __name__ == "__main__":
    unittest.main()
