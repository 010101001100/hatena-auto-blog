import sys
import quality_v2 as q

_base_gemini = q.gemini
FALLBACK_MODEL = "gemini-3.5-flash-lite"


def robust_gemini(api_key, model, prompt, search=False, json_mode=False, max_tokens=7000):
    errors = []

    # まず指定モデルをそのまま試す。
    try:
        return _base_gemini(
            api_key, model, prompt,
            search=search,
            json_mode=json_mode,
            max_tokens=max_tokens,
        )
    except RuntimeError as e:
        errors.append(f"{model} search={search}: {e}")

    # 検索ツールが契約/クォータ上使えない場合は、検索したふりをさせず同モデルで再試行。
    if search:
        no_search_prompt = (
            "重要: この実行ではGoogle検索ツールを利用できません。"
            "検索したと主張せず、変わりやすい仕様・料金・数値は避け、"
            "長く有効な一般的操作や判断基準だけを扱ってください。\n\n"
            + prompt
        )
        try:
            print(f"WARNING: {model} の検索グラウンディングが使えないため検索なしで再試行します")
            return _base_gemini(
                api_key, model, no_search_prompt,
                search=False,
                json_mode=json_mode,
                max_tokens=max_tokens,
            )
        except RuntimeError as e:
            errors.append(f"{model} search=False: {e}")

    # 上位モデルの割当がない/上限到達なら、従来動作実績のあるFlash-Liteへ落とす。
    if model != FALLBACK_MODEL:
        fallback_prompt = (
            "品質優先。曖昧な一般論を避け、具体的で再現できる内容だけを書いてください。"
            "分からない仕様や数値は作らないでください。\n\n"
            + prompt
        )
        try:
            print(f"WARNING: {model} が利用できないため {FALLBACK_MODEL} にフォールバックします")
            return _base_gemini(
                api_key, FALLBACK_MODEL, fallback_prompt,
                search=False,
                json_mode=json_mode,
                max_tokens=max_tokens,
            )
        except RuntimeError as e:
            errors.append(f"{FALLBACK_MODEL}: {e}")

    raise RuntimeError(" / ".join(errors[-3:]))


q.gemini = robust_gemini

if __name__ == "__main__":
    try:
        raise SystemExit(q.main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
