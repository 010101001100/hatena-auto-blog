import json
import os
import re
import sys
import time
import quality_v2 as q
from quality_gate import completion_result, evaluate_quality
from article_checks import practical_static_checks
from execution_plan import execution_plan_issues, format_execution_plan
from official_sources import TOPIC_SEEDS, search_official_query, source_summary_for_prompt

_base_gemini = q.gemini
_base_write_article = q.write_article
_base_critique = q.critique
_base_local_checks = q.local_checks
_base_research = q.research

FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-3.1-flash-lite"]
_LAST_CALL = 0.0
_CALL_COUNT = 0
_EXHAUSTED_MODELS = set()


class ModelDailyQuotaExceeded(RuntimeError):
    """当日の無料枠が尽きたモデル。短時間の再試行では回復しない。"""


class ApiCallBudgetExceeded(RuntimeError):
    """今回の自動実行に割り当てたAPI呼び出し枠を使い切った。"""


def _quota_exhausted(exc):
    message = str(exc).lower()
    return (
        "you exceeded your current quota" in message
        or "quota exceeded for metric" in message
        or ("http 429" in message and "free_tier_requests" in message)
    )


def _short_error(exc):
    # Geminiの大きなエラーJSONを繰り返しログへ流さない。
    return str(exc).splitlines()[0][:180]


def _throttle():
    global _LAST_CALL
    # 短時間の連続呼び出しを避ける。日次クォータ超過にはsleepを使わない。
    wait = 13.0 - (time.monotonic() - _LAST_CALL)
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL = time.monotonic()


def _call_base(*args, **kwargs):
    global _CALL_COUNT
    budget = max(1, int(os.getenv("MAX_GEMINI_CALLS", "14")))
    if _CALL_COUNT >= budget:
        raise ApiCallBudgetExceeded(
            f"実行あたりのGemini API呼び出し上限（{budget}回）に達したため公開を保留"
        )
    _throttle()
    _CALL_COUNT += 1
    return _base_gemini(*args, **kwargs)


def _is_transient_gemini_error(exc):
    message = str(exc).lower()
    if _quota_exhausted(exc):
        return False
    return any(
        token in message for token in (
            "http 429", "http 500", "http 502", "http 503", "http 504",
            "temporarily unavailable", "high demand",
            "connection reset", "timed out", "timeout",
        )
    )


def _call_with_retry(*args, **kwargs):
    # quality_v2.gemini()の内側では再試行しない。ここで一度だけ再試行する。
    for attempt in range(2):
        try:
            return _call_base(*args, **kwargs)
        except (ApiCallBudgetExceeded, ModelDailyQuotaExceeded):
            raise
        except RuntimeError as exc:
            if _quota_exhausted(exc):
                raise ModelDailyQuotaExceeded(_short_error(exc)) from exc
            if attempt or not _is_transient_gemini_error(exc):
                raise
            print(f"WARNING: Gemini一時エラー。8秒後に1回だけ再試行: {_short_error(exc)}")
            time.sleep(8)
    raise AssertionError("unreachable")


def _models(primary):
    out = []
    for model in [primary, *FALLBACK_MODELS]:
        if model and model not in out and model not in _EXHAUSTED_MODELS:
            out.append(model)
    return out


def _call_candidates(api_key, model, prompt, *, search, json_mode, max_tokens):
    errors = []
    for candidate in _models(model):
        try:
            if candidate != model:
                print(f"INFO: 利用可能な代替Geminiモデル: {candidate}")
            result = _call_with_retry(
                api_key, candidate, prompt, search=search,
                json_mode=json_mode, max_tokens=max_tokens,
            )
            if search and len(result[1]) < 2:
                errors.append(f"{candidate}: 検索ソースが2件未満")
                continue
            return result
        except ModelDailyQuotaExceeded as exc:
            _EXHAUSTED_MODELS.add(candidate)
            print(f"WARNING: {candidate} は日次クォータ超過。実行中は再利用しません")
            errors.append(f"{candidate}: {_short_error(exc)}")
        except ApiCallBudgetExceeded:
            raise
        except RuntimeError as exc:
            errors.append(f"{candidate}: {_short_error(exc)}")

    if not _models(model):
        raise ModelDailyQuotaExceeded(
            "使用可能なGeminiモデルの日次クォータが尽きたため、記事公開を保留"
        )
    raise RuntimeError("Gemini API失敗: " + " / ".join(errors[-3:]))


def robust_gemini(api_key, model, prompt, search=False, json_mode=False, max_tokens=7000):
    """
    モデルあたりの日次クォータ枯渇は記録して再試行しない。
    Gemini検索は任意。記事企画の一次情報はretry_researchで直接取得する。
    """
    if search:
        search_enabled = os.getenv("USE_GOOGLE_SEARCH", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }
        if search_enabled:
            try:
                return _call_candidates(
                    api_key, model, prompt, search=True,
                    json_mode=json_mode, max_tokens=max_tokens,
                )
            except (ModelDailyQuotaExceeded, ApiCallBudgetExceeded):
                raise
            except RuntimeError as exc:
                print(f"WARNING: Gemini検索に失敗したため安全な調査へ: {_short_error(exc)}")
        else:
            print("INFO: Gemini検索無効（公式ページの直接取得を優先）")

        safe_prompt = """
重要: このGemini応答にはGoogle検索グラウンディングを使いません。
自分が検索した、最新情報を調べた、などの主張をしないこと。
一次情報の確認は別の公式ページ取得処理が行います。
料金・鮮度依存の未確認主張、根拠のない数値・ランキングを記載しないこと。
""".strip() + "\n\n" + prompt
        return _call_candidates(
            api_key, model, safe_prompt, search=False,
            json_mode=json_mode, max_tokens=max_tokens,
        )

    return _call_candidates(
        api_key, model, prompt, search=False,
        json_mode=json_mode, max_tokens=max_tokens,
    )


def _seed_group(seed):
    label = (seed.get("label") or "").lower()
    if "yt-dlp" in label:
        return "yt-dlp"
    if "ffmpeg" in label or "ffprobe" in label:
        return "ffmpeg"
    if "python" in label or "pip" in label or "venv" in label or "requirements.txt" in label:
        return "python"
    if "powershell" in label or "winget" in label or "windowsで環境変数" in label:
        return "powershell"
    if "github" in label:
        return "github"
    if label.startswith("git") or " git" in label:
        return "git"
    if "vs code" in label:
        return "vscode"
    if "docker" in label:
        return "docker"
    return "other"


def _title_group(title):
    text = (title or "").lower()
    checks = [
        ("yt-dlp", ["yt-dlp"]),
        ("ffmpeg", ["ffmpeg", "ffprobe"]),
        ("python", ["python", "pip", "venv", "requirements"]),
        ("powershell", ["powershell", "winget", "環境変数path"]),
        ("github", ["github"]),
        ("git", ["git ", "gitで", "gitの"]),
        ("vscode", ["vs code", "vscode"]),
        ("docker", ["docker"]),
    ]
    for group, tokens in checks:
        if any(token in text for token in tokens):
            return group
    return None


def _diversified_seeds(titles):
    buckets = {}
    for seed in TOPIC_SEEDS:
        buckets.setdefault(_seed_group(seed), []).append(seed)

    # 直近記事からカテゴリ利用履歴を推定する。
    recent_groups = [
        group
        for group in (_title_group(title) for title in titles[:14])
        if group
    ]
    last_group = recent_groups[0] if recent_groups else None

    # 同カテゴリの連投は禁止。
    blocked = {last_group} if last_group else set()

    # yt-dlpは直近3記事に1本まで。直近3記事にあれば今回候補から完全除外。
    if "yt-dlp" in recent_groups[:3]:
        blocked.add("yt-dlp")

    groups = [g for g in buckets if g not in blocked]
    if not groups:
        groups = list(buckets)

    def group_priority(group):
        count = recent_groups.count(group)
        try:
            last_seen = recent_groups.index(group)
        except ValueError:
            last_seen = 999
        # 未登場/長く出ていないカテゴリを最優先し、出現回数が多いカテゴリを後回し。
        return (-last_seen, count)

    group_order = sorted(groups, key=group_priority)
    print(
        "カテゴリ優先順: "
        + " -> ".join(group_order)
        + (f" / 除外: {', '.join(sorted(blocked))}" if blocked else "")
    )

    # 各カテゴリの1本目を先に試し、同カテゴリ候補の連続消化を防ぐ。
    ordered = []
    max_len = max((len(buckets[g]) for g in group_order), default=0)
    for i in range(max_len):
        for group in group_order:
            if i < len(buckets[group]):
                ordered.append(buckets[group][i])
    return ordered


def retry_research(api_key, model, theme, titles, reject=""):
    """
    先に公式資料を取得できるテーマ候補を選び、
    その公式資料だけを読ませて記事企画を作る。
    """
    for seed in _diversified_seeds(titles):
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
- **最優先**：前提確認から成功判定まで、記事だけで完結できる狭い検索意図を選ぶ
- 例: Docker Desktopの「必要条件の確認」と「インストールと仮想化設定の全作業」を同時に扱わない。1記事1つの完了目標に絞る
- 不確実なBIOS/UEFIの変更やメーカー固有操作など、公式資料にない作業を読者に強要しない
- 実機ごとに異なる作業は「要確認」「公式の端末メーカー資料へ」として範囲を区切り、具体的な操作を創作しない
- 満たす必要のある事前条件を「確認方法」と「不足している場合の分岐」に分ける
- 完了確認のコマンドや画面表示を、裏付けがある範囲で必ず用意する
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
  "pillar":"CLI・コマンドライン / Python・開発環境 / Git・GitHub / 動画・音声ツール / Windows・PowerShell / VS Code・Docker のどれか",
  "platform":"PC版Chrome / Android版Chrome / Windows / iPhone / Mac など1つだけ",
  "reader":"対象読者",
  "search_intent":"読み終わった時にできること",
  "answer_first":"最初に伝える答え",
  "must_answer":["公式資料から答えられる論点を3〜6個"],
  "verified_facts":["公式資料で直接確認できる事実を3〜8個"],
  "pitfalls":["公式資料で確認できる注意点"],
  "hands_on":["公式資料で確認できる操作手順"],
  "avoid_claims":["公式資料にないため書かない内容"],
  "execution_plan": {{
    "scope":"1記事で完了する単一の作業目的。インストール全体と要件確認を混同しない",
    "prerequisites":["読者が開始前に確認する条件と、具体的な確認方法を1〜6件"],
    "steps":["目的達成のために順に行う操作を2〜8件。画面名・入力コマンドは公式根拠があるもののみ"],
    "success_check":"最後に読者が目視またはコマンドで確認できる明確な成功条件",
    "failure_paths":["条件不足や予想と違う表示の時、公式に裏付けられる確認・分岐を1〜5件"]
  }}
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

        plan_problems = execution_plan_issues(data)
        if plan_problems:
            print(
                "WARNING: 初稿前の実行計画が不完全。記事生成せず候補を見直します: "
                + " / ".join(plan_problems)
            )
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
- 本文は1600〜3500字を目安にする。実用上必要なら増減し、文字数合わせで水増ししない
- 冒頭2〜3文で読者の疑問への答えを先に示す
- 1記事では1つのOS・端末・プラットフォームだけを扱う。PCとAndroid等を混在させない
- 「なぜ」だけでなく「どこをどう操作するか」「どう判断するか」を書く
- 具体的な手順・設定例・判断基準のうち最低2種類を入れる
- 読者が記事を閉じた直後に1つ以上の行動を取れる内容にする
- 初心者が冒頭から最後まで順番に操作できるよう、前提条件・入力場所・実行例・期待される結果を示す
- ファイル名を指定して実行するなら、そのファイルの作成・保存方法を説明する（読者がすでに所有していると前提にしない）
- コード例には実行に必要なファイル名・カレントディレクトリ・実行コマンドを揃える
- 環境差・失敗時の確認方法を最低1つ載せる。根拠のない修復手順は書かない
- エラー対処は検索意図に直結するものだけに絞り、別記事の話題を混ぜない
- 出力結果を例示する場合は未検証の実測結果と偽らず、説明用の期待値として示す
- Github.comのSSHキー登録/セットアップでは、公式資料に基づき `ssh -T git@github.com` で接続確認し、期待される認証メッセージを示す
- VS Codeの`Ctrl+Up`については、ターミナル表示を以前のコマンド位置へスクロールする操作と、入力欄で過去のコマンドを呼び出す操作を混同しない
- 「便利です」「おすすめです」「重要です」だけで段落を終わらせない
- 抽象論が2段落続いたら具体例・手順・条件に置き換える
- 「まとめ」「はじめに」「おわりに」だけの抽象見出しは禁止
- タイトルは説明的で自然にする。「うざい！」「徹底解説」「完全版」「設定術」「必見」など煽り・SEO量産風の語は禁止
- タイトルで同じ意味を重ねない（例: 「方法と設定変更手順」）
{evidence_rule}
""".strip()

    # 調査1回で作成した完走計画を初稿の最優先指示として再利用する。
    # 追加のGemini企画呼び出しを増やさない。
    plan_text = format_execution_plan(memo)
    combined = (
        "【最優先：初稿から読者が完走できる記事を書く】\n"
        + plan_text
        + "\n\n"
        + "計画の各前提・操作・成功結果・失敗分岐を本文で明示する。"
        + "ただし根拠のないBIOS画面やUI操作を創作しない。"
        + "目的が要件確認なら、環境設定の変更まで無理に本文へ含めない。"
        + "実行コマンドは入力する場所と期待する表示をセットで示す。"
        + "\n\n"
        + quality_rule
    )
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
    title = article["title"]
    body = article["body"]

    title_banned = ["うざい", "徹底解説", "完全版", "設定術", "必見"]
    for phrase in title_banned:
        if phrase in title:
            issues.append(f"SEO量産風タイトル: {phrase}")
    if "方法と設定変更手順" in title or "方法と手順" in title:
        issues.append("タイトルが意味重複")

    if len(body) < 1300:
        issues.append(f"本文がまだ薄い ({len(body)}文字)")
    if len(body) > 4200:
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

def practical_audit(api_key, model, article, memo):
    """読者が成功状態に到達できるかを、採点AIとは別の問いで監査する。"""
    prompt = f"""
あなたは初心者向け技術記事の手順テスターです。
以下の記事を、何も準備していない読者が上から順に操作するものとして監査してください。
想像で省略手順を補ってはいけません。実機テストをしたと主張してはいけません。

【読者】
{memo.get('reader', '')}
【達成すべき検索意図】
{memo.get('search_intent', '')}
【公式資料に基づく完走計画】
{format_execution_plan(memo)}
【記事】
タイトル: {article['title']}
本文:
{article['body']}

重大欠落として指摘する例:
- hello.pyなど未作成のファイルを突然実行し、作成・保存手順がない
- 作業ディレクトリが不明で、説明通り入力しても対象ファイルを見つけられない
- コマンドをcmd、Python対話モードなどどこへ入力するか分からない
- 成功したか判断できる表示・結果・確認方法がない
- GitHub.comのSSHキー登録記事で、`ssh -T git@github.com` による疎通確認と期待する認証メッセージがない
- VS Codeの履歴ナビゲーションで、`Ctrl+Up` が表示位置へスクロールする操作なのに、入力欄へコマンドを再入力する操作と説明している
- 記事の目的達成に必須の前提や作業が丸ごと省略されている
- 記事のゴールが「要件確認」なのに「メーカー固有のBIOS変更方法」まで必須だと誤認していないか注意する
- 企画のscope内で成功できることを評価し、scope外の高度な操作を追加要求しない
- 根拠のない画面名・手順を捏造してまで完了を演出してはいけない
- 利用不可時の切り分けがなく、読者が容易につまずく

不要な例の水増しや、テーマ外の高度なエラー対処は要求しない。
記事の操作に致命的な欠落がなければpass=trueとする。

必ず以下のJSONだけ返す:
{{"pass":true,"blocking_gaps":[],"minor_notes":[]}}
""".strip()
    text, _, _ = robust_gemini(
        api_key, model, prompt, search=False, json_mode=True, max_tokens=2200
    )
    return completion_result(q.parse_json(text))


def preflight_checks(article, memo, sources, titles):
    """無駄なAPI採点を避けるため、ローカルで落とせる原稿を先に弾く。"""
    checks = [*strict_local_checks(article, memo, titles)]
    checks.extend(practical_static_checks(article, memo))

    if len(sources) < 2:
        checks.append("公式資料が2件未満")
    if not memo.get("official_evidence"):
        checks.append("公式資料本文の根拠が調査メモにない")

    body = article["body"]
    if "## 参考情報" not in body:
        checks.append("参考情報セクションがない")
    else:
        refs = body.split("## 参考情報", 1)[1]
        ref_urls = re.findall(r"https?://[^)\s>]+", refs)
        if len(ref_urls) < 2:
            checks.append("参考リンクが2件未満")
        allowed_urls = {source.get("url", "") for source in sources}
        if any(url not in allowed_urls for url in ref_urls):
            checks.append("公式調査で取得していないURLを参考情報に使用")

    return list(dict.fromkeys(checks))


def _early_revision(checks):
    """機械的にREVISEと判断できる原稿に採点APIを使わない。"""
    report = {
        "decision": "REVISE",
        "score_100": 0,
        "problems": checks,
        "revision_instructions": checks,
    }
    return False, report, checks


def strict_critique(api_key, model, article, memo, sources, titles):
    checks = preflight_checks(article, memo, sources, titles)
    if checks:
        return _early_revision(checks)

    # まず編集点数を取得。明らかな不合格稿に追加のAI監査を使わない。
    _, report, base_checks = _base_critique(
        api_key, model, article, memo, sources, titles
    )
    checks = list(dict.fromkeys([*checks, *base_checks]))
    preliminary_pass, score, reasons = evaluate_quality(
        report, checks, grounded_ok=True, practical_ok=True
    )
    report["score_100"] = score
    if not preliminary_pass:
        return False, report, reasons

    # 操作の完走性を先に監査し、欠落があれば公式監査のAPI呼び出しを節約。
    # API上限エラーはREVISEとして握りつぶさず、投稿せずに実行を止める。
    practical_ok, practical_problems = practical_audit(
        api_key, model, article, memo
    )
    if not practical_ok:
        return (
            False,
            report,
            evaluate_quality(
                report, practical_problems, grounded_ok=True, practical_ok=False
            )[2],
        )

    grounded_ok, grounding_problems = grounding_audit(
        api_key, model, article, memo
    )
    passed, score, checks = evaluate_quality(
        report, grounding_problems, grounded_ok, practical_ok
    )
    report["score_100"] = score
    return passed, report, checks


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
