import json
import os
import re
import sys
import time
import quality_v2 as q
from official_sources import TOPIC_SEEDS, search_official_query, source_summary_for_prompt

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
    高品質Flashを優先し、必要時のみ現行Flash-Liteへフォールバックする。
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
    先に公式資料を取得できるテーマ候補を選び、
    その公式資料だけを読ませて記事企画を作る。
    """
    for seed in TOPIC_SEEDS:
        seed_score, _ = q.nearest(seed["label"], titles)
        if seed_score >= 0.58:
            continue
        if seed["label"] in reject:
            continue

        print(f"公式テーマ候補: {seed['label']}")
        official = search_official_query(
            seed["query"],
            seed["domains"],
            max_sources=3,
        )
        if len(official) < 2:
            print(
                f"WARNING: 「{seed['label']}」は公式資料が"
                f"{len(official)}件しか取れないためスキップ"
            )
            continue

        evidence = source_summary_for_prompt(official)
        plan_prompt = f"""
あなたは実用系Webメディアの編集者です。
以下の公式資料だけを読み、1本の記事企画を作ってください。
あなた自身の記憶や一般知識を事実の根拠に使ってはいけません。

ブログ方針:
{theme}

記事候補:
{seed['label']}

公式資料:
{evidence}

最近の記事:
{chr(10).join(f"- {t}" for t in titles[:30]) or "- なし"}

条件:
- 公式資料で十分説明できる範囲だけを記事テーマにする
- 公式資料にない高度なトラブルシューティングへ広げない
- 読者が実際に操作できる具体的なテーマにする
- 1記事1検索意図
- PC版とAndroid版、iPhone版など複数プラットフォームを1記事に混ぜない
- 記事候補に端末指定がない場合はPC版を優先し、そのプラットフォームだけを書く
- 公式資料にない画面名・手順・仕様・効果を作らない
- 料金、ランキング、口コミ、推測は扱わない
- 最近の記事の焼き直しにしない

JSONだけ:
{{
  "topic":"公式資料で説明可能な具体テーマ",
  "working_title":"18〜42文字の仮タイトル",
  "pillar":"PC設定・トラブル解決 / スマホ設定・データ整理 / Webサービス・AIツール活用 / バックアップ・ファイル管理 / 個人の作業効率化 のどれか",
  "platform":"PC版Chrome / Android版Chrome / Windows / iPhone / Mac など1つだけ",
  "reader":"対象読者",
  "search_intent":"読み終わった時にできること",
  "answer_first":"最初に伝える答え",
  "must_answer":["公式資料から答えられる論点を3〜6個"],
  "verified_facts":["公式資料で直接確認できる事実を3〜8個"],
  "pitfalls":["公式資料で確認できる注意点"],
  "hands_on":["公式資料で確認できる操作手順"],
  "avoid_claims":["公式資料にないため書かない内容"]
}}
""".strip()

        data = None
        for attempt in range(2):
            try:
                text, _, _ = robust_gemini(
                    api_key,
                    model,
                    plan_prompt,
                    search=False,
                    json_mode=True,
                    max_tokens=4000,
                )
                data = q.parse_json(text)
                break
            except (json.JSONDecodeError, ValueError) as e:
                print(f"WARNING: 公式企画JSONを再生成します: {e}")
                plan_prompt += (
                    "\nJSON文字列内の改行や引用符を正しくエスケープし、"
                    "JSONオブジェクト以外を出力しないでください。"
                )

        if not data or not data.get("topic") or not data.get("working_title"):
            continue

        title_score, old = q.nearest(data["working_title"], titles)
        if title_score >= 0.60:
            print(
                f"WARNING: 企画タイトルが既存記事「{old}」と似すぎ "
                f"({title_score:.2f}) のため次候補へ"
            )
            continue

        data["official_evidence"] = evidence
        data["official_seed"] = seed["label"]
        data["grounding_rule"] = (
            "記事中の製品仕様、画面名、操作手順、挙動、注意点は"
            "official_evidenceに明記された内容だけを事実として扱う。"
            "公式資料にないことは書かない。"
        )
        sources = [
            {
                "title": src["title"],
                "url": src["url"],
                "domain": src.get("domain", ""),
            }
            for src in official
        ]
        print(f"公式資料を{len(sources)}件取得して企画化")
        return data, sources, [seed["query"]]

    raise RuntimeError("最近の記事と重複せず、公式資料を2件以上取得できるテーマがありません")
def ensure_official_references(article, sources):
    if not sources:
        return article

    body = article["body"].strip()

    # AIが作った参考情報は内容が揺れるので、公式検索で取得したURLからコード側で再構築する。
    body = re.sub(
        r"\n+## 参考情報\s*\n.*$",
        "",
        body,
        flags=re.DOTALL,
    ).rstrip()

    refs = []
    seen = set()
    for src in sources:
        url = (src.get("url") or "").strip()
        title = (src.get("title") or url).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        refs.append(f"- [{title}]({url})")
        if len(refs) >= 3:
            break

    if len(refs) < 2:
        raise RuntimeError("公式参考リンクを2件以上確保できませんでした")

    article["body"] = body + "\n\n## 参考情報\n\n" + "\n".join(refs)
    return article


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
- 本文は1400〜2200字を目安にする。公式資料で言えることが少ない場合は無理に長くしない
- 冒頭2〜3文で読者の疑問への答えを先に示す
- 1記事では1つのOS・端末・プラットフォームだけを扱う。PCとAndroid等を混在させない
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

    article = _base_write_article(
        api_key,
        model,
        theme,
        memo,
        sources,
        titles,
        combined,
    )
    return ensure_official_references(article, sources)


def strict_local_checks(article, memo, titles):
    issues = list(_base_local_checks(article, memo, titles))
    body = article["body"]

    if len(body) < 1300:
        issues.append(f"本文がまだ薄い ({len(body)}文字)")
    if len(body) > 2800:
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



def grounding_audit(api_key, model, article, memo):
    evidence = memo.get("official_evidence", "")
    if not evidence:
        return False, ["公式資料本文がありません"]

    prompt = f"""
あなたは実用記事のファクトチェック担当です。
次の公式資料だけを根拠に、記事に「読者を誤操作させる実質的な誤り」がないか監査してください。
一般知識やあなた自身の記憶は根拠に使わないでください。

【公式資料】
{evidence}

【記事】
タイトル: {article['title']}
本文:
{article['body']}

重要な判定ルール:
- 目的、設定経路、ボタン/項目、機能の効果、データ消失リスクなど、読者の行動結果に影響する内容を重点監査する
- 公式資料に明記された手順を自然な日本語に言い換えたものはSUPPORTED
- 「3点メニュー」「画面左側」などの補助的な見た目説明や、ごく軽微な表記差だけではFAILにしない
- 「通知をオン/オフ」と「通知を許可/ブロック」のように意味が同じ言い換えは矛盾扱いしない
- OSや端末が異なる手順を混ぜ、読者が操作できなくなる場合は重大なCONFLICT
- 公式資料にない追加の操作・機能・効果を事実として断定している場合はMATERIAL_UNSUPPORTED
- 危険な操作、データ消失につながる誤り、存在しない設定経路は必ずFAIL
- 単なる文体、タイトルの言い回し、補足的な説明の不足はこの監査ではFAILにしない

JSONだけ:
{{
  "pass": true,
  "material_unsupported": ["重大な未裏付け主張"],
  "conflicts": ["実質的な矛盾"],
  "minor_notes": ["公開を止めるほどではない軽微な表現差"]
}}
""".strip()

    text, _, _ = robust_gemini(
        api_key,
        model,
        prompt,
        search=False,
        json_mode=True,
        max_tokens=2500,
    )
    report = q.parse_json(text)
    unsupported = [
        x for x in report.get("material_unsupported", []) if isinstance(x, str)
    ]
    conflicts = [x for x in report.get("conflicts", []) if isinstance(x, str)]
    minor = [x for x in report.get("minor_notes", []) if isinstance(x, str)]

    if minor:
        print("公式監査の軽微な注記: " + " / ".join(minor[:4]))

    passed = bool(report.get("pass")) and not unsupported and not conflicts
    problems = []
    problems.extend(f"公式資料で重大な裏付け不足: {x}" for x in unsupported[:6])
    problems.extend(f"公式資料と実質矛盾: {x}" for x in conflicts[:6])
    return passed, problems

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
            grounded, grounding_problems = grounding_audit(
                api_key, model, article, memo
            )
            if not grounded:
                checks.extend(grounding_problems or ["公式資料との整合監査に不合格"])
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
