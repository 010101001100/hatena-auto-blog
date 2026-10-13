import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS


TOPIC_SEEDS = [
    # yt-dlp: 導入・更新・設定・トラブルシューティング
    {"label": "yt-dlpをWindowsにインストールする", "query": "yt-dlp Windows install official github yt-dlp/yt-dlp", "domains": ["github.com"]},
    {"label": "yt-dlpを最新版に更新する", "query": "yt-dlp update latest official github yt-dlp/yt-dlp", "domains": ["github.com"]},
    {"label": "yt-dlpで設定ファイルを使う", "query": "yt-dlp configuration file official github yt-dlp/yt-dlp", "domains": ["github.com"]},
    {"label": "yt-dlpでffmpegが見つからない時の確認方法", "query": "yt-dlp ffmpeg location official github yt-dlp/yt-dlp", "domains": ["github.com"]},
    {"label": "yt-dlpコマンドが見つからない時にPATHを確認する", "query": "yt-dlp command not found PATH Windows official github yt-dlp/yt-dlp", "domains": ["github.com", "learn.microsoft.com"]},

    # FFmpeg
    {"label": "FFmpegをWindowsで使えるようにPATHを設定する", "query": "FFmpeg Windows PATH official documentation", "domains": ["ffmpeg.org", "learn.microsoft.com"]},
    {"label": "ffprobeでメディアファイルの情報を確認する", "query": "ffprobe file information official documentation", "domains": ["ffmpeg.org"]},
    {"label": "FFmpegの基本オプションとコマンド構成を確認する", "query": "ffmpeg command options official documentation", "domains": ["ffmpeg.org"]},
    {"label": "FFmpegのフィルター一覧と使い方を確認する", "query": "ffmpeg filters official documentation", "domains": ["ffmpeg.org"]},

    # Python / pip
    {"label": "WindowsにPythonをインストールして確認する", "query": "Python Windows install official docs", "domains": ["docs.python.org", "python.org"]},
    {"label": "Pythonでvenv仮想環境を作成する", "query": "Python venv create virtual environment official docs", "domains": ["docs.python.org"]},
    {"label": "Pythonのvenvを有効化・終了する", "query": "Python venv activate deactivate official docs", "domains": ["docs.python.org"]},
    {"label": "pipでパッケージをインストール・削除する", "query": "pip install uninstall official documentation", "domains": ["pip.pypa.io"]},
    {"label": "pipでインストール済みパッケージ一覧を確認する", "query": "pip list official documentation", "domains": ["pip.pypa.io"]},
    {"label": "pipでパッケージを更新する", "query": "pip install upgrade package official documentation", "domains": ["pip.pypa.io"]},
    {"label": "requirements.txtからPython環境を再現する", "query": "pip requirements file install official documentation", "domains": ["pip.pypa.io"]},
    {"label": "pip freezeでrequirements.txtを作る", "query": "pip freeze requirements official documentation", "domains": ["pip.pypa.io"]},
    {"label": "pythonコマンドが見つからない時にPATHを確認する", "query": "Python Windows PATH command not found official docs", "domains": ["docs.python.org", "learn.microsoft.com"]},
    {"label": "pipコマンドが見つからない時にpython -m pipを使う", "query": "python -m pip official documentation", "domains": ["pip.pypa.io", "docs.python.org"]},
    {"label": "PythonでHTTPサーバーを一時的に起動する", "query": "Python http.server command line official docs", "domains": ["docs.python.org"]},
    {"label": "PythonでJSONを整形・検証する", "query": "Python json.tool command line official docs", "domains": ["docs.python.org"]},

    # PowerShell / Windows CLI
    {"label": "PowerShellの実行ポリシーを確認する", "query": "PowerShell Get-ExecutionPolicy official docs", "domains": ["learn.microsoft.com"]},
    {"label": "PowerShellの実行ポリシーを変更する", "query": "PowerShell Set-ExecutionPolicy official docs", "domains": ["learn.microsoft.com"]},
    {"label": "PowerShellで環境変数PATHを確認する", "query": "PowerShell environment variables PATH official docs", "domains": ["learn.microsoft.com"]},
    {"label": "Windowsで環境変数PATHを追加する", "query": "Windows environment variables PATH official docs", "domains": ["learn.microsoft.com"]},
    {"label": "PowerShellでファイルやフォルダを検索する", "query": "PowerShell Get-ChildItem recurse filter official docs", "domains": ["learn.microsoft.com"]},
    {"label": "PowerShellでコマンドの場所を確認する", "query": "PowerShell Get-Command executable path official docs", "domains": ["learn.microsoft.com"]},
    {"label": "wingetでアプリを検索・インストールする", "query": "winget search install official docs", "domains": ["learn.microsoft.com"]},
    {"label": "wingetでインストール済みアプリを更新する", "query": "winget upgrade official docs", "domains": ["learn.microsoft.com"]},

    # Git
    {"label": "Gitのユーザー名とメールアドレスを設定する", "query": "git config user.name user.email official docs", "domains": ["git-scm.com"]},
    {"label": "Gitで新しいリポジトリを初期化する", "query": "git init official docs", "domains": ["git-scm.com"]},
    {"label": "Gitで変更内容を確認する", "query": "git status diff official docs", "domains": ["git-scm.com"]},
    {"label": "Gitで直前のコミットメッセージを修正する", "query": "git commit amend official docs", "domains": ["git-scm.com"]},
    {"label": "Gitでブランチを作成して切り替える", "query": "git switch create branch official docs", "domains": ["git-scm.com"]},
    {"label": "Gitでリモートリポジトリを追加・確認する", "query": "git remote add show official docs", "domains": ["git-scm.com"]},
    {"label": "Gitで追跡したくないファイルを.gitignoreに追加する", "query": "gitignore official documentation", "domains": ["git-scm.com"]},
    {"label": "Gitで変更を一時退避する", "query": "git stash official docs", "domains": ["git-scm.com"]},

    # GitHub
    {"label": "GitHubでSSHキーを追加する", "query": "GitHub add SSH key account official docs", "domains": ["docs.github.com"]},
    {"label": "GitHubでSSH接続をテストする", "query": "GitHub test SSH connection official docs", "domains": ["docs.github.com"]},
    {"label": "GitHubでPersonal Access Tokenを作成する", "query": "GitHub fine-grained personal access token create official docs", "domains": ["docs.github.com"]},
    {"label": "GitHubで2要素認証を設定する", "query": "GitHub two-factor authentication setup official docs", "domains": ["docs.github.com"]},
    {"label": "GitHubでブランチ保護ルールを設定する", "query": "GitHub branch protection rule official docs", "domains": ["docs.github.com"]},
    {"label": "GitHub Actionsの手動実行workflow_dispatchを設定する", "query": "GitHub Actions workflow_dispatch official docs", "domains": ["docs.github.com"]},
    {"label": "GitHub ActionsでSecretsを登録する", "query": "GitHub Actions secrets repository official docs", "domains": ["docs.github.com"]},
    {"label": "GitHub Actionsのcronスケジュールを設定する", "query": "GitHub Actions schedule cron official docs", "domains": ["docs.github.com"]},

    # VS Code
    {"label": "VS Codeで統合ターミナルを開いて使う", "query": "VS Code integrated terminal official docs", "domains": ["code.visualstudio.com"]},
    {"label": "VS CodeでPythonインタープリターを選択する", "query": "VS Code Python select interpreter official docs", "domains": ["code.visualstudio.com"]},
    {"label": "VS Codeで既定のターミナルプロファイルを変更する", "query": "VS Code default terminal profile official docs", "domains": ["code.visualstudio.com"]},
    {"label": "VS Codeで設定同期を有効にする", "query": "VS Code settings sync official docs", "domains": ["code.visualstudio.com"]},
    {"label": "VS Codeで拡張機能を無効化・削除する", "query": "VS Code extensions disable uninstall official docs", "domains": ["code.visualstudio.com"]},
    {"label": "VS Codeでワークスペースごとの設定を使う", "query": "VS Code workspace settings official docs", "domains": ["code.visualstudio.com"]},

    # Docker
    {"label": "Docker DesktopをWindowsにインストールする", "query": "Docker Desktop Windows install official docs", "domains": ["docs.docker.com"]},
    {"label": "docker runでコンテナを起動する基本", "query": "docker run official docs", "domains": ["docs.docker.com"]},
    {"label": "docker psでコンテナ一覧を確認する", "query": "docker ps container list official docs", "domains": ["docs.docker.com"]},
    {"label": "docker logsでコンテナログを確認する", "query": "docker logs official docs", "domains": ["docs.docker.com"]},
    {"label": "docker execで起動中コンテナに入る", "query": "docker exec official docs", "domains": ["docs.docker.com"]},
    {"label": "docker compose upとdownの基本", "query": "Docker Compose up down official docs", "domains": ["docs.docker.com"]},
    {"label": "Dockerで不要なコンテナやイメージを整理する", "query": "docker system prune remove unused official docs", "domains": ["docs.docker.com"]},
]


UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)


def direct_official_urls(query: str, domains: list[str]) -> list[str]:
    """検索エンジンが0件でも辿れる、安定した公式ドキュメントURLを返す。"""
    q = query.lower()
    urls = []

    if "github.com" in domains and "yt-dlp" in q:
        urls = [
            "https://github.com/yt-dlp/yt-dlp/blob/master/README.md",
            "https://github.com/yt-dlp/yt-dlp/wiki/Installation",
            "https://github.com/yt-dlp/yt-dlp/releases/latest",
        ]

    elif "ffmpeg.org" in domains:
        if "ffprobe" in q:
            urls = [
                "https://ffmpeg.org/ffprobe.html",
                "https://ffmpeg.org/ffmpeg-all.html",
            ]
        elif "filter" in q:
            urls = [
                "https://ffmpeg.org/ffmpeg-filters.html",
                "https://ffmpeg.org/ffmpeg.html",
            ]
        else:
            urls = [
                "https://ffmpeg.org/ffmpeg.html",
                "https://ffmpeg.org/ffmpeg-all.html",
            ]

    elif "pip.pypa.io" in domains:
        if "freeze" in q:
            urls = [
                "https://pip.pypa.io/en/stable/cli/pip_freeze/",
                "https://pip.pypa.io/en/stable/user_guide/",
            ]
        elif "requirements" in q:
            urls = [
                "https://pip.pypa.io/en/stable/user_guide/",
                "https://pip.pypa.io/en/stable/reference/requirements-file-format/",
            ]
        elif "uninstall" in q:
            urls = [
                "https://pip.pypa.io/en/stable/cli/pip_install/",
                "https://pip.pypa.io/en/stable/cli/pip_uninstall/",
            ]
        elif "list" in q:
            urls = [
                "https://pip.pypa.io/en/stable/cli/pip_list/",
                "https://pip.pypa.io/en/stable/user_guide/",
            ]
        else:
            urls = [
                "https://pip.pypa.io/en/stable/cli/pip_install/",
                "https://pip.pypa.io/en/stable/user_guide/",
            ]

    elif "docs.python.org" in domains or "python.org" in domains:
        if "venv" in q:
            urls = [
                "https://docs.python.org/3/library/venv.html",
                "https://docs.python.org/3/tutorial/venv.html",
            ]
        elif "http.server" in q:
            urls = [
                "https://docs.python.org/3/library/http.server.html",
                "https://docs.python.org/3/using/cmdline.html",
            ]
        elif "json.tool" in q:
            urls = [
                "https://docs.python.org/3/library/json.html",
                "https://docs.python.org/3/using/cmdline.html",
            ]
        else:
            urls = [
                "https://docs.python.org/3/using/windows.html",
                "https://docs.python.org/3/using/cmdline.html",
                "https://www.python.org/downloads/windows/",
            ]

    elif "learn.microsoft.com" in domains:
        if "executionpolicy" in q or "execution policy" in q:
            urls = [
                "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-executionpolicy",
                "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/set-executionpolicy",
                "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies",
            ]
        elif "get-childitem" in q:
            urls = [
                "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-childitem",
                "https://learn.microsoft.com/en-us/powershell/scripting/samples/working-with-files-and-folders",
            ]
        elif "get-command" in q:
            urls = [
                "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/get-command",
                "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_command_precedence",
            ]
        elif "winget" in q and "upgrade" in q:
            urls = [
                "https://learn.microsoft.com/en-us/windows/package-manager/winget/upgrade",
                "https://learn.microsoft.com/en-us/windows/package-manager/winget/",
            ]
        elif "winget" in q:
            urls = [
                "https://learn.microsoft.com/en-us/windows/package-manager/winget/search",
                "https://learn.microsoft.com/en-us/windows/package-manager/winget/install",
            ]
        else:
            urls = [
                "https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_environment_variables",
                "https://learn.microsoft.com/en-us/windows/win32/procthread/environment-variables",
            ]

    elif "git-scm.com" in domains:
        if "init" in q:
            pages = ["git-init", "git"]
        elif "status" in q or "diff" in q:
            pages = ["git-status", "git-diff"]
        elif "amend" in q:
            pages = ["git-commit", "git-rebase"]
        elif "switch" in q or "branch" in q:
            pages = ["git-switch", "git-branch"]
        elif "remote" in q:
            pages = ["git-remote", "git-fetch"]
        elif "gitignore" in q:
            pages = ["gitignore", "git-status"]
        elif "stash" in q:
            pages = ["git-stash", "git-status"]
        else:
            pages = ["git-config", "git"]
        urls = [f"https://git-scm.com/docs/{page}" for page in pages]

    elif "docs.github.com" in domains:
        if "ssh" in q:
            urls = [
                "https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account",
                "https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection",
            ]
        elif "token" in q:
            urls = [
                "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
                "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github",
            ]
        elif "two-factor" in q or "2fa" in q:
            urls = [
                "https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/configuring-two-factor-authentication",
                "https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/accessing-github-using-two-factor-authentication",
            ]
        elif "branch protection" in q:
            urls = [
                "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches",
                "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule",
            ]
        elif "secret" in q:
            urls = [
                "https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets",
                "https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax",
            ]
        elif "workflow_dispatch" in q or "cron" in q or "schedule" in q:
            urls = [
                "https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax",
                "https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow",
            ]

    elif "code.visualstudio.com" in domains:
        if "python" in q:
            urls = [
                "https://code.visualstudio.com/docs/python/environments",
                "https://code.visualstudio.com/docs/python/python-tutorial",
            ]
        elif "settings sync" in q:
            urls = [
                "https://code.visualstudio.com/docs/configure/settings-sync",
                "https://code.visualstudio.com/docs/configure/settings",
            ]
        elif "extension" in q:
            urls = [
                "https://code.visualstudio.com/docs/configure/extensions/extension-marketplace",
                "https://code.visualstudio.com/docs/configure/settings",
            ]
        elif "workspace" in q:
            urls = [
                "https://code.visualstudio.com/docs/configure/settings",
                "https://code.visualstudio.com/docs/editing/workspaces/workspaces",
            ]
        else:
            urls = [
                "https://code.visualstudio.com/docs/terminal/basics",
                "https://code.visualstudio.com/docs/terminal/profiles",
            ]

    elif "docs.docker.com" in domains:
        if "desktop" in q and "windows" in q:
            urls = [
                "https://docs.docker.com/desktop/setup/install/windows-install/",
                "https://docs.docker.com/desktop/setup/install/",
            ]
        elif " logs" in " " + q:
            urls = [
                "https://docs.docker.com/reference/cli/docker/container/logs/",
                "https://docs.docker.com/reference/cli/docker/container/",
            ]
        elif " exec" in " " + q:
            urls = [
                "https://docs.docker.com/reference/cli/docker/container/exec/",
                "https://docs.docker.com/reference/cli/docker/container/",
            ]
        elif "compose" in q:
            urls = [
                "https://docs.docker.com/reference/cli/docker/compose/up/",
                "https://docs.docker.com/reference/cli/docker/compose/down/",
            ]
        elif "prune" in q:
            urls = [
                "https://docs.docker.com/reference/cli/docker/system/prune/",
                "https://docs.docker.com/reference/cli/docker/system/",
            ]
        elif " ps" in " " + q:
            urls = [
                "https://docs.docker.com/reference/cli/docker/container/ls/",
                "https://docs.docker.com/reference/cli/docker/container/",
            ]
        else:
            urls = [
                "https://docs.docker.com/reference/cli/docker/container/run/",
                "https://docs.docker.com/reference/cli/docker/container/",
            ]

    return [u for u in urls if is_official_url(u, domains)]


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

    # 検索エンジンが0件/少数でも、既知の公式URLを直接取得して補う。
    if len(candidates) < max_sources:
        direct_urls = direct_official_urls(query, domains)
        if direct_urls:
            print(
                f"INFO: 公式検索候補が{len(candidates)}件のため"
                f" 既知の公式URLを{len(direct_urls)}件補完"
            )
        for url in direct_urls:
            if url in seen:
                continue
            seen.add(url)
            candidates.append(
                {
                    "title": url,
                    "url": url,
                    "snippet": "",
                    "domain": (urlparse(url).hostname or "").lower(),
                }
            )

    sources = []
    for item in candidates[:10]:
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
