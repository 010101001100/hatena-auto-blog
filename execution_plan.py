"""公式調査の1回の応答で作る、再現可能な記事執筆計画。

実行前提、実行手順、成功判定を企画段階で固定する。
別途AIへ企画作成を依頼し直さず、既存の調査応答を利用する。
"""

PLAN_FIELDS = ("scope", "prerequisites", "steps", "success_check", "failure_paths")


def _short_text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= 600


def execution_plan_issues(memo):
    """計画が不完全なら記事生成のAPIを呼ぶ前にREVISE扱いする。"""
    if not isinstance(memo, dict):
        return ["記事企画が辞書形式ではない"]
    plan = memo.get("execution_plan")
    if not isinstance(plan, dict):
        return ["execution_planがない"]

    errors = []
    if not _short_text(plan.get("scope")):
        errors.append("記事で達成する範囲が明示されていない")

    prereqs = plan.get("prerequisites")
    if not isinstance(prereqs, list) or not 1 <= len(prereqs) <= 6 or not all(
        _short_text(x) for x in prereqs
    ):
        errors.append("必要な前提条件のリストが不完全")

    steps = plan.get("steps")
    if not isinstance(steps, list) or not 2 <= len(steps) <= 8 or not all(
        _short_text(x) for x in steps
    ):
        errors.append("操作ステップが2〜8件になっていない")

    if not _short_text(plan.get("success_check")):
        errors.append("読者が成功を判定する方法がない")

    failure_paths = plan.get("failure_paths")
    if not isinstance(failure_paths, list) or not 1 <= len(failure_paths) <= 5 or not all(
        _short_text(x) for x in failure_paths
    ):
        errors.append("前提条件を満たさない場合の切り分けがない")

    return errors


def format_execution_plan(memo):
    """調査段階の完走要件を初稿プロンプトへ確実に渡す。"""
    problems = execution_plan_issues(memo)
    if problems:
        raise ValueError("記事企画の実行計画が不完全: " + " / ".join(problems))
    plan = memo["execution_plan"]
    blocks = [
        "【この1記事で達成する範囲】",
        plan["scope"].strip(),
        "【記事の冒頭で必要な前提条件を確認】",
        *[f"- {item.strip()}" for item in plan["prerequisites"]],
        "【本文で必ず順番に実行可能にする操作】",
        *[f"{i}. {item.strip()}" for i, item in enumerate(plan["steps"], 1)],
        "【読者が自分で判定できる成功結果】",
        plan["success_check"].strip(),
        "【前提条件が満たせない・失敗した場合の分岐】",
        *[f"- {item.strip()}" for item in plan["failure_paths"]],
    ]
    return "\n".join(blocks)
