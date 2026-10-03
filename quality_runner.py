import re
import sys
import quality_v2 as q

_base_gemini = q.gemini
_base_write_article = q.write_article
_base_critique = q.critique
_base_local_checks = q.local_checks

FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash"]


def _models(primary):
    out = []
    for model in [primary, *FALLBACK_MODELS]:
        if model and model not in out:
            out.append(model)
    return out


def robust_gemini(api_key, model, prompt, search=False, json_mode=False, max_tokens=7000):
    """
    品質優先:
    - 調査は必ずGoogle検索付き。検索なしへのフォールバックは禁止。
    - 執筆/QAだけは別Flashモデルへフォールバック可。
    """
    errors = []

    if search:
        for candidate in _models(model):
            try:
                text, sources, queries = _base_gemini(
                    api_key,
                    candidate,
                    prompt,
                    search=True,
                    json_mode=json_mode,
                    max_tokens=max_tokens,
                )
                if len(sources) < 2:
                    errors.append(f"{candidate}: 参照ソースが{len(sources)}件しか取れませんでした")
                    continue
                print(f"検索調査モデル: {candidate} / ソース{len(sources)}件")
                return text, sources, queries
            except RuntimeError as e:
                errors.append(f"{candidate}: {e}")

        raise RuntimeError(
            "Google検索で十分な根拠を取得できないため、この回は記事を公開しません。 / "
            + " / ".join(errors[-3:])
        )

    for candidate in _models(model):
        try:
            if candidate != model:
                print(f"WARNING: {model} が使えないため {candidate} にフォールバックします")
            return _base_gemini(
                api_key,
                candidate,
                prompt,
                search=False,
                json_mode=json_mode,
                max_tokens=max_tokens,
            )
        except RuntimeError as e:
            errors.append(f"{candidate}: {e}")

    raise RuntimeError("Gemini API失敗: " + " / ".join(errors[-3:]))


def strict_write_article(api_key, model, theme, memo, sources, titles, revision=""):
    source_rule = ""
    if sources:
        source_rule = """
- 本文末尾に必ず「## 参考情報」を作る
- 参考情報には、提示された参照先から実際に使った2〜5件だけをMarkdownリンクで載せる
- 提示されていないURLを作らない
- 参照情報をそのまま写さず、自分の言葉で要約する
""".strip()

    quality_rule = f"""
追加の品質条件:
- 本文は2200〜3600字を目安にする。薄い一般論で水増ししない
- 冒頭2〜3文で読者の疑問への答えを先に示す
- 「なぜそうするか」だけでなく「どこをどう操作するか」「どう判断するか」を書く
- 具体的な手順・設定例・判断基準のうち最低2種類を入れる
- 製品固有のUI名・仕様・料金・バージョンは、調査メモで確認できるものだけを書く
- 読者が記事を閉じた直後に1つ以上の行動を取れる内容にする
- 「便利です」「おすすめです」「重要です」だけで段落を終わらせない
- 抽象論が2段落続いたら、具体例・手順・条件のどれかに置き換える
- 「まとめ」「はじめに」だけの抽象見出しは禁止
{source_rule}
""".strip()

    combined = quality_rule
    if revision:
        combined += "\n\n前稿への修正指示:\n" + revision

    return _base_write_article(
        api_key,
        model,
        theme,
        memo,
        sources,
        titles,
        combined,
    )


def strict_local_checks(article, memo, titles):
    issues = list(_base_local_checks(article, memo, titles))
    title, body = article["title"], article["body"]

    if len(body) < 1800:
        issues.append(f"本文がまだ薄い ({len(body)}文字)")
    if len(body) > 4600:
        issues.append(f"本文が冗長 ({len(body)}文字)")

    h2s = re.findall(r"(?m)^##\s+(.+)$", body)
    if not 3 <= len(h2s) <= 7:
        issues.append(f"H2数が不適切 ({len(h2s)}個)")
    if any(h.strip() in {"はじめに", "まとめ", "おわりに"} for h in h2s):
        issues.append("抽象的な見出し（はじめに/まとめ/おわりに）を使用")

    vague = [
        "重要です",
        "大切です",
        "おすすめです",
        "便利です",
        "活用しましょう",
    ]
    vague_hits = sum(body.count(x) for x in vague)
    if vague_hits >= 4:
        issues.append(f"抽象的な定型表現が多い ({vague_hits}箇所)")

    if "## 参考情報" not in body:
        issues.append("参考情報セクションがない")
    ref_part = body.split("## 参考情報", 1)[1] if "## 参考情報" in body else ""
    if len(re.findall(r"https?://", ref_part)) < 2:
        issues.append("参考情報のリンクが2件未満")

    return list(dict.fromkeys(issues))


def strict_critique(api_key, model, article, memo, sources, titles):
    passed, report, checks = _base_critique(
        api_key,
        model,
        article,
        memo,
        sources,
        titles,
    )

    # q.critique 内の local_checks は q.local_checks に差し替わるため、
    # ここでも明示的に再確認して取りこぼしを防ぐ。
    checks = list(dict.fromkeys([*checks, *strict_local_checks(article, memo, titles)]))

    text = article["title"] + "\n" + article["body"]
    risky_patterns = [
        (r"\d[\d,]*\s*円", "金額を記載。調査メモの裏取りを再確認"),
        (r"(?:必ず|完全に|確実に).{0,24}(?:解決|直る|防げる|成功|復旧)", "結果を強く断定"),
        (r"(?:絶対|100%).{0,20}(?:安全|成功|解決|防止)", "過度な断定"),
    ]
    for pattern, message in risky_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            checks.append(message)

    # 参照元が少ない記事は公開しない。
    if len(sources) < 2:
        checks.append("Google検索の参照元が2件未満")

    # QA側がPASSでも、問題点を1件でも検出したら公開しない。
    if checks:
        passed = False

    return passed, report, list(dict.fromkeys(checks))


q.gemini = robust_gemini
q.write_article = strict_write_article
q.local_checks = strict_local_checks
q.critique = strict_critique

if __name__ == "__main__":
    try:
        raise SystemExit(q.main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
