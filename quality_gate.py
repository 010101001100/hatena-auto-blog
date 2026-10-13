"""公開前の100点採点と必須条件。APIを呼ばずにテストできる判定ロジック。"""

SCORE_WEIGHTS = {
    "evidence": 5,       # 事実の正確性: 25
    "intent_match": 4,   # 検索意図: 20
    "usefulness": 4,     # 実用性: 20
    "structure": 3,      # 構成: 15
    "title_seo": 2,      # タイトル/SEO: 10
    "originality": 2,    # 独自の付加価値: 10
}
MINIMUM_SCORE = 90
REQUIRED_RATINGS = (*SCORE_WEIGHTS, "specificity")
REQUIRED_FLAGS = ("factual_risk", "topic_drift", "generic_ai_style")


def score_report(report):
    """欠損・不正な評価値を高得点として処理しない。"""
    total = 0
    for key, weight in SCORE_WEIGHTS.items():
        value = report.get(key)
        if type(value) is not int or not 0 <= value <= 5:
            raise ValueError(f"不正な採点値: {key}={value!r}")
        total += value * weight
    return total


def completion_result(report):
    """実行手順の完走性を独立監査。形式不正もREVISE扱い。"""
    if not isinstance(report, dict) or type(report.get("pass")) is not bool:
        return False, ["操作の完走性監査の応答形式が不正"]
    gaps = report.get("blocking_gaps")
    if not isinstance(gaps, list) or not all(isinstance(x, str) for x in gaps):
        return False, ["操作の完走性監査にblocking_gapsがない"]
    if report["pass"] and not gaps:
        return True, []
    return False, [f"操作の完走を妨げる欠落: {x}" for x in gaps[:8]] or [
        "操作の完走性監査に不合格"
    ]


def evaluate_quality(report, checks, grounded_ok, practical_ok):
    """100点評価に加え、独立監査と最低点を満たした時だけPASS。"""
    errors = list(checks)
    try:
        score = score_report(report)
    except (ValueError, AttributeError) as exc:
        return False, 0, errors + [str(exc)]

    if report.get("decision") != "PASS":
        errors.append("編集AIがREVISE判定")
    if score < MINIMUM_SCORE:
        errors.append(f"総合スコア不足: {score}/{MINIMUM_SCORE}点")
    for key in REQUIRED_RATINGS:
        value = report.get(key)
        if type(value) is not int or value < 4 or value > 5:
            errors.append(f"必須項目が4/5未満・不正: {key}={value!r}")
    for key in REQUIRED_FLAGS:
        if type(report.get(key)) is not bool or report[key]:
            errors.append(f"重大リスクの指摘・形式不正: {key}")
    if not grounded_ok:
        errors.append("公式資料との整合性監査が未合格")
    if not practical_ok:
        errors.append("初心者の操作完走性監査が未合格")
    return not errors, score, list(dict.fromkeys(errors))
