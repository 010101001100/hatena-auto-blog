import json
import unittest
from unittest.mock import patch

from execution_plan import execution_plan_issues, format_execution_plan
import quality_runner


def valid_memo():
    return {
        "topic": "Docker Desktopの利用前にWindowsで要件を確認する",
        "working_title": "WindowsでDocker Desktopの要件を確認する手順",
        "reader": "Windowsの利用者",
        "search_intent": "インストール前の要件を確認する",
        "execution_plan": {
            "scope": "Windows上でDocker Desktopの要件を確認する（導入自体は対象外）",
            "prerequisites": [
                "Windowsのバージョンをwinverで確認する",
                "wsl --versionを使える場合はWSLバージョンを確認する",
            ],
            "steps": [
                "Windowsのバージョンを確認する",
                "WSLの状態を確認する",
                "公式要件と照らしてインストール可否を判断する",
            ],
            "success_check": "必要条件を満たすか項目別に判断できる",
            "failure_paths": [
                "WSLがない場合はMicrosoft公式のインストール手順を参照する",
                "BIOS変更はメーカー固有のため機種別公式資料を確認する",
            ],
        },
    }


class ExecutionPlanTests(unittest.TestCase):
    def test_valid_plan(self):
        self.assertEqual(execution_plan_issues(valid_memo()), [])

    def test_plan_is_included_in_first_draft_prompt(self):
        memo = valid_memo()
        prompt = format_execution_plan(memo)
        self.assertIn("wsl --version", prompt)
        self.assertIn("成功結果", prompt)
        self.assertIn("BIOS変更", prompt)
        self.assertIn("導入自体は対象外", prompt)

    def test_missing_success_check_is_blocked(self):
        memo = valid_memo()
        memo["execution_plan"]["success_check"] = ""
        self.assertTrue(execution_plan_issues(memo))
        with self.assertRaises(ValueError):
            format_execution_plan(memo)

    def test_one_step_is_blocked(self):
        memo = valid_memo()
        memo["execution_plan"]["steps"] = ["チェックする"]
        self.assertTrue(execution_plan_issues(memo))

    def test_missing_plan_is_blocked(self):
        self.assertTrue(execution_plan_issues({"topic": "Docker"}))

    def test_invalid_checklist_types_are_blocked(self):
        memo = valid_memo()
        memo["execution_plan"]["prerequisites"] = "下調べ"
        self.assertTrue(execution_plan_issues(memo))

    def test_research_uses_same_planning_call_for_executable_plan(self):
        memo = valid_memo()
        official = [
            {"title": "公式1", "url": "https://example.org/a", "domain": "example.org"},
            {"title": "公式2", "url": "https://example.org/b", "domain": "example.org"},
        ]
        seed = {"label": "Docker Desktopの要件を確認", "query": "docker requirements", "domains": ["example.org"]}
        with (
            patch.object(quality_runner, "_diversified_seeds", return_value=[seed]),
            patch.object(quality_runner.q, "nearest", return_value=(0.1, "")),
            patch.object(quality_runner, "search_official_query", return_value=official),
            patch.object(quality_runner, "source_summary_for_prompt", return_value="公式資料本文") as summary,
            patch.object(
                quality_runner, "robust_gemini",
                return_value=(json.dumps(memo, ensure_ascii=False), [], [])
            ) as gemini,
        ):
            data, sources, _ = quality_runner.retry_research("key", "model", "theme", [])
        self.assertEqual(data["execution_plan"]["steps"], memo["execution_plan"]["steps"])
        self.assertEqual(len(sources), 2)
        self.assertEqual(gemini.call_count, 1)
        summary.assert_called_once()

    def test_first_draft_uses_plan_without_new_planning_api_call(self):
        memo = valid_memo()
        article = {"title": "Docker Desktopの利用要件を確認", "category": "VS Code・Docker",
                   "body": "## 事前確認\n確認する\n\n## 操作\n操作する\n\n## 判定\n判定する"}
        sources = [
            {"title": "公式1", "url": "https://example.org/a"},
            {"title": "公式2", "url": "https://example.org/b"},
        ]
        with patch.object(quality_runner, "_base_write_article", return_value=article.copy()) as writer:
            result = quality_runner.strict_write_article(
                "key", "model", "theme", memo, sources, [], ""
            )
        self.assertEqual(writer.call_count, 1)
        passed_prompt = writer.call_args.args[-1]
        self.assertIn(memo["execution_plan"]["scope"], passed_prompt)
        self.assertIn(memo["execution_plan"]["success_check"], passed_prompt)
        self.assertIn("BIOS変更", passed_prompt)
        self.assertIn("## 参考情報", result["body"])


if __name__ == "__main__":
    unittest.main()
