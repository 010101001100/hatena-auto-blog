import re
import sys
import quality_v2 as q

_base_gemini = q.gemini
_base_write_article = q.write_article
_base_critique = q.critique
FALLBACK_MODEL = "gemini-3.5-flash-lite"


def robust_gemini(api_key, model, prompt, search=False, json_mode=False, max_tokens=7000):
    errors = []
    try:
        return _base_gemini(api_key, model, prompt, search=search, json_mode=json_mode, max_tokens=max_tokens)
    except RuntimeError as e:
        errors.append(f"{model} search={search}: {e}")

    if search:
        no_search_prompt = (
            "重要: この実行ではGoogle検索ツールを利用できません。検索したと主張しないでください。"
            "料金、価格、バージョン番号、割合、倍率、最新仕様など変わりやすい具体値は扱わず、"
            "長く有効な操作原則・整理方法・確認手順を中心にしてください。"
            "『公式情報で確認した』などの表現も禁止です。\n\n" + prompt
        )
        try:
            print(f"WARNING: {model} の検索グラウンディングが使えないため検索なしで再試行します")
            return _base_gemini(api_key, model, no_search_prompt, search=False, json_mode=json_mode, max_tokens=max_tokens)
        except RuntimeError as e:
            errors.append(f"{model} search=False: {e}")

    if model != FALLBACK_MODEL:
        fallback_prompt = (
            "品質優先。一般論の水増しを避け、再現可能な手順と判断基準を書いてください。"
            "不明な仕様、料金、数値、バージョン情報は絶対に作らないでください。\n\n" + prompt
        )
        try:
            print(f"WARNING: {model} が利用できないため {FALLBACK_MODEL} にフォールバックします")
            return _base_gemini(api_key, FALLBACK_MODEL, fallback_prompt, search=False, json_mode=json_mode, max_tokens=max_tokens)
        except RuntimeError as e:
            errors.append(f"{FALLBACK_MODEL}: {e}")

    raise RuntimeError(" / ".join(errors[-3:]))


def strict_write_article(api_key, model, theme, memo, sources, titles, revision=""):
    if not sources:
        extra = """
この実行では検索ソースを取得できていません。次を厳守してください。
- 「無料」「有料」「○円」「○%」「○倍」など変わりうる具体値を書かない
- OSやアプリの特定バージョン番号を根拠なしに書かない
- 「公式」「標準採用」など、確認済みを装う断定を避ける
- 「必ず」「完全に」「確実に」「極めて高い」のような絶対表現を使わない
- 「全員がログアウトする」「すべて消える」など結果を一律に断定しない
- 調査メモ内の verified_facts も未検証の参考候補として扱う
- 製品固有の細かい仕様より、ユーザー自身が画面で確認できる手順・判断基準を優先する
- UI名称や挙動は「環境や更新状況により異なる場合があります」と必要に応じて限定する
- 原因の切り分けは「可能性が高まる」「候補になる」のように慎重に書く
""".strip()
        revision = (revision + "\n\n" + extra).strip()
    return _base_write_article(api_key, model, theme, memo, sources, titles, revision)


def strict_critique(api_key, model, article, memo, sources, titles):
    passed, report, checks = _base_critique(api_key, model, article, memo, sources, titles)

    if not sources:
        text = article["title"] + "\n" + article["body"]
        risky_patterns = [
            (r"(?:無料|有料|料金|価格)", "検索未確認なのに料金・無料/有料を断定"),
            (r"\d[\d,]*\s*円", "検索未確認なのに具体的な金額を記載"),
            (r"\d+(?:\.\d+)?\s*%", "検索未確認なのに割合を記載"),
            (r"\d+(?:\.\d+)?\s*倍", "検索未確認なのに倍率を記載"),
            (r"(?:iOS|Android)\s*\d+(?:\.\d+)?", "検索未確認なのにOSバージョンを断定"),
            (r"Windows\s*(?:10|11)", "検索未確認なのにWindowsバージョンを限定"),
            (r"(?:必ず|完全に|確実に|極めて高い)", "検索未確認なのに強い断定表現を使用"),
            (r"すべてのサイトからログアウト", "サイトデータ削除の影響を一律に断定"),
            (r"二段階認証の再設定", "ログアウトと二段階認証の再設定を混同している可能性"),
        ]
        for pattern, message in risky_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                checks.append(message)

        for phrase in ("公式の無料", "標準採用", "ファイルサイズが約"):
            if phrase in text:
                checks.append(f"検索未確認の断定表現: {phrase}")

        if checks:
            passed = False

    return passed, report, checks


q.gemini = robust_gemini
q.write_article = strict_write_article
q.critique = strict_critique

if __name__ == "__main__":
    try:
        raise SystemExit(q.main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
