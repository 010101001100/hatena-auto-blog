import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import requests

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


def build_draft_prompt(theme: str, syntax: str, recent_titles: list[str]) -> str:
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- なし"
    syntax_rules = {
        "markdown": "本文はMarkdown。見出しは ## / ### を使う。",
        "hatena": "本文ははてな記法。大見出しは *、小見出しは ** を使う。",
        "plain": "本文はプレーンテキスト。",
    }
    rule = syntax_rules.get(syntax.lower(), syntax_rules["markdown"])

    return f"""
日本語ブログの記事を1本だけ書いてください。

ブログの方向性:
{theme}

直近の記事:
{recent}

最重要:
- 直近記事と内容が重複しない
- 読者が検索してきた疑問を1つだけ、具体的に解決する
- 一般論の寄せ集めではなく、その場で試せる手順・設定例・コード例・判断基準のどれかを必ず入れる
- 知らない事実や数字、体験談、口コミ、出典を作らない
- 最新情報の確認が必要な話題は避ける
- 「本記事では」「いかがでしたか」「ぜひ参考にしてください」「〜について解説します」のようなAIっぽい定型文は禁止
- 「はじめに」「まとめ」だけの空疎な見出しは禁止
- 同じ意味の説明を言い換えて水増ししない
- タイトルは具体的で32文字程度まで。煽らない
- 本文は1200〜2400字程度。必要なら短くてよい
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


def build_editor_prompt(title: str, body: str, theme: str, recent_titles: list[str]) -> str:
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- なし"
    return f"""
あなたは厳しいブログ編集者です。次の原稿を公開前に査読してください。

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
3. ありきたりな一般論、水増し、同語反復が少ない
4. 捏造した体験談・数字・引用・出典・断定がない
5. タイトルと本文が一致している
6. AI臭い定型文や過剰な前置きがない
7. 直近記事の焼き直しではない
8. 誤解を招く危険な助言ではない

原稿をそのまま通してはいけません。必要なら大幅に書き直してください。
それでも公開品質にできない場合は FAIL にしてください。

出力形式を厳守:
QUALITY: PASS または FAIL
TITLE: 最終タイトル
---BODY---
最終本文
""".strip()


def edit_and_gate(api_key: str, model: str, title: str, body: str, theme: str, recent_titles: list[str]) -> tuple[bool, str, str]:
    text = gemini_text(
        api_key,
        model,
        build_editor_prompt(title, body, theme, recent_titles),
        temperature=0.25,
    )
    quality = re.search(r"QUALITY:\s*(PASS|FAIL)", text)
    if not quality:
        raise RuntimeError("編集チェック結果を解析できませんでした")
    final_title, final_body = parse_article(text)

    if quality.group(1) != "PASS":
        return False, final_title, final_body

    banned = [
        "いかがでしたか",
        "ぜひ参考にしてください",
        "本記事では",
    ]
    if any(x in final_body for x in banned):
        return False, final_title, final_body

    if len(final_title) < 4 or len(final_title) > 60:
        return False, final_title, final_body
    if len(final_body) < 800:
        return False, final_title, final_body

    return True, final_title, final_body


def make_atom_xml(title: str, body: str, author: str, categories: list[str], draft: bool) -> bytes:
    entry = ET.Element(f"{{{ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = title

    author_el = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
    ET.SubElement(author_el, f"{{{ATOM_NS}}}name").text = author

    ET.SubElement(entry, f"{{{ATOM_NS}}}content", {"type": "text/plain"}).text = body
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

    first = gemini_text(
        gemini_key,
        model,
        build_draft_prompt(theme, syntax, recent_titles),
        temperature=0.75,
    )
    draft_title, draft_body = parse_article(first)

    passed, title, body = edit_and_gate(
        gemini_key,
        model,
        draft_title,
        draft_body,
        theme,
        recent_titles,
    )

    print(f"最終タイトル: {title}")
    print(f"本文文字数: {len(body)}")

    if not passed:
        print("品質チェック不合格のため投稿しませんでした。")
        return 0

    if dry_run:
        print("\n--- DRY RUN: 投稿しません ---\n")
        print(body)
        return 0

    location = post_to_hatena(
        url,
        hatena_id,
        hatena_api_key,
        make_atom_xml(title, body, hatena_id, categories, draft),
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
