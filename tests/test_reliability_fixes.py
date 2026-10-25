import unittest
from unittest.mock import patch

import quality_runner as runner
from article_checks import practical_static_checks


class GeminiOutageProtectionTests(unittest.TestCase):
    def setUp(self):
        self.saved_exhausted = set(runner._EXHAUSTED_MODELS)
        runner._EXHAUSTED_MODELS.clear()

    def tearDown(self):
        runner._EXHAUSTED_MODELS.clear()
        runner._EXHAUSTED_MODELS.update(self.saved_exhausted)

    def test_two_models_reporting_503_stop_before_third(self):
        with patch.object(
            runner, "_call_with_retry", side_effect=RuntimeError("HTTP 503")
        ) as call:
            with self.assertRaises(runner.GeminiServiceUnavailable):
                runner.robust_gemini("key", "primary", "prompt")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(
            [c.args[1] for c in call.call_args_list],
            ["primary", runner.FALLBACK_MODELS[0]],
        )

    def test_two_models_timing_out_also_stop(self):
        with patch.object(
            runner, "_call_with_retry", side_effect=RuntimeError("Read timed out")
        ) as call:
            with self.assertRaises(runner.GeminiServiceUnavailable):
                runner.robust_gemini("key", "primary", "prompt")
        self.assertEqual(call.call_count, 2)

    def test_fallback_success_is_preserved(self):
        with patch.object(
            runner, "_call_with_retry",
            side_effect=[RuntimeError("HTTP 503"), ("ok", [], [])],
        ) as call:
            result = runner.robust_gemini("key", "primary", "prompt")
        self.assertEqual(result[0], "ok")
        self.assertEqual(call.call_count, 2)

    def test_429_quota_can_use_fallback(self):
        with patch.object(
            runner, "_call_with_retry",
            side_effect=[runner.ModelDailyQuotaExceeded("quota"), ("ok", [], [])],
        ):
            result = runner.robust_gemini("key", "primary", "prompt")
        self.assertEqual(result[0], "ok")
        self.assertIn("primary", runner._EXHAUSTED_MODELS)

    def test_other_error_does_not_trigger_outage(self):
        with patch.object(
            runner, "_call_with_retry",
            side_effect=[RuntimeError("HTTP 400"), RuntimeError("HTTP 400"),
                         ("ok", [], [])],
        ) as call:
            result = runner.robust_gemini("key", "primary", "prompt")
        self.assertEqual(result[0], "ok")
        self.assertEqual(call.call_count, 3)


class RotationTests(unittest.TestCase):
    seeds = [
        {"label": "yt-dlpを導入する", "query": "y1", "domains": ["github.com"]},
        {"label": "yt-dlpの設定を変える", "query": "y2", "domains": ["github.com"]},
        {"label": "Pythonの仮想環境を作る", "query": "p1", "domains": ["docs.python.org"]},
        {"label": "Pythonパッケージを管理", "query": "p2", "domains": ["docs.python.org"]},
        {"label": "PowerShellのポリシー", "query": "w1", "domains": ["learn.microsoft.com"]},
        {"label": "FFmpegの動画変換", "query": "f1", "domains": ["ffmpeg.org"]},
    ]

    def test_first_category_rotates_each_day_with_same_recent_articles(self):
        with patch.object(runner, "TOPIC_SEEDS", self.seeds):
            first = [runner._diversified_seeds([], rotation_day=100 + day)[0]["label"]
                     for day in range(4)]
        self.assertEqual(len(set(first)), 4)

    def test_topics_within_group_rotate_as_well(self):
        with patch.object(runner, "TOPIC_SEEDS", self.seeds):
            first = runner._diversified_seeds([], rotation_day=100)
            second = runner._diversified_seeds([], rotation_day=101)
        py1 = [x["label"] for x in first if "Python" in x["label"]]
        py2 = [x["label"] for x in second if "Python" in x["label"]]
        self.assertNotEqual(py1[0], py2[0])

    def test_recent_category_not_immediately_repeated(self):
        with patch.object(runner, "TOPIC_SEEDS", self.seeds):
            candidates = runner._diversified_seeds(
                ["Pythonで仮想環境を作成する"], rotation_day=100
            )
        self.assertNotIn("Python", candidates[0]["label"])


class PowerShellCommandTests(unittest.TestCase):
    def test_wrong_nested_powershell_command_blocked(self):
        article = {
            "title": "PowerShellの実行ポリシーを確認",
            "body": "PowerShellを開いて `powershell Get-ExecutionPolicy` を実行。",
        }
        issues = practical_static_checks(article, {})
        self.assertTrue(any("Get-ExecutionPolicy" in x for x in issues))

    def test_direct_command_allowed(self):
        article = {
            "title": "PowerShellの実行ポリシーを確認",
            "body": "PowerShellで `Get-ExecutionPolicy` を実行。",
        }
        self.assertEqual(practical_static_checks(article, {}), [])

    def test_cmd_invocation_with_explicit_context_allowed(self):
        article = {
            "title": "PowerShellの実行ポリシーを確認",
            "body": "コマンドプロンプトから `powershell -Command Get-ExecutionPolicy`",
        }
        self.assertEqual(practical_static_checks(article, {}), [])


if __name__ == "__main__":
    unittest.main()
