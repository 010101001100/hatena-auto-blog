import os
import unittest
from unittest.mock import patch

import quality_runner as runner


class GeminiQuotaTests(unittest.TestCase):
    def setUp(self):
        self.original_exhausted = set(runner._EXHAUSTED_MODELS)
        self.original_count = runner._CALL_COUNT
        runner._EXHAUSTED_MODELS.clear()
        runner._CALL_COUNT = 0

    def tearDown(self):
        runner._EXHAUSTED_MODELS.clear()
        runner._EXHAUSTED_MODELS.update(self.original_exhausted)
        runner._CALL_COUNT = self.original_count

    def test_daily_quota_429_is_not_retried(self):
        exc = RuntimeError(
            "Gemini API失敗: HTTP 429: You exceeded your current quota. "
            "Quota exceeded for metric: generate_content_free_tier_requests"
        )
        with (
            patch.object(runner, "_call_base", side_effect=exc) as call,
            patch.object(runner.time, "sleep") as sleep,
        ):
            with self.assertRaises(runner.ModelDailyQuotaExceeded):
                runner._call_with_retry("key", "gemini-3.8-flash", "prompt")
        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    def test_http_503_is_retried_once_only(self):
        good = ("ok", [], [])
        with (
            patch.object(
                runner, "_call_base",
                side_effect=[RuntimeError("Gemini API失敗: HTTP 503"), good]
            ) as call,
            patch.object(runner.time, "sleep") as sleep,
        ):
            result = runner._call_with_retry("key", "model", "prompt")
        self.assertEqual(result, good)
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(8)

    def test_model_quota_is_remembered_across_requests(self):
        def fake_call(key, model, prompt, **kwargs):
            if model == "gemini-3.8-flash":
                raise runner.ModelDailyQuotaExceeded("daily quota")
            return ("success", [], [])

        with patch.object(runner, "_call_with_retry", side_effect=fake_call) as call:
            for _ in range(2):
                self.assertEqual(
                    runner.robust_gemini("key", "gemini-3.8-flash", "prompt")[0],
                    "success",
                )
        models_called = [x.args[1] for x in call.call_args_list]
        self.assertEqual(models_called.count("gemini-3.8-flash"), 1)
        self.assertEqual(models_called.count("gemini-3.6-flash"), 2)

    def test_all_models_exhausted_fails_without_api_request(self):
        runner._EXHAUSTED_MODELS.update([
            "gemini-3.8-flash", *runner.FALLBACK_MODELS,
        ])
        with patch.object(runner, "_call_with_retry") as call:
            with self.assertRaises(runner.ModelDailyQuotaExceeded):
                runner.robust_gemini("key", "gemini-3.8-flash", "prompt")
        call.assert_not_called()

    def test_call_budget_is_hard_limit(self):
        with (
            patch.dict(os.environ, {"MAX_GEMINI_CALLS": "2"}),
            patch.object(runner, "_throttle"),
            patch.object(runner, "_base_gemini", return_value=("ok", [], [])) as base,
        ):
            runner._call_base("k", "model", "x")
            runner._call_base("k", "model", "x")
            with self.assertRaises(runner.ApiCallBudgetExceeded):
                runner._call_base("k", "model", "x")
        self.assertEqual(base.call_count, 2)


class PublishGateCostTests(unittest.TestCase):
    article = {"title": "普通の記事", "body": "本文"}
    memo = {"official_evidence": "公式資料"}
    sources = [
        {"url": "https://example.org/1"},
        {"url": "https://example.org/2"},
    ]

    def test_invalid_local_draft_skips_all_ai_audits(self):
        with (
            patch.object(runner, "strict_local_checks", return_value=["本文が短い"]),
            patch.object(runner, "practical_static_checks", return_value=[]),
            patch.object(runner, "_base_critique") as editorial,
            patch.object(runner, "practical_audit") as practical,
            patch.object(runner, "grounding_audit") as grounding,
        ):
            passed, report, problems = runner.strict_critique(
                "k", "model", self.article, self.memo, self.sources, []
            )
        self.assertFalse(passed)
        self.assertEqual(report["decision"], "REVISE")
        self.assertIn("本文が短い", problems)
        editorial.assert_not_called()
        practical.assert_not_called()
        grounding.assert_not_called()

    def test_failing_editorial_score_skips_other_ai_audits(self):
        report = {
            "decision": "REVISE", "intent_match": 3, "specificity": 3,
            "evidence": 3, "structure": 3, "usefulness": 3,
            "originality": 3, "title_seo": 3,
            "factual_risk": False, "topic_drift": False,
            "generic_ai_style": False,
        }
        with (
            patch.object(runner, "preflight_checks", return_value=[]),
            patch.object(runner, "_base_critique", return_value=(False, report, [])),
            patch.object(runner, "practical_audit") as practical,
            patch.object(runner, "grounding_audit") as grounding,
        ):
            passed, _, reasons = runner.strict_critique(
                "k", "model", self.article, self.memo, self.sources, []
            )
        self.assertFalse(passed)
        self.assertTrue(any("スコア不足" in x for x in reasons))
        practical.assert_not_called()
        grounding.assert_not_called()

    def test_practical_failure_skips_grounding_audit(self):
        report = {
            "decision": "PASS", "intent_match": 5, "specificity": 5,
            "evidence": 5, "structure": 5, "usefulness": 5,
            "originality": 5, "title_seo": 5,
            "factual_risk": False, "topic_drift": False,
            "generic_ai_style": False,
        }
        with (
            patch.object(runner, "preflight_checks", return_value=[]),
            patch.object(runner, "_base_critique", return_value=(True, report, [])),
            patch.object(runner, "practical_audit", return_value=(
                False, ["接続確認がない"]
            )),
            patch.object(runner, "grounding_audit") as grounding,
        ):
            passed, _, reasons = runner.strict_critique(
                "k", "model", self.article, self.memo, self.sources, []
            )
        self.assertFalse(passed)
        self.assertIn("接続確認がない", reasons)
        grounding.assert_not_called()


if __name__ == "__main__":
    unittest.main()
