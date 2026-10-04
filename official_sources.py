import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS


TOPIC_SEEDS = [
    # Chrome / Google
    {"label": "Chromeで特定サイトのCookieとサイトデータを削除", "query": "Chrome 特定サイト Cookie サイトデータ 削除", "domains": ["support.google.com"]},
    {"label": "Windowsでスタートアップアプリを管理", "query": "Windows スタートアップ アプリ 管理", "domains": ["support.microsoft.com"]},
    {"label": "iPhoneでSafariの履歴とWebサイトデータを削除", "query": "iPhone Safari 履歴 Webサイト データ 削除", "domains": ["support.apple.com"]},
    {"label": "Androidでアプリの権限を変更", "query": "Android アプリ 権限 変更", "domains": ["support.google.com"]},
    {"label": "Gmailでフィルタを作成してメールを自動整理", "query": "Gmail フィルタ 作成 メール 自動 整理", "domains": ["support.google.com"]},
    {"label": "OneDriveのFiles On-Demandで容量を節約", "query": "OneDrive Files On-Demand 容量 オンデマンド ファイル", "domains": ["support.microsoft.com"]},
    {"label": "Chromeでサイトごとの通知を許可・ブロック", "query": "Chrome サイト 通知 設定 許可 ブロック", "domains": ["support.google.com"]},
    {"label": "Windowsで既定のアプリを変更", "query": "Windows 既定 アプリ 変更 ファイル 種類", "domains": ["support.microsoft.com"]},
    {"label": "iPhoneでアプリごとの位置情報アクセスを変更", "query": "iPhone 位置情報 アプリ 権限 変更", "domains": ["support.apple.com"]},
    {"label": "Googleドライブで削除したファイルを復元", "query": "Google Drive 削除 ファイル 復元 ゴミ箱", "domains": ["support.google.com"]},
    {"label": "Chromeでカメラ・マイクなどサイト権限を変更", "query": "Chrome サイト 権限 カメラ マイク 変更", "domains": ["support.google.com"]},
    {"label": "Windowsでストレージセンサーを使って空き容量を増やす", "query": "Windows ストレージ センサー 空き容量 Storage Sense", "domains": ["support.microsoft.com"]},
    {"label": "iPhoneのiCloudバックアップを設定", "query": "iPhone iCloud バックアップ 設定", "domains": ["support.apple.com"]},
    {"label": "Androidで不要なアプリを削除・無効化", "query": "Android アプリ 削除 無効化", "domains": ["support.google.com"]},
    {"label": "Googleフォトのバックアップ設定を確認", "query": "Google フォト バックアップ 設定 確認", "domains": ["support.google.com"]},
    {"label": "OneDriveで削除したファイルを復元", "query": "OneDrive 削除 ファイル 復元 ごみ箱", "domains": ["support.microsoft.com"]},
    {"label": "Chromeの閲覧データを削除", "query": "Chrome 閲覧データ 削除 キャッシュ Cookie", "domains": ["support.google.com"]},
    {"label": "WindowsでBluetooth機器を追加・削除", "query": "Windows Bluetooth デバイス 追加 削除", "domains": ["support.microsoft.com"]},
    {"label": "iPhoneのストレージ使用量を確認・管理", "query": "iPhone ストレージ 容量 確認 管理", "domains": ["support.apple.com"]},
    {"label": "Gmailで送信取り消し時間を設定", "query": "Gmail 送信取り消し 設定", "domains": ["support.google.com"]},

    # 追加: Chrome
    {"label": "Chromeでダウンロード先を変更", "query": "Chrome ダウンロード 保存先 変更", "domains": ["support.google.com"]},
    {"label": "Chromeでポップアップをサイトごとに許可・ブロック", "query": "Chrome ポップアップ サイトごと 許可 ブロック", "domains": ["support.google.com"]},
    {"label": "Chromeの保存済みパスワードを確認・編集・削除", "query": "Chrome 保存済み パスワード 確認 編集 削除 Google Password Manager", "domains": ["support.google.com"]},
    {"label": "Chromeで自動入力の住所や支払い情報を管理", "query": "Chrome 自動入力 住所 支払い情報 管理", "domains": ["support.google.com"]},
    {"label": "Chromeで既定の検索エンジンを変更", "query": "Chrome 既定 検索エンジン 変更", "domains": ["support.google.com"]},
    {"label": "Chromeでホームページと起動時ページを設定", "query": "Chrome 起動時 ページ ホームページ 設定", "domains": ["support.google.com"]},
    {"label": "Chromeで拡張機能を無効化・削除", "query": "Chrome 拡張機能 無効 削除 管理", "domains": ["support.google.com"]},
    {"label": "Chromeで同期するデータを選ぶ", "query": "Chrome 同期 データ 選択 設定", "domains": ["support.google.com"]},
    {"label": "Chromeで言語と翻訳設定を変更", "query": "Chrome 言語 翻訳 設定 変更", "domains": ["support.google.com"]},
    {"label": "Chromeでセーフブラウジング設定を変更", "query": "Chrome セーフブラウジング 設定 変更", "domains": ["support.google.com"]},

    # 追加: Windows
    {"label": "Windowsで通知をアプリごとにオン・オフ", "query": "Windows 通知 アプリごと オフ 設定", "domains": ["support.microsoft.com"]},
    {"label": "Windowsで一時ファイルを削除して空き容量を増やす", "query": "Windows 一時ファイル 削除 空き容量", "domains": ["support.microsoft.com"]},
    {"label": "Windowsで既定のブラウザを変更", "query": "Windows 既定 ブラウザ 変更", "domains": ["support.microsoft.com"]},
    {"label": "WindowsでWi-Fiネットワークを削除して再接続", "query": "Windows Wi-Fi ネットワーク 削除 再接続 忘れる", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでアプリをアンインストール", "query": "Windows アプリ アンインストール 削除", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでディスプレイの拡大縮小と解像度を変更", "query": "Windows 拡大縮小 解像度 変更 ディスプレイ", "domains": ["support.microsoft.com"]},
    {"label": "Windowsで夜間モードを設定", "query": "Windows 夜間モード Night light 設定", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでマイクのアプリ権限を変更", "query": "Windows マイク アプリ 権限 変更", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでカメラのアプリ権限を変更", "query": "Windows カメラ アプリ 権限 変更", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでごみ箱から削除ファイルを復元", "query": "Windows ごみ箱 ファイル 復元", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでクリップボード履歴をオン・オフ", "query": "Windows クリップボード 履歴 設定", "domains": ["support.microsoft.com"]},
    {"label": "Windowsで近距離共有を設定", "query": "Windows 近距離共有 Nearby sharing 設定", "domains": ["support.microsoft.com"]},
    {"label": "Windowsで集中モード・通知の邪魔を減らす", "query": "Windows 集中モード 通知 Focus 設定", "domains": ["support.microsoft.com"]},
    {"label": "Windowsでバックアップからファイルを復元", "query": "Windows バックアップ ファイル 復元 ファイル履歴", "domains": ["support.microsoft.com"]},

    # 追加: iPhone / Apple
    {"label": "iPhoneで不要なアプリを取り除いて容量を空ける", "query": "iPhone Appを取り除く ストレージ 容量", "domains": ["support.apple.com"]},
    {"label": "iPhoneで写真のストレージ使用量を減らす", "query": "iPhone 写真 ストレージ 最適化 iCloud 写真", "domains": ["support.apple.com"]},
    {"label": "iPhoneでアプリごとの通知を変更", "query": "iPhone アプリ 通知 設定 変更", "domains": ["support.apple.com"]},
    {"label": "iPhoneでカメラ・マイクのアプリ権限を変更", "query": "iPhone カメラ マイク アプリ 権限 変更", "domains": ["support.apple.com"]},
    {"label": "iPhoneでモバイルデータ通信をアプリごとに制限", "query": "iPhone モバイルデータ 通信 アプリごと オフ", "domains": ["support.apple.com"]},
    {"label": "iPhoneで集中モードを設定", "query": "iPhone 集中モード 設定", "domains": ["support.apple.com"]},
    {"label": "iPhoneでAirDropの受信設定を変更", "query": "iPhone AirDrop 受信 設定 変更", "domains": ["support.apple.com"]},
    {"label": "iPhoneで削除した写真を復元", "query": "iPhone 削除 写真 復元 最近削除した項目", "domains": ["support.apple.com"]},
    {"label": "iPhoneでSafariのポップアップをブロック", "query": "iPhone Safari ポップアップ ブロック 設定", "domains": ["support.apple.com"]},
    {"label": "iPhoneでSafariのダウンロード先を変更", "query": "iPhone Safari ダウンロード 保存先 変更", "domains": ["support.apple.com"]},
    {"label": "MacをTime Machineでバックアップ", "query": "Mac Time Machine バックアップ 設定", "domains": ["support.apple.com"]},
    {"label": "Macのストレージ容量を確認・最適化", "query": "Mac ストレージ 容量 確認 最適化", "domains": ["support.apple.com"]},
    {"label": "SafariでWebサイトごとの設定を変更", "query": "Safari Webサイト 設定 カメラ マイク 通知", "domains": ["support.apple.com"]},

    # 追加: Android / Google
    {"label": "Androidでアプリごとの通知をオン・オフ", "query": "Android アプリ 通知 オン オフ 設定", "domains": ["support.google.com"]},
    {"label": "Androidでアプリの位置情報権限を変更", "query": "Android 位置情報 アプリ 権限 変更", "domains": ["support.google.com"]},
    {"label": "Androidで不要ファイルを削除して空き容量を増やす", "query": "Android 空き容量 不要ファイル 削除", "domains": ["support.google.com"]},
    {"label": "Androidでバックアップを設定", "query": "Android バックアップ Google 設定", "domains": ["support.google.com"]},
    {"label": "AndroidでWi-Fiネットワークを削除して再接続", "query": "Android Wi-Fi ネットワーク 削除 再接続 忘れる", "domains": ["support.google.com"]},
    {"label": "AndroidでBluetooth機器を接続・削除", "query": "Android Bluetooth デバイス 接続 削除", "domains": ["support.google.com"]},
    {"label": "Androidで既定のアプリを変更", "query": "Android 既定 アプリ 変更", "domains": ["support.google.com"]},
    {"label": "Androidでデータセーバーを設定", "query": "Android データセーバー 設定", "domains": ["support.google.com"]},
    {"label": "Androidでアプリのバックグラウンド通信を制限", "query": "Android アプリ バックグラウンド データ 制限", "domains": ["support.google.com"]},
    {"label": "Androidで画面ロックを設定・変更", "query": "Android 画面ロック 設定 変更", "domains": ["support.google.com"]},

    # Google Photos / Drive / Gmail
    {"label": "Googleフォトでバックアップを一時停止・再開", "query": "Google フォト バックアップ 一時停止 再開", "domains": ["support.google.com"]},
    {"label": "Googleフォトで削除した写真を復元", "query": "Google フォト 削除 写真 復元 ゴミ箱", "domains": ["support.google.com"]},
    {"label": "Googleフォトでバックアップ対象フォルダを選ぶ", "query": "Google フォト デバイス フォルダ バックアップ 選択", "domains": ["support.google.com"]},
    {"label": "Googleドライブでファイルをオフライン利用", "query": "Google Drive オフライン ファイル 利用", "domains": ["support.google.com"]},
    {"label": "Googleドライブで共有相手の権限を変更", "query": "Google Drive 共有 権限 閲覧 編集 変更", "domains": ["support.google.com"]},
    {"label": "Googleドライブでファイルの共有を停止", "query": "Google Drive 共有 停止 ファイル", "domains": ["support.google.com"]},
    {"label": "Gmailで迷惑メールを報告・解除", "query": "Gmail 迷惑メール 報告 解除", "domains": ["support.google.com"]},
    {"label": "Gmailで特定の送信者をブロック・解除", "query": "Gmail 送信者 ブロック 解除", "domains": ["support.google.com"]},
    {"label": "Gmailでメールを自動転送", "query": "Gmail 自動転送 設定", "domains": ["support.google.com"]},
    {"label": "Gmailでラベルを作成して整理", "query": "Gmail ラベル 作成 整理", "domains": ["support.google.com"]},
    {"label": "Gmailで署名を設定", "query": "Gmail 署名 設定", "domains": ["support.google.com"]},
    {"label": "Gmailで不在通知を設定", "query": "Gmail 不在通知 休暇 返信 設定", "domains": ["support.google.com"]},

    # OneDrive / Microsoft
    {"label": "OneDriveの同期を一時停止・再開", "query": "OneDrive 同期 一時停止 再開", "domains": ["support.microsoft.com"]},
    {"label": "OneDriveでフォルダーのバックアップを設定", "query": "OneDrive フォルダー バックアップ デスクトップ ドキュメント 写真", "domains": ["support.microsoft.com"]},
    {"label": "OneDriveでファイルをオンライン専用に戻す", "query": "OneDrive オンライン専用 空き容量を増やす", "domains": ["support.microsoft.com"]},
    {"label": "OneDriveで共有を停止・権限を変更", "query": "OneDrive 共有 停止 権限 変更", "domains": ["support.microsoft.com"]},

    # GitHub
    {"label": "GitHubで2要素認証を設定", "query": "GitHub two factor authentication 2FA setup", "domains": ["docs.github.com"]},
    {"label": "GitHubでSSHキーを追加", "query": "GitHub SSH key add account", "domains": ["docs.github.com"]},
    {"label": "GitHubでブランチ保護ルールを設定", "query": "GitHub protected branch rules setup", "domains": ["docs.github.com"]},
    {"label": "GitHubでリポジトリをアーカイブ・解除", "query": "GitHub archive unarchive repository", "domains": ["docs.github.com"]},
    {"label": "GitHubでIssueを閉じる・再開する", "query": "GitHub close reopen issue", "domains": ["docs.github.com"]},
    {"label": "GitHubで通知設定を変更", "query": "GitHub notifications settings watching repository", "domains": ["docs.github.com"]},

    # ChatGPT / OpenAI
    {"label": "ChatGPTのデータをエクスポート", "query": "ChatGPT export data", "domains": ["help.openai.com"]},
    {"label": "ChatGPTのカスタム指示を設定", "query": "ChatGPT custom instructions settings", "domains": ["help.openai.com"]},
    {"label": "ChatGPTの会話履歴を削除・アーカイブ", "query": "ChatGPT delete archive chats", "domains": ["help.openai.com"]},
    {"label": "ChatGPTでチャット履歴を検索", "query": "ChatGPT search chat history", "domains": ["help.openai.com"]},
    {"label": "ChatGPTで共有リンクを作成・削除", "query": "ChatGPT shared links create delete", "domains": ["help.openai.com"]},
    {"label": "ChatGPTの通知設定を変更", "query": "ChatGPT notifications settings", "domains": ["help.openai.com"]},
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
