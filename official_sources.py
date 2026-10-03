import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS


TOPIC_SEEDS = [
    {"label": "Chromeで特定サイトのCookieとサイトデータを削除", "query": "Chrome 特定サイト Cookie サイトデータ 削除", "domains": ["support.google.com"]},
    {"label": "Chromeでサイトごとの通知を許可・ブロック", "query": "Chrome サイト 通知 設定 許可 ブロック", "domains": ["support.google.com"]},
    {"label": "Chromeでカメラ・マイクなどサイト権限を変更", "query": "Chrome サイト 権限 カメラ マイク 変更", "domains": ["support.google.com"]},
    {"label": "Chromeの閲覧データを削除", "query": "Chrome 閲覧データ 削除 キャッシュ Cookie", "domains": ["support.google.com"]},
    {"label": "Chromeの保存済みパスワードを管理", "query": "Chrome Google パスワード マネージャー 保存済み パスワード 管理", "domains": ["support.google.com"]},
    {"label": "Windowsでストレージセンサーを使って空き容量を増やす", "query": "Windows ストレージ センサー 空き容量 Storage Sense", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでスタートアップアプリを管理", "query": "Windows スタートアップ アプリ 管理", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでバックアップからファイルを復元", "query": "Windows バックアップ ファイル 復元 ファイル履歴", "domains": ["support.microsoft.com"]},
    {"label": "Windowsで既定のアプリを変更", "query": "Windows 既定 アプリ 変更 ファイル 種類", "domains": ["support.microsoft.com"]},
    {"label": "WindowsでBluetooth機器を追加・削除", "query": "Windows Bluetooth デバイス 追加 削除", "domains": ["support.microsoft.com"]},
    {"label": "OneDriveのFiles On-Demandで容量を節約", "query": "OneDrive Files On-Demand 容量 オンデマンド ファイル", "domains": ["support.microsoft.com"]},
    {"label": "OneDriveで削除したファイルを復元", "query": "OneDrive 削除 ファイル 復元 ごみ箱", "domains": ["support.microsoft.com"]},
    {"label": "OneDriveの同期を一時停止・再開", "query": "OneDrive 同期 一時停止 再開", "domains": ["support.microsoft.com"]},
    {"label": "iPhoneのiCloudバックアップを設定", "query": "iPhone iCloud バックアップ 設定", "domains": ["support.apple.com"]},
    {"label": "iPhoneでSafariの履歴とWebサイトデータを削除", "query": "iPhone Safari 履歴 Webサイト データ 削除", "domains": ["support.apple.com"]},
    {"label": "iPhoneのストレージ使用量を確認・管理", "query": "iPhone ストレージ 容量 確認 管理", "domains": ["support.apple.com"]},
    {"label": "iPhoneでアプリごとの位置情報アクセスを変更", "query": "iPhone 位置情報 アプリ 権限 変更", "domains": ["support.apple.com"]},
    {"label": "MacをTime Machineでバックアップ", "query": "Mac Time Machine バックアップ 設定", "domains": ["support.apple.com"]},
    {"label": "Macのストレージ容量を確認・最適化", "query": "Mac ストレージ 容量 確認 最適化", "domains": ["support.apple.com"]},
    {"label": "SafariでWebサイトごとの設定を変更", "query": "Safari Webサイト 設定 カメラ マイク 通知", "domains": ["support.apple.com"]},
    {"label": "Androidでアプリの権限を変更", "query": "Android アプリ 権限 変更", "domains": ["support.google.com"]},
    {"label": "Androidで不要なアプリを削除・無効化", "query": "Android アプリ 削除 無効化", "domains": ["support.google.com"]},
    {"label": "Androidでバックアップを設定", "query": "Android バックアップ Google 設定", "domains": ["support.google.com"]},
    {"label": "Googleフォトのバックアップ設定を確認", "query": "Google フォト バックアップ 設定 確認", "domains": ["support.google.com"]},
    {"label": "Gmailでフィルタを作成してメールを自動整理", "query": "Gmail フィルタ 作成 メール 自動 整理", "domains": ["support.google.com"]},
    {"label": "Gmailで送信取り消し時間を設定", "query": "Gmail 送信取り消し 設定", "domains": ["support.google.com"]},
    {"label": "Googleドライブでファイルをオフライン利用", "query": "Google Drive オフライン ファイル 利用", "domains": ["support.google.com"]},
    {"label": "Googleドライブで削除したファイルを復元", "query": "Google Drive 削除 ファイル 復元 ゴミ箱", "domains": ["support.google.com"]},
    {"label": "GitHubで2要素認証を設定", "query": "GitHub two factor authentication 2FA setup", "domains": ["docs.github.com"]},
    {"label": "GitHubでSSHキーを追加", "query": "GitHub SSH key add account", "domains": ["docs.github.com"]},
    {"label": "GitHubでブランチ保護ルールを設定", "query": "GitHub protected branch rules setup", "domains": ["docs.github.com"]},
    {"label": "ChatGPTのデータをエクスポート", "query": "ChatGPT export data", "domains": ["help.openai.com"]},
    {"label": "ChatGPTのカスタム指示を設定", "query": "ChatGPT custom instructions settings", "domains": ["help.openai.com"]},
    {"label": "ChatGPTの会話履歴を削除・アーカイブ", "query": "ChatGPT delete archive chats", "domains": ["help.openai.com"]},
]

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)


def is_official_url(url: str, allowed_domains: list[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_page_text(url: str, timeout: int = 10) -> str:
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": UA,
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            },
        )
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(
            ["script", "style", "noscript", "svg", "nav", "footer", "header"]
        ):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        return clean_text(main.get_text(" ", strip=True))[:12000]
    except requests.RequestException:
        return ""


def search_official_query(
    query: str,
    domains: list[str],
    max_sources: int = 3,
) -> list[dict]:
    candidates = []
    seen = set()

    for domain in domains:
        try:
            results = DDGS(timeout=7).text(
                f"site:{domain} {query}",
                region="jp-jp",
                safesearch="moderate",
                max_results=6,
                backend="bing",
            )
        except Exception as e:
            print(f"WARNING: 公式検索失敗 {domain}: {e}")
            results = []

        for item in results or []:
            url = (item.get("href") or item.get("url") or "").strip()
            if not url or url in seen or not is_official_url(url, domains):
                continue
            seen.add(url)
            candidates.append(
                {
                    "title": clean_text(item.get("title") or url),
                    "url": url,
                    "snippet": clean_text(
                        item.get("body") or item.get("snippet") or ""
                    ),
                    "domain": (urlparse(url).hostname or "").lower(),
                }
            )

    sources = []
    for item in candidates[:8]:
        page_text = fetch_page_text(item["url"])
        evidence = page_text if len(page_text) >= 500 else item["snippet"]
        if len(evidence) < 160:
            continue
        item["evidence"] = evidence[:8000]
        sources.append(item)
        if len(sources) >= max_sources:
            break

    return sources


def source_summary_for_prompt(sources: list[dict]) -> str:
    blocks = []
    for i, src in enumerate(sources, 1):
        blocks.append(
            f"[公式資料{i}]\n"
            f"タイトル: {src['title']}\n"
            f"URL: {src['url']}\n"
            f"抜粋: {src['evidence'][:4500]}"
        )
    return "\n\n".join(blocks)
