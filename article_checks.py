"""LLM採点だけに依存しない、検索意図に直結する公開前の具体的チェック。"""

import re


def practical_static_checks(article, memo):
    """明白な手順欠落を機械的に検出。未知の主張はAI監査にも回す。"""
    title = article.get("title", "")
    body = article.get("body", "")
    topic = (memo.get("topic") or "") + " " + title
    issues = []

    # GitHub.com向けSSHキーの登録/セットアップは、接続試験があって初めて完走できる。
    ssh_setup = (
        re.search(r"github", topic, re.IGNORECASE)
        and re.search(r"ssh", topic, re.IGNORECASE)
        and re.search(r"鍵|キー|key", topic, re.IGNORECASE)
        and re.search(r"追加|登録|生成|設定|接続|セットアップ", topic)
    )
    if ssh_setup:
        if not re.search(r"ssh\s+-T\s+git@github\.com\b", body, re.IGNORECASE):
            issues.append(
                "GitHub SSHキーの記事に接続確認 `ssh -T git@github.com` がない。"
                "登録後の疎通テストと判定手順を追加する"
            )
        if not re.search(r"successfully authenticated|Hi\s+USERNAME|"
                         r"Hi\s+ユーザー|Hi\s+[^\s!]+!|you.ve\s+successfully\s+authenticated", body, re.IGNORECASE):
            issues.append(
                "GitHub SSH接続テストの期待結果がない。"
                "GitHubの挨拶メッセージを例示して成功判定を説明する"
            )

    # 入力例としてhello.pyを実行させるなら、初学者が作れるようにする。
    if re.search(r"\b(?:py|python|python3)\s+hello\.py\b", body, re.IGNORECASE):
        can_create = (
            bool(re.search(r"notepad\s+hello\.py\b", body, re.IGNORECASE))
            or ("hello.py" in body and "保存" in body and
                ("作成" in body or "新規" in body))
        )
        if not can_create:
            issues.append(
                "hello.pyを実行する例に、ファイルの作成・保存手順がない"
            )

    # PowerShellを開いている利用者が、別のpowershell.exeを起動してしまう
    # コマンド表記を検出する。cmdから呼ぶ例ならその旨の説明を必須とする。
    policy_topic = re.search(
        r"Get-ExecutionPolicy|実行ポリシー", topic, flags=re.IGNORECASE
    )
    nested_policy = re.search(
        r"\bpowershell(?:\.exe)?\s+(?:-Command\s+)?[\"']?Get-ExecutionPolicy\b",
        body,
        flags=re.IGNORECASE,
    )
    if policy_topic and nested_policy and not re.search(
        r"コマンドプロンプト|cmd(?:\.exe)?から|別(?:の|プロセス|シェル|セッション)|"
        r"Windows\s+PowerShellを起動",
        body, flags=re.IGNORECASE,
    ):
        issues.append(
            "実行ポリシー確認で powershell Get-ExecutionPolicy をそのまま"
            "勧めている。PowerShell内なら Get-ExecutionPolicy を直接実行し、"
            "cmdから別のPowerShellを起動する例なら用途を明示する"
        )

    return issues
