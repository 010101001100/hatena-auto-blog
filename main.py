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
    return titles[:7]


def build_prompt(theme: str, syntax: str, recent_titles: list[str]) -> str:
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- なし"
    syntax_rules = {
        "markdown": "本文はMarkdown。見出しは ## / ### を使う。",
        "hatena": "本文ははてな記法。大見出しは *、小見出しは ** を使う。",
        "plain": "本文はプレーンテキスト。短い段落と箇条書きを使う。",
    }
    rule = syntax_rules.get(syntax.lower(), syntax_rules["markdown"])
    return f"""
あなたは日本語の実用ブログ編集者です。
次のテーマに沿って、検索から長期的に読まれるエバーグリーン記事を1本作ってください。

ブログテーマ:
{theme}

直近の記事タイトル（似すぎた話題は避ける）:
{recent}

ルール:
- 読者の具体的な疑問や困りごとを1つ解決する
- 自然な日本語のタイトルにする
- おおむね1800〜3000日本語文字
- 結論→理由→手順→注意点→まとめ、の順を基本にする
- 実体験を捏造しない
- 最新ニュース、投資判断、医療診断、法律判断、特定時点の価格・統計などは扱わない
- 根拠のない数字・ランキング・口コミ・引用・出典を作らない
- キーワードを不自然に詰め込まない
- {rule}
- 本文冒頭にタイトルを繰り返さない

出力形式:
TITLE: 記事タイトル
---BODY---
記事本文
""".strip()


def generate_article(api_key: str, model: str, prompt: str) -> tuple[str, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 4096
        }
    }
    r = requests.post(
        url,
        params={"key": api_key},
        json=payload,
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Gemini API失敗: HTTP {r.status_code}\n{r.text[:1200]}")

    data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Gemini APIの応答を解析できません: {data}") from e

    m = re.match(r"^TITLE:\s*(.+?)\s*\n---BODY---\s*\n(.+)$", text, flags=re.DOTALL)
    if not m:
        raise RuntimeError("AI出力を解析できませんでした")
    title = m.group(1).strip()
    body = m.group(2).strip()
    if len(title) < 4 or len(body) < 500:
        raise RuntimeError("生成記事が短すぎるため投稿を中止しました")
    return title, body


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
        "暮らしを少し楽にする実用的なコツ・整理・節約・デジタル活用",
    )
    model = env("GEMINI_MODEL", "gemini-2.5-flash-lite") or "gemini-2.5-flash-lite"
    syntax = env("BLOG_SYNTAX", "markdown") or "markdown"
    categories = [x.strip() for x in env("BLOG_CATEGORIES", "").split(",") if x.strip()]
    draft = bool_env("HATENA_DRAFT", default=False)
    dry_run = bool_env("DRY_RUN", default=False)

    url = endpoint(hatena_id, blog_id)
    recent_titles = fetch_recent_titles(url, hatena_id, hatena_api_key)

    title, body = generate_article(
        gemini_key,
        model,
        build_prompt(theme, syntax, recent_titles),
    )

    print(f"生成タイトル: {title}")
    print(f"本文文字数: {len(body)}")

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
