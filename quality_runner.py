import json
import os
import re
import sys
import time
import quality_v2 as q
from official_sources import search_official, source_summary_for_prompt

_base_gemini = q.gemini
_base_write_article = q.write_article
_base_critique = q.critique
_base_local_checks = q.local_checks
_base_research = q.research

FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-3.1-flash-lite"]
_LAST_CALL = 0.0


def _throttle():
    global _LAST_CALL
    # Free tierの3.8 Flashは短時間の連続呼び出しで429になりやすいので間隔を空ける。
    wait = 13.0 - (time.monotonic() - _LAST_CALL)
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL = time.monotonic()


def _call_base(*args, **kwargs):
    _throttle()
    return _base_gemini(*args, **kwargs)


def _models(primary):
    out = []
    for model in [primary, *FALLBACK_MODELS]:
        if model and model not in out:
            out.append(model)
    return out


def robust_gemini(api_key, model, prompt, search=False, json_mode=False, max_tokens=7000):
    """
    通常は3.8 Flashの安全モードを使用。
    USE_GOOGLE_SEARCH=true の時だけ検索グラウンディングを試す。
    Flash-Liteには落とさない。
    """
    errors = []

    if search:
        search_enabled = os.getenv("USE_GOOGLE_SEARCH", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }

        if search_enabled:
            for candidate in _models(model):
                try:
                    text, sources, queries = _call_base(
                        api_key,
                        candidate,
                        prompt,
                        search=True,
                        json_mode=json_mode,
                        max_tokens=max_tokens,
                    )
                    if len(sources) >= 2:
                        print(f"検索調査モデル: {candidate} / ソース{len(sources)}件")
                        return text, sources, queries
                    errors.append(f"{candidate}: ソース{len(sources)}件")
                except RuntimeError as e:
                    errors.append(f"{candidate}: {e}")
        else:
            print("INFO: Google検索は無効。API枠を記事品質に使うため安全モードへ進みます")

        safe_prompt = """
重要: この実行ではGoogle検索を使っていません。
検索した、公式情報で確認した、最新情報を確認した、とは絶対に書かないでください。

テーマ選定は長く有効なエバーグリーン内容だけに限定してください。
禁止:
- 料金、価格、割合、倍率、ランキング
- 最新、現在、2026年版など鮮度依存の主張
- 特定バージョン番号に依存する細かい仕様
- 医療、法律、投資、税務
- 「公式が推奨」「標準で必ず有効」など未確認の断定

優先:
- 読者自身が画面で確認できる手順
- データ整理、バックアップの考え方
- 設定を確認する順番
- トラブルの切り分け方
- ツールに依存しすぎない作業手順

verified_facts欄も「記事作成時の仮説・確認候補」として慎重に扱ってください。
""".strip() + "\n\n" + prompt

        for candidate in _models(model):
            try:
                print(f"安全なエバーグリーン調査モデル: {candidate}")
                return _call_base(
                    api_key,
                    candidate,
                    safe_prompt,
                    search=False,
                    json_mode=json_mode,
                    max_tokens=max_tokens,
                )
            except RuntimeError as e:
                errors.append(f"{candidate} safe: {e}")

        raise RuntimeError("Gemini調査失敗: " + " / ".join(errors[-4:]))

    for candidate in _models(model):
        try:
            if candidate != model:
                print(f"WARNING: {model} が使えないため {candidate} にフォールバックします")
            return _call_base(
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


def retry_research(api_key, model, theme, titles, reject=""):
    """
    AIはテーマ候補だけ作る。
    その後、公式ドメインを外部検索し、本文を取得できた公式資料が2件以上あるテーマだけ採用する。
    """
    last = None
    accumulated_reject = reject

    for topic_attempt in range(3):
        data = None
        for json_attempt in range(3):
            try:
                extra_reject = accumulated_reject
                if json_attempt:
                    extra_reject = (
                        accumulated_reject
                        + "\n前回はJSON形式が壊れました。改行を含む文字列は正しくJSONエスケープし、"
                        + "JSONオブジェクト以外を一切出力しないでください。"
                    )
                data, _, queries = _base_research(
                    api_key, model, theme, titles, extra_reject
                )
                break
            except (json.JSONDecodeError, ValueError) as e:
                last = e
                print(
                    f"WARNING: 調査JSONの解析に失敗。再生成します "
                    f"({json_attempt + 1}/3): {e}"
                )

        if not data:
            continue

        topic = data.get("topic", "")
        print(f"公式情報を検索: {topic}")
        official = search_official(topic, max_sources=4)

        if len(official) >= 2:
            data["verified_facts"] = []
            data["pitfalls"] = []
            data["hands_on"] = []
            data["official_evidence"] = source_summary_for_prompt(official)
            data["grounding_rule"] = (
                "記事中の製品仕様、画面名、操作手順、挙動、注意点は"
                "official_evidenceに明記された内容だけを事実として扱う。"
                "公式資料にないことは断定しない。"
            )
            sources = [
                {
                    "title": src["title"],
                    "url": src["url"],
                    "domain": src.get("domain", ""),
                }
                for src in official
            ]
            print(f"公式資料を{len(sources)}件取得")
            return data, sources, queries

        print(f"WARNING: 公式資料が{len(official)}件しか取れませんでした。テーマを変更します")
        accumulated_reject += (
            f"\n前回のテーマ「{topic}」は公式資料を2件以上取得できませんでした。"
            "Windows、Chrome、Android、iPhone/iOS、macOS/Safari、"
            "GitHub、ChatGPT/OpenAI、Gmail/Google Drive、OneDriveなど、"
            "公式ヘルプが充実した製品の具体的な困りごとへ変更してください。"
        )

    if last:
        raise last
    raise RuntimeError("公式資料を2件以上取得できる記事テーマを選べませんでした")
def strict_write_article(api_key, model, theme, memo, sources, titles, revision=""):
    if sources:
        evidence_rule = """
- 事実の根拠は調査メモ内の official_evidence だけに限定する
- official_evidence にない製品仕様、画面名、操作手順、挙動、数値を推測で補わない
- 不明な点は断定せず、「環境により表示が異なる場合がある」と必要に応じて限定する
- 本文末尾に必ず「## 参考情報」を作る
- 提示された公式参照先から実際に使った2〜5件だけMarkdownリンクで載せる
- 提示されていないURLを作らない
- 参照情報をそのまま写さず、自分の言葉で要約する
""".strip()
    else:
        evidence_rule = """
検索ソースを取得できていないため、次を厳守:
- 料金、金額、割合、倍率、ランキング、特定バージョン番号を書かない
- 「最新」「公式が推奨」「標準で必ず」「全員」「必ず成功」など未確認の断定をしない
- 製品固有の細かい仕様より、読者自身が画面で確認できる手順・判断基準を優先
- UI名称や挙動は更新で変わりうる場合があることを必要に応じて限定する
- 原因は断定せず「候補」「切り分け」の形で扱う
- 架空の参考URLや出典を書かない
- 「参考情報」セクションは作らない
""".strip()

    quality_rule = f"""
追加の品質条件:
- 本文は2200〜3600字を目安にする。薄い一般論で水増ししない
- 冒頭2〜3文で読者の疑問への答えを先に示す
- 「なぜ」だけでなく「どこをどう操作するか」「どう判断するか」を書く
- 具体的な手順・設定例・判断基準のうち最低2種類を入れる
- 読者が記事を閉じた直後に1つ以上の行動を取れる内容にする
- 「便利です」「おすすめです」「重要です」だけで段落を終わらせない
- 抽象論が2段落続いたら具体例・手順・条件に置き換える
- 「まとめ」「はじめに」「おわりに」だけの抽象見出しは禁止
{evidence_rule}
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
    body = article["body"]

    if len(body) < 1800:
        issues.append(f"本文がまだ薄い ({len(body)}文字)")
    if len(body) > 4600:
        issues.append(f"本文が冗長 ({len(body)}文字)")

    h2s = re.findall(r"(?m)^##\s+(.+)$", body)
    if not 3 <= len(h2s) <= 7:
        issues.append(f"H2数が不適切 ({len(h2s)}個)")
    if any(h.strip() in {"はじめに", "まとめ", "おわりに"} for h in h2s):
        issues.append("抽象的な見出しを使用")

    vague = ["重要です", "大切です", "おすすめです", "便利です", "活用しましょう"]
    vague_hits = sum(body.count(x) for x in vague)
    if vague_hits >= 4:
        issues.append(f"抽象的な定型表現が多い ({vague_hits}箇所)")

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
    checks = list(dict.fromkeys([*checks, *strict_local_checks(article, memo, titles)]))
    text = article["title"] + "\n" + article["body"]

    if len(sources) >= 2:
        if "## 参考情報" not in article["body"]:
            checks.append("参考情報セクションがない")
        refs = article["body"].split("## 参考情報", 1)[1] if "## 参考情報" in article["body"] else ""
        ref_urls = re.findall(r"https?://[^)\s>]+", refs)
        if len(ref_urls) < 2:
            checks.append("参考リンクが2件未満")
        allowed_urls = {s.get("url", "") for s in sources}
        unknown_urls = [u for u in ref_urls if u not in allowed_urls]
        if unknown_urls:
            checks.append("公式調査で取得していないURLを参考情報に使用")
        if "official_evidence" not in memo:
            checks.append("公式資料本文の根拠が調査メモにない")
    else:
        risky_patterns = [
            (r"\d[\d,]*\s*円", "検索未確認なのに具体的な金額を記載"),
            (r"\d+(?:\.\d+)?\s*%", "検索未確認なのに割合を記載"),
            (r"\d+(?:\.\d+)?\s*倍", "検索未確認なのに倍率を記載"),
            (r"(?:必ず|完全に|確実に).{0,24}(?:解決|直る|防げる|成功|復旧)", "検索未確認の結果を強く断定"),
            (r"(?:最新|2026年版|ランキング)", "検索未確認の鮮度依存表現"),
        ]
        for pattern, message in risky_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                checks.append(message)
        if "## 参考情報" in article["body"]:
            checks.append("検索ソースなしなのに参考情報セクションを生成")

    if checks:
        passed = False

    return passed, report, list(dict.fromkeys(checks))


q.gemini = robust_gemini
q.research = retry_research
q.write_article = strict_write_article
q.local_checks = strict_local_checks
q.critique = strict_critique

if __name__ == "__main__":
    try:
        raise SystemExit(q.main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
