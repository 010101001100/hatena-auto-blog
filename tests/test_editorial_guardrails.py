import unittest
from unittest.mock import patch

from editorial_guardrails import editorial_checks
import quality_runner


def doc_article(title, body):
    return {"title": title, "body": body}


def ffmpeg_article(extra="", title="ffmpegで動画形式を変換する手順"):
    body = (
        "入力はclip.avi。用途は画質を確かめてMP4に変換すること。\n"
        "`ffmpeg -n -i clip.avi -c:v libx264 result.mp4` で別名保存。\n"
        "既存ファイルは上書きせず、変換後はresult.mp4を再生して確認する。\n"
        + extra
    )
    return doc_article(title, body)


class EditorialSafetyTests(unittest.TestCase):
    def test_ffmpeg_missing_overwrite_explanation_and_verification(self):
        article = doc_article(
            "ffmpegで動画形式を変換する基本手順",
            "ffmpeg -i clip.avi movie.mp4\n変換できたはず。",
        )
        issues = editorial_checks(article, {})
        self.assertTrue(any("上書きリスク" in x for x in issues))
        self.assertTrue(any("上書き" in x and "-n" in x for x in issues))
        self.assertTrue(any("確認する手順" in x for x in issues))

    def test_ffmpeg_safe_original_example_passes(self):
        self.assertEqual(editorial_checks(ffmpeg_article(), {}), [])

    def test_low_bitrate_needs_visual_quality_warning(self):
        article = ffmpeg_article("ffmpeg -i clip.avi -b:v 64k small.mp4")
        issues = editorial_checks(article, {})
        self.assertTrue(any("ビットレート64k" in x for x in issues))

    def test_low_bitrate_with_warning_passes(self):
        article = ffmpeg_article(
            "ffmpeg -i clip.avi -b:v 64k small.mp4\n"
            "64kは画質が低下する場合がある構文例で、通常は用途に合わせて選ぶ。"
        )
        self.assertEqual(editorial_checks(article, {}), [])

    def test_raw_manual_examples_alone_are_rejected(self):
        article = doc_article(
            "ffmpegで動画形式を変換する",
            (
                "ffmpeg -i input.avi output.mp4\n"
                "ffmpeg -i input.avi -b:v 64k -bufsize 64k output.mp4\n"
                "出力ファイルが既にあれば上書きに注意。-nで防止する。\n"
                "64kは画質が低くなる構文例。\n"
                "変換後の出力ファイルを再生して確認。"
            ),
        )
        issues = editorial_checks(article, {})
        self.assertTrue(any("公式マニュアル" in x for x in issues))

    def test_original_example_alongside_manual_excerpts_passes(self):
        article = ffmpeg_article("ffmpeg -i input.avi output.mp4\n")
        self.assertEqual(editorial_checks(article, {}), [])

    def test_docker_windows10_requires_support_end_notice(self):
        article = doc_article(
            "Docker Desktop Windowsのインストールモード比較",
            "Windows 10 22H2でもDockerを動かせる条件を説明する。",
        )
        self.assertTrue(
            any("サポート終了日" in x for x in editorial_checks(article, {}))
        )

    def test_docker_support_notice_passes(self):
        article = doc_article(
            "Docker Desktop Windowsのインストールモード比較",
            "Windows 10は2025年10月14日に通常サポート終了。"
            "ESUやLTSCなど例外あり。Windows 11で選択を比較する。",
        )
        self.assertEqual(editorial_checks(article, {}), [])

    def test_docker_requirement_needs_check_paths(self):
        article = doc_article(
            "WindowsでDocker Desktopの動作要件を確認する",
            "Windows 11で必要なメモリ容量は8GB。BIOS/UEFIの仮想化も有効にする。",
        )
        issues = editorial_checks(article, {})
        self.assertTrue(any("搭載メモリ" in x for x in issues))
        self.assertTrue(any("仮想化要件" in x for x in issues))

    def test_docker_requirement_with_check_paths_passes(self):
        article = doc_article(
            "WindowsでDocker Desktopの動作要件を確認する",
            (
                "Windows 11でメモリ8GBを確認。\n"
                "タスクマネージャーでパフォーマンスのCPU欄から仮想化を確認し、"
                "メモリ画面から搭載メモリを確認する。\n"
                "WSLは wsl --version を実行。"
            ),
        )
        self.assertEqual(editorial_checks(article, {}), [])

    def test_unrelated_articles_not_blocked(self):
        article = doc_article(
            "PowerShellのスクリプト実行ポリシーを確認する",
            "Windows 10の環境でPowerShellの設定値を確かめる。",
        )
        self.assertEqual(editorial_checks(article, {}), [])


class GroundingSupplementTests(unittest.TestCase):
    seed = {
        "label": "Docker DesktopをWindowsにインストールする",
        "domains": ["docs.docker.com"],
    }
    sources = [
        {"url": "https://docs.docker.com/desktop/setup/install/windows-install/"},
        {"url": "https://docs.docker.com/desktop/setup/install/"},
    ]

    def test_microsoft_source_added_to_windows_docker_research(self):
        page = "Microsoft サポート: Windows 10 は 2025年10月14日にサポート終了しました。" * 15
        with patch.object(quality_runner, "fetch_page_text", return_value=page) as fetch:
            result = quality_runner._append_lifecycle_evidence(self.seed, self.sources)
        self.assertEqual(len(result), 3)
        self.assertIn("support.microsoft.com", result[-1]["url"])
        self.assertIn("2025年10月14日", result[-1]["evidence"])
        fetch.assert_called_once()

    def test_fetch_failure_does_not_invent_sourcing(self):
        with patch.object(quality_runner, "fetch_page_text", return_value=""):
            result = quality_runner._append_lifecycle_evidence(self.seed, self.sources)
        self.assertEqual(result, self.sources)

    def test_other_docker_topic_does_not_fetch_windows_lifecycle(self):
        seed = {"label": "docker logsで確認する", "domains": ["docs.docker.com"]}
        with patch.object(quality_runner, "fetch_page_text") as fetch:
            result = quality_runner._append_lifecycle_evidence(seed, self.sources)
        self.assertEqual(result, self.sources)
        fetch.assert_not_called()

    def test_preflight_blocks_misleading_perfect_scored_ffmpeg_article(self):
        article = doc_article(
            "ffmpegで動画を変換する",
            "ffmpeg -i input.avi -b:v 64k output.mp4\n",
        )
        with (
            patch.object(quality_runner, "strict_local_checks", return_value=[]),
            patch.object(quality_runner, "practical_static_checks", return_value=[]),
            patch.object(quality_runner, "_base_critique") as critic,
        ):
            checks = quality_runner.preflight_checks(
                article,
                {"official_evidence": "公式"},
                [
                    {"url": "https://docs.example.org/1"},
                    {"url": "https://docs.example.org/2"},
                ],
                [],
            )
        self.assertTrue(any("画質" in x or "上書き" in x for x in checks))
        critic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
