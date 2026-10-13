import unittest
from unittest.mock import patch

import quality_runner


def passing_report(**changes):
    report = {
        "decision": "PASS", "evidence": 5, "intent_match": 5,
        "usefulness": 5, "structure": 5, "title_seo": 5,
        "originality": 5, "specificity": 5,
        "factual_risk": False, "topic_drift": False,
        "generic_ai_style": False, "problems": [],
    }
    report.update(changes)
    return report


ARTICLE = {
    "title": "Windowsのcmdでpyコマンドを使ってPythonを実行する手順",
    "body": "## 手順\n\n...\n\n\n## 確認\n\n...\n\n\n## 参考情報\n\n"
            "- [公式A](https://docs.example.org/a)\n"
            "- [公式B](https://docs.example.org/b)\n",
}
MEMO = {"official_evidence": "操作についての公式資料", "search_intent": "Python実行"}
SOURCES = [
    {"title": "公式A", "url": "https://docs.example.org/a"},
    {"title": "公式B", "url": "https://docs.example.org/b"},
]


class IntegrationGateTests(unittest.TestCase):
    def check_article(self, report, factual=True, practical=True):
        with (
            patch.object(quality_runner, "_base_critique", return_value=(True, report, [])),
            patch.object(quality_runner, "strict_local_checks", return_value=[]),
            patch.object(quality_runner, "grounding_audit", return_value=(factual, [])),
            patch.object(quality_runner, "practical_audit", return_value=(practical, [])),
        ):
            return quality_runner.strict_critique(
                "not-a-real-key", "fake-model", ARTICLE, MEMO, SOURCES, []
            )

    def test_full_pass_after_both_audits(self):
        passed, report, checks = self.check_article(passing_report())
        self.assertTrue(passed, checks)
        self.assertEqual(report["score_100"], 100)

    def test_gap_blocks_even_with_perfect_editorial_score(self):
        passed, report, checks = self.check_article(passing_report(), practical=False)
        self.assertFalse(passed)
        self.assertEqual(report["score_100"], 100)
        self.assertTrue(any("完走性" in item for item in checks))

    def test_grounding_failure_blocks_even_with_perfect_editorial_score(self):
        passed, _, _ = self.check_article(passing_report(), factual=False)
        self.assertFalse(passed)

    def test_editorial_risk_flag_blocks_despite_grounding_pass(self):
        passed, _, _ = self.check_article(
            passing_report(factual_risk=True), factual=True, practical=True
        )
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
