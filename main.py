import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import requests
import markdown

ATOM_NS = "http://www.w3.org/2005/Atom"
APP_NS = "http://www.w3.org/2007/app"

ET.register_namespace("", ATOM_NS)
ET.register_namespace("app", APP_NS)


def env(name: str, default: str = "", required: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"環境変数 {name} が設定されていません")
    return value


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def endpoint(hatena_id: str, blog_id: str) -> str:
    return f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"


def fetch_recent_titles(url: str, hatena_id: str, api_key: str) -> list[str]:
    r = requests.get(url, auth=(hatena_id, api_key), timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = {"atom": ATOM_NS}
    titles = []
    for entry in root.findall("atom:entry", ns):
        t = entry.findtext("atom:title", default="", namespaces=ns).strip()
        if t:
            titles.append(t)
    return titles[:10]


def gemini_text(api_key: str, model: str, prompt: str, temperature: float = 0.7) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 6000,
        },
    }
    r = requests.post(url, params={"key": api_key}, json=payload, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini API失敗: HTTP {r.status_code}\n{r.text[:1200]}")
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Gemini APIの応答を解析できません: {data}") from e


def build_topic_prompt(theme: str, recent_titles: list[str]) -> str:
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- なし"
    return f"""
次のブログ向けに、直近記事と明確に異なる新しい記事ネタを1つ選んでください。

ブログの方向性:
{theme}

直近の記事タイトル:
{recent}

厳守:
- 直近記事と同じ製品名・サービス名・OS名・トラブル種別を選ばない
- 直近記事がDocker/Immich/Windows系なら、それらを含むテーマは避ける
- 「○○が起動しない」「○○エラー」など似たトラブル解決記事を連投しない
- ブログの方向性から外れない
- 初心者が検索しそうな具体的な疑問にする
- 最新ニュースや価格など鮮度依存の話題は避ける

出力形式:
TOPIC: 記事テーマ
INTENT: 読者が解決したいこと
MUST_INCLUDE: 記事に必ず入れる具体要素
""".strip()


def choose_topic(api_key: str, model: str, theme: str, recent_titles: list[str]) -> tuple[str, str, str]:
    text = gemini_text(
        api_key,
        model,
        build_topic_prompt(theme, recent_titles),
        temperature=0.85,
    )
    topic = re.search(r"TOPIC:\s*(.+)", text)
    intent = re.search(r"INTENT:\s*(.+)", text)
    must = re.search(r"MUST_INCLUDE:\s*(.+)", text)
    if not (topic and intent and must):
        raise RuntimeError("記事ネタ選定の出力を解析できませんでした")
    return topic.group(1).strip(), intent.group(1).strip(), must.group(1).strip()


def build_draft_prompt(theme: str, syntax: str, recent_titles: list[str], topic: str, intent: str, must_include: str) -> str:
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- なし"
    rule = "本文はMarkdown。見出しは ## / ###、箇条書き、番号付きリスト、コードブロックを適切に使う。"

    return f"""
日本語ブログの記事を1本だけ書いてください。

ブログの方向性:
{theme}

今回の記事テーマ:
{topic}

読者の検索意図:
{intent}

必ず入れる具体要素:
{must_include}

直近の記事:
{recent}

最重要:
- 今回の記事テーマから絶対に逸脱しない
- 直近記事と同じ製品・サービス・OS・トラブルの話へ戻らない
- 読者が検索してきた疑問を1つだけ、具体的に解決する
- 一般論の寄せ集めではなく、その場で試せる手順・設定例・コード例・判断基準のどれかを必ず入れる
- 知らない事実や数字、体験談、口コミ、出典を作らない
- 最新情報の確認が必要な話題は避ける
- 「本記事では」「いかがでしたか」「ぜひ参考にしてください」「〜について解説します」のようなAIっぽい定型文は禁止
- 「はじめに」「まとめ」だけの空疎な見出しは禁止
- 同じ意味の説明を言い換えて水増ししない
- タイトルは具体的で32文字程度まで。煽らない
- 本文は1400〜2400字程度
- 1段落は2〜4文を目安にし、長い段落を作らない
- 見出しの前後には必ず空行を入れる
- 手順が3つ以上ある場合は箇条書きか番号付きリストにする
- コマンド・設定値・コードは必ずコードブロックにする
- 画面上で読みやすい余白を作り、文章を一塊にしない
- H2相当の見出しを3〜6個使う
- {rule}

出力:
TITLE: タイトル
---BODY---
本文
""".strip()

def parse_article(text: str) -> tuple[str, str]:
    m = re.search(r"TITLE:\s*(.+?)\s*\n---BODY---\s*\n(.+)$", text, flags=re.DOTALL)
    if not m:
        raise RuntimeError("AI出力を解析できませんでした")
    return m.group(1).strip(), m.group(2).strip()


def build_quality_prompt(title: str, body: str, theme: str, recent_titles: list[str]) -> str:
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- なし"
    return f"""
あなたは厳しいブログ編集者です。次の原稿を公開してよいか判定してください。

ブログの方向性:
{theme}

直近の記事:
{recent}

原稿タイトル:
{title}

原稿本文:
{body}

公開基準:
1. 読者の疑問が明確で、具体的な答えがある
2. 手順・設定例・コード例・比較軸など、持ち帰れる情報がある
3. 一般論、水増し、同語反復が少ない
4. 捏造した体験談・数字・引用・出典・断定がない
5. タイトルと本文が一致している
6. AIっぽい定型文や過剰な前置きがない
7. 直近記事の焼き直しではない
8. 誤解を招く危険な助言ではない
9. 本文が十分な長さで、段落・見出し・箇条書きが読みやすい

本文を書き直さないでください。判定だけしてください。

出力形式:
QUALITY: PASS または FAIL
REASON: 50〜150文字で理由
""".strip()


def quality_check(api_key: str, model: str, title: str, body: str, theme: str, recent_titles: list[str]) -> tuple[bool, str]:
    if len(title) < 4 or len(title) > 60:
        return False, "タイトル長が不適切"
    if len(body) < 1200:
        return False, f"本文が短すぎる（{len(body)}文字）"

    banned = ["いかがでしたか", "ぜひ参考にしてください", "本記事では"]
    if any(x in body for x in banned):
        return False, "AI定型文を検出"

    text = gemini_text(
        api_key,
        model,
        build_quality_prompt(title, body, theme, recent_titles),
        temperature=0.1,
    )
    m = re.search(r"QUALITY:\s*(PASS|FAIL)", text)
    reason = re.search(r"REASON:\s*(.+)", text)
    if not m:
        return False, "品質判定の形式を解析できませんでした"
    return m.group(1) == "PASS", (reason.group(1).strip() if reason else "理由なし")

def make_atom_xml(
    title: str,
    body: str,
    author: str,
    categories: list[str],
    draft: bool,
    syntax: str,
) -> bytes:
    entry = ET.Element(f"{{{ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = title

    author_el = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
    ET.SubElement(author_el, f"{{{ATOM_NS}}}name").text = author

    # はてな側のMarkdown解釈に依存せず、こちらでHTMLへ変換する。
    # これにより ## や ``` がそのまま表示される事故を防ぐ。
    html_body = markdown.markdown(
        body,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )

    ET.SubElement(
        entry,
        f"{{{ATOM_NS}}}content",
        {"type": "text/html"},
    ).text = html_body

    ET.SubElement(entry, f"{{{ATOM_NS}}}updated").text = datetime.now(
        ZoneInfo("Asia/Tokyo")
    ).isoformat(timespec="seconds")

    for category in categories:
        if category.strip():
            ET.SubElement(entry, f"{{{ATOM_NS}}}category", {"term": category.strip()})

    control = ET.SubElement(entry, f"{{{APP_NS}}}control")
    ET.SubElement(control, f"{{{APP_NS}}}draft").text = "yes" if draft else "no"

    return ET.tostring(entry, encoding="utf-8", xml_declaration=True)

def post_to_hatena(url: str, hatena_id: str, api_key: str, xml_body: bytes) -> str:
    r = requests.post(
        url,
        data=xml_body,
        auth=(hatena_id, api_key),
        headers={"Content-Type": "application/atom+xml;type=entry;charset=utf-8"},
        timeout=30,
    )
    if r.status_code != 201:
        raise RuntimeError(f"はてな投稿失敗: HTTP {r.status_code}\n{r.text[:1000]}")
    return r.headers.get("Location", "")


def main() -> int:
    gemini_key = env("GEMINI_API_KEY", required=True)
    hatena_id = env("HATENA_ID", required=True)
    blog_id = env("HATENA_BLOG_ID", required=True)
    hatena_api_key = env("HATENA_API_KEY", required=True)

    theme = env(
        "BLOG_THEME",
        "Web・AI・プログラミング・副業・ネット活用の実用情報。初心者が実際に手を動かせる内容を優先する",
    )
    model = env("GEMINI_MODEL", "gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"
    syntax = env("BLOG_SYNTAX", "markdown") or "markdown"
    categories = [x.strip() for x in env("BLOG_CATEGORIES", "").split(",") if x.strip()]
    draft = bool_env("HATENA_DRAFT", default=False)
    dry_run = bool_env("DRY_RUN", default=False)

    url = endpoint(hatena_id, blog_id)
    recent_titles = fetch_recent_titles(url, hatena_id, hatena_api_key)

    topic, intent, must_include = choose_topic(
        gemini_key,
        model,
        theme,
        recent_titles,
    )
    print(f"選定テーマ: {topic}")

    title = ""
    body = ""
    passed = False
    reason = ""

    for attempt in range(1, 4):
        prompt = build_draft_prompt(
            theme,
            syntax,
            recent_titles,
            topic,
            intent,
            must_include,
        )
        if reason:
            prompt += f"\n\n前回は品質チェックで不合格でした。理由: {reason}\nテーマは変えず、欠点だけ直して完成原稿を作り直してください。"

        first = gemini_text(
            gemini_key,
            model,
            prompt,
            temperature=0.65,
        )
        title, body = parse_article(first)
        passed, reason = quality_check(
            gemini_key,
            model,
            title,
            body,
            theme,
            recent_titles,
        )

        print(f"試行 {attempt}: {title}")
        print(f"本文文字数: {len(body)}")
        print(f"品質判定: {'PASS' if passed else 'FAIL'} / {reason}")

        if passed:
            break

    if not passed:
        raise RuntimeError(f"3回生成しましたが品質基準を通過しませんでした: {reason}")

    if dry_run:
        print("\n--- DRY RUN: 投稿しません ---\n")
        print(body)
        return 0

    location = post_to_hatena(
        url,
        hatena_id,
        hatena_api_key,
        make_atom_xml(title, body, hatena_id, categories, draft, syntax),
    )
    state = "下書き保存" if draft else "公開投稿"
    print(f"{state}しました: {location or '(Locationヘッダなし)'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
