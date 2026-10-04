import json
import os
import re
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import markdown
import requests

ATOM = "http://www.w3.org/2005/Atom"
APP = "http://www.w3.org/2007/app"
ET.register_namespace("", ATOM)
ET.register_namespace("app", APP)

THEME = (
    "Windows・Linux・CLI・開発ツール・自動化ツールを使う人向けのIT実用ブログ。"
    "yt-dlp、FFmpeg、Python、pip、PowerShell、Git、GitHub、VS Code、Dockerなどの"
    "導入、設定、コマンド、エラー解決、連携方法を中心に、検索してすぐ試せる具体策を扱う。"
    "一般的なスマホ設定や生活系ハウツーより、ツール名やエラー名が明確な技術記事を優先する。"
)
PILLARS = [
    "CLI・コマンドライン",
    "Python・開発環境",
    "Git・GitHub",
    "動画・音声ツール",
    "Windows・PowerShell",
    "VS Code・Docker",
]
BANNED = ["いかがでしたか", "ぜひ参考にしてください", "本記事では", "最後までお読みいただき"]


def env(name, default="", required=False):
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"環境変数 {name} がありません")
    return value


def flag(name, default=False):
    raw = os.getenv(name)
    return default if raw is None else raw.lower().strip() in {"1", "true", "yes", "on"}


def endpoint(hatena_id, blog_id):
    return f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"


def recent_titles(url, hatena_id, api_key, limit=50):
    out, seen, next_url = [], set(), url
    ns = {"a": ATOM}
    for _ in range(8):
        if not next_url or next_url in seen or len(out) >= limit:
            break
        seen.add(next_url)
        r = requests.get(next_url, auth=(hatena_id, api_key), timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for entry in root.findall("a:entry", ns):
            title = entry.findtext("a:title", default="", namespaces=ns).strip()
            if title:
                out.append(title)
        next_url = ""
        for link in root.findall("a:link", ns):
            if link.attrib.get("rel") == "next":
                next_url = link.attrib.get("href", "")
                break
    return out[:limit]


def norm(s):
    return re.sub(r"[\W_]+", "", s.lower(), flags=re.UNICODE)


def similarity(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def nearest(title, titles):
    if not titles:
        return 0.0, ""
    return max((similarity(title, old), old) for old in titles)


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


def dedupe_sources(items):
    out, seen = [], set()
    for item in items:
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(item)
    return out[:10]


def gemini(api_key, model, prompt, search=False, json_mode=False, max_tokens=7000):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if search:
        payload["tools"] = [{"google_search": {}}]
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    error = ""
    for attempt in range(1, 4):
        try:
            r = requests.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=180,
            )
            if r.status_code == 200:
                data = r.json()
                cand = (data.get("candidates") or [None])[0]
                if not cand:
                    raise RuntimeError("Geminiの候補が空です")
                text = "\n".join(
                    p.get("text", "") for p in cand.get("content", {}).get("parts", []) if p.get("text")
                ).strip()
                if not text:
                    raise RuntimeError("Geminiの本文が空です")
                meta = cand.get("groundingMetadata") or {}
                sources = []
                for chunk in meta.get("groundingChunks") or []:
                    web = chunk.get("web") or {}
                    uri = (web.get("uri") or "").strip()
                    if uri.startswith(("http://", "https://")):
                        sources.append({"title": (web.get("title") or uri).strip(), "url": uri})
                queries = [q for q in (meta.get("webSearchQueries") or []) if isinstance(q, str)]
                return text, dedupe_sources(sources), queries
            error = f"HTTP {r.status_code}: {r.text[:1200]}"
            if r.status_code not in {429, 500, 502, 503, 504}:
                break
        except requests.RequestException as e:
            error = str(e)
        time.sleep(attempt * 2)
    raise RuntimeError(f"Gemini API失敗: {error}")


def research(api_key, model, theme, titles, reject=""):
    recent = "\n".join(f"- {t}" for t in titles[:50]) or "- なし"
    prompt = f"""
あなたは実用ブログのリサーチ編集者です。Google検索を使って記事テーマを1つだけ決め、根拠を確認してください。

ブログ方針: {theme}
柱: {' / '.join(PILLARS)}
最近の記事（同じ検索意図は禁止）:
{recent}
{reject}

条件:
- 1記事で1つの具体的な困りごとだけ解決する
- 読者が実際に操作・設定・判断できる内容にする
- 公式ヘルプ、メーカー、開発元など一次情報で確認できるテーマを優先
- 「おすすめ10選」「AIとは」「副業で稼ぐ」のような広い量産テーマは禁止
- 医療、法律、投資、税務、危険作業は扱わない
- 根拠のない数値、口コミ、ランキング、収益話は扱わない

JSONだけを返してください:
{{
 "topic":"具体的な記事テーマ",
 "working_title":"18〜42文字の仮タイトル",
 "pillar":"柱のどれか1つ",
 "reader":"どんな状況の読者か",
 "search_intent":"読み終わった時に何ができれば成功か",
 "answer_first":"冒頭で答える結論",
 "must_answer":["必須論点を4〜7個"],
 "verified_facts":["検索で確認した事実を4〜8個"],
 "pitfalls":["失敗・注意点を2〜5個"],
 "hands_on":["実際に試せる手順やチェック項目"],
 "avoid_claims":["裏取りできないので書かないこと"]
}}
""".strip()
    text, sources, queries = gemini(api_key, model, prompt, search=True, max_tokens=5000)
    data = parse_json(text)
    if not data.get("topic") or not data.get("working_title"):
        raise RuntimeError("調査結果の形式が不正です")
    return data, sources, queries


def unique_research(api_key, model, theme, titles):
    reject = ""
    for i in range(3):
        data, sources, queries = research(api_key, model, theme, titles, reject)
        score, old = nearest(data["working_title"], titles)
        print(f"テーマ候補{i + 1}: {data['working_title']} / 類似度 {score:.2f}")
        if score < 0.64:
            return data, sources, queries
        reject = f"前回候補は既存記事『{old}』と似すぎました。製品・問題・検索意図をすべて変えてください。"
    raise RuntimeError("既存記事と十分に違うテーマを選べませんでした")


def source_text(sources):
    return "\n".join(f"{i}. {s['title']} — {s['url']}" for i, s in enumerate(sources[:8], 1)) or "なし"


def write_article(api_key, model, theme, memo, sources, titles, revision=""):
    recent = "\n".join(f"- {t}" for t in titles[:20]) or "- なし"
    prompt = f"""
あなたは日本語の実用系Webメディアの熟練ライターです。下の調査メモを事実の土台に記事を書いてください。

ブログ方針: {theme}
調査メモ:
{json.dumps(memo, ensure_ascii=False, indent=2)}
検索で取得した参照先:
{source_text(sources)}
最近の記事:
{recent}
{revision}

ルール:
- 冒頭2〜4文で先に答えを書く。長い前置きは禁止
- 1記事1検索意図。テーマを広げない
- 調査メモにplatformがある場合、その1環境だけを扱い、別OS・別端末の手順を混ぜない
- 1200〜2200字を目安に、公式資料で裏付けられる範囲だけを書く
- H2を3〜6個。必要ならH3を使う
- 3手順以上は番号付きリスト。条件分岐や比較は表か箇条書き
- 画面名、設定名、操作順、判断基準など再現可能な情報を優先
- 調査メモにない具体的な数値、料金、仕様、口コミ、体験談を作らない
- 架空の実体験を書かない
- 「本記事では」「いかがでしたか」「ぜひ参考に」「まとめると」は禁止
- 最後を機械的な「まとめ」見出しにしない
- 同じ内容を言い換えて水増ししない
- 他サイトの文章をコピーしない
- Markdown。H1は使わない

JSONだけを返してください:
{{"title":"18〜42文字の完成タイトル","category":"{' / '.join(PILLARS)} のどれか1つ","body":"Markdown本文"}}
""".strip()
    text, _, _ = gemini(api_key, model, prompt, json_mode=True, max_tokens=7000)
    data = parse_json(text)
    for key in ("title", "category", "body"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise RuntimeError(f"記事に{key}がありません")
        data[key] = data[key].strip()
    return data


def local_checks(article, memo, titles):
    title, body = article["title"], article["body"]
    issues = []
    if not 14 <= len(title) <= 48:
        issues.append(f"タイトル長 {len(title)}文字")
    if not 1200 <= len(body) <= 4200:
        issues.append(f"本文長 {len(body)}文字")
    if len(re.findall(r"^## ", body, flags=re.MULTILINE)) < 3:
        issues.append("H2が3個未満")
    if not re.search(r"(?m)^(?:1\.|- |\* )", body):
        issues.append("手順または箇条書きがない")
    for phrase in BANNED:
        if phrase in body:
            issues.append(f"定型句: {phrase}")
    score, old = nearest(title, titles)
    if score >= 0.68:
        issues.append(f"既存記事『{old}』と似すぎ ({score:.2f})")
    return issues


def critique(api_key, model, article, memo, sources, titles):
    recent = "\n".join(f"- {t}" for t in titles[:20]) or "- なし"
    prompt = f"""
あなたは厳格なWebメディア編集長です。褒めずに公開可否を判定してください。
調査メモ:
{json.dumps(memo, ensure_ascii=False, indent=2)}
参照先:
{source_text(sources)}
最近の記事:
{recent}
タイトル: {article['title']}
本文:
{article['body']}

0〜5点で採点: intent_match, specificity, evidence, structure, usefulness, originality
全項目4点以上のみPASS。事実リスク、テーマ逸脱、AI量産文があれば必ずREVISE。
JSONだけ:
{{"decision":"PASS or REVISE","intent_match":0,"specificity":0,"evidence":0,"structure":0,"usefulness":0,"originality":0,"factual_risk":false,"topic_drift":false,"generic_ai_style":false,"problems":["問題点"],"revision_instructions":["具体的な修正指示"]}}
""".strip()
    text, _, _ = gemini(api_key, model, prompt, json_mode=True, max_tokens=2500)
    report = parse_json(text)
    checks = local_checks(article, memo, titles)
    scores = [int(report.get(k, 0)) for k in ("intent_match", "specificity", "evidence", "structure", "usefulness", "originality")]
    flags = any(bool(report.get(k)) for k in ("factual_risk", "topic_drift", "generic_ai_style"))
    passed = report.get("decision") == "PASS" and all(s >= 4 for s in scores) and not flags and not checks
    return passed, report, checks


def revision_note(report, checks):
    problems = checks + [x for x in (report.get("problems") or []) if isinstance(x, str)]
    fixes = [x for x in (report.get("revision_instructions") or []) if isinstance(x, str)]
    return "\n\n".join([
        "前稿は編集チェックで不合格でした。テーマは変えず、全文を修正してください。",
        "問題点:\n" + "\n".join(f"- {x}" for x in problems[:8]),
        "修正指示:\n" + "\n".join(f"- {x}" for x in fixes[:8]),
        "一般論、冗長な前置き、AI定型文も削ってください。",
    ])


def atom_xml(title, body, author, categories, draft):
    entry = ET.Element(f"{{{ATOM}}}entry")
    ET.SubElement(entry, f"{{{ATOM}}}title").text = title
    ae = ET.SubElement(entry, f"{{{ATOM}}}author")
    ET.SubElement(ae, f"{{{ATOM}}}name").text = author
    html = markdown.markdown(body, extensions=["fenced_code", "tables", "sane_lists"], output_format="html5")
    ET.SubElement(entry, f"{{{ATOM}}}content", {"type": "text/html"}).text = html
    ET.SubElement(entry, f"{{{ATOM}}}updated").text = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
    for cat in categories:
        if cat.strip():
            ET.SubElement(entry, f"{{{ATOM}}}category", {"term": cat.strip()})
    control = ET.SubElement(entry, f"{{{APP}}}control")
    ET.SubElement(control, f"{{{APP}}}draft").text = "yes" if draft else "no"
    return ET.tostring(entry, encoding="utf-8", xml_declaration=True)


def publish(url, hatena_id, api_key, xml):
    r = requests.post(url, data=xml, auth=(hatena_id, api_key), headers={"Content-Type": "application/atom+xml;type=entry;charset=utf-8"}, timeout=30)
    if r.status_code != 201:
        raise RuntimeError(f"はてな投稿失敗: HTTP {r.status_code} {r.text[:800]}")
    return r.headers.get("Location", "")


def main():
    key = env("GEMINI_API_KEY", required=True)
    hatena_id = env("HATENA_ID", required=True)
    blog_id = env("HATENA_BLOG_ID", required=True)
    hatena_key = env("HATENA_API_KEY", required=True)
    theme = env("BLOG_THEME", THEME) or THEME
    research_model = env("RESEARCH_MODEL", "gemini-3.8-flash") or "gemini-3.8-flash"
    writer_model = env("WRITER_MODEL", "gemini-3.8-flash") or "gemini-3.8-flash"
    critic_model = env("CRITIC_MODEL", "gemini-3.8-flash") or "gemini-3.8-flash"
    draft, dry_run = flag("HATENA_DRAFT", False), flag("DRY_RUN", False)

    max_topic_attempts = max(1, int(env("MAX_TOPIC_ATTEMPTS", "5") or "5"))
    drafts_per_topic = max(1, int(env("DRAFTS_PER_TOPIC", "2") or "2"))

    url = endpoint(hatena_id, blog_id)
    titles = recent_titles(url, hatena_id, hatena_key, 50)
    print(f"最近の記事: {len(titles)}件")
    print(
        f"投稿成功まで再挑戦: 最大{max_topic_attempts}テーマ / "
        f"各テーマ最大{drafts_per_topic}稿"
    )

    failed_topics = []

    for topic_attempt in range(1, max_topic_attempts + 1):
        print(f"\n=== テーマ挑戦 {topic_attempt}/{max_topic_attempts} ===")

        memo, sources, queries = unique_research(
            key, research_model, theme, titles
        )
        print(f"採用テーマ: {memo['topic']}")
        print(
            f"検索クエリ数: {len(queries)} / "
            f"参照ソース数: {len(sources)}"
        )

        revision = ""
        article = None

        for attempt in range(1, drafts_per_topic + 1):
            article = write_article(
                key,
                writer_model,
                theme,
                memo,
                sources,
                titles,
                revision,
            )
            passed, report, checks = critique(
                key,
                critic_model,
                article,
                memo,
                sources,
                titles,
            )
            keys = (
                "intent_match",
                "specificity",
                "evidence",
                "structure",
                "usefulness",
                "originality",
            )
            score_line = ", ".join(
                f"{k}={report.get(k, '?')}" for k in keys
            )
            print(
                f"テーマ{topic_attempt}・試行{attempt}: "
                f"{article['title']} / {len(article['body'])}文字"
            )
            print(
                f"判定: {'PASS' if passed else 'REVISE'} / "
                f"{score_line}"
            )
            if checks:
                print("機械チェック: " + " / ".join(checks))

            if passed:
                categories = ["実用", article["category"]]

                if dry_run:
                    print("DRY RUN: 投稿しません")
                    print(article["title"])
                    print(article["body"])
                    return 0

                location = publish(
                    url,
                    hatena_id,
                    hatena_key,
                    atom_xml(
                        article["title"],
                        article["body"],
                        hatena_id,
                        categories,
                        draft,
                    ),
                )
                print(
                    ("下書き保存" if draft else "公開投稿")
                    + f"しました: {location}"
                )
                return 0

            revision = revision_note(report, checks)

        # このテーマは品質基準を満たせなかったので、
        # 同じテーマを再選択しないよう「仮の既存記事」として扱って次へ進む。
        failed_title = (
            (article or {}).get("title")
            or memo.get("working_title")
            or memo.get("topic")
            or ""
        )
        failed_topics.append(failed_title)
        if failed_title:
            titles.insert(0, failed_title)
        if memo.get("working_title"):
            titles.insert(0, memo["working_title"])
        if memo.get("topic"):
            titles.insert(0, memo["topic"])

        print(
            f"WARNING: テーマ「{memo.get('topic', '')}」は"
            f"{drafts_per_topic}稿で合格しなかったため破棄し、次テーマへ進みます"
        )

    raise RuntimeError(
        f"{max_topic_attempts}テーマ試しても公開基準を満たす記事を作れませんでした。"
        f"失敗候補: {' / '.join(failed_topics[:max_topic_attempts])}"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
