import unittest

from article_checks import practical_static_checks


class PracticalStaticTests(unittest.TestCase):
    def test_missing_ssh_check_blocks(self):
        article = {"title": "MacでGitHubのSSHキーを生成・登録する",
                   "body": "ssh-keygen -t ed25519 で作成しGitHubの設定から登録する。"}
        issues = practical_static_checks(article, {})
        self.assertTrue(any("ssh -T" in x for x in issues))
        self.assertTrue(any("期待結果" in x for x in issues))

    def test_ssh_with_success_check_passes(self):
        article = {"title": "WindowsでGitHubにSSH公開鍵を登録",
                   "body": "`ssh -T git@github.com` で検証。"
                           " `Hi USERNAME! You've successfully authenticated` が出れば成功。"}
        self.assertEqual(practical_static_checks(article, {}), [])

    def test_ssh_check_without_expected_output_blocks(self):
        article = {"title": "MacでGitHub SSHキーを登録",
                   "body": "接続確認は `ssh -T git@github.com` を実行する。"}
        self.assertTrue(any("期待結果" in x for x in practical_static_checks(article, {})))

    def test_negative_authentication_text_is_not_success(self):
        article = {"title": "MacでGitHub SSHキーを登録",
                   "body": "`ssh -T git@github.com` を実行しても認証できません。"}
        issues = practical_static_checks(article, {})
        self.assertTrue(any("期待結果" in issue for issue in issues))

    def test_ordinary_git_article_has_no_specific_ssh_requirement(self):
        article = {"title": "GitHub ActionsのSecretsを設定する", "body": "画面で確認する"}
        self.assertEqual(practical_static_checks(article, {}), [])

    def test_python_hello_needs_file_creation(self):
        article = {"title": "Windowsのcmdでpyコマンドを使う", "body": "`py hello.py` と入力する"}
        self.assertTrue(any("hello.py" in x for x in practical_static_checks(article, {})))

    def test_python_hello_with_file_creation_passes(self):
        article = {"title": "cmdからPythonを動かす",
                   "body": "`notepad hello.py` でファイルを作り保存。`py hello.py` を実行する。"}
        self.assertEqual(practical_static_checks(article, {}), [])


if __name__ == "__main__":
    unittest.main()
