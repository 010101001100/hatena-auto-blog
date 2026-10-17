"""実用記事を読者目線で検査する、API呼び出し不要の追加品質ゲート。

LLM採点を信頼し切らず、公開後の実用性評価で発覚した具体的な
問題をテーマ別に検出する。万能な事実検証を自称しない。
"""

import re


def _has(text, pattern):
    return bool(re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE))


def editorial_checks(article, memo):
    """公開前に見つけられる誤解・事故・実用性不足を返す。"""
    title = article.get("title") or ""
    body = article.get("body") or ""
    context = " ".join([
        title,
        str(memo.get("topic") or ""),
        str(memo.get("working_title") or ""),
    ])
    issues = []

    # 「ffmpegで変換する」記事に限って適用。ffprobeやコマンド導入記事は対象外。
    ffmpeg_conversion = (
        _has(context, r"\bffmpeg\b")
        and _has(context, r"変換|再エンコード|エンコード|動画形式")
    )
    if ffmpeg_conversion:
        # FFmpeg公式の64 kbit/sの構文例は一般的な高画質設定の推奨ではない。
        if _has(body, r"-b:v\s+64k\b") and not (
            _has(body, r"画質")
            and _has(body, r"低い|低下|粗く|劣化|悪く|厳し|用途に合|"
                      r"実用には向か|テスト用|構文例|例示用|低ビットレート")
        ):
            issues.append(
                "映像ビットレート64kを使う場合、低画質になり得る点と"
                "用途依存の設定例であることを明記する"
            )

        # -y の強制上書き、-n の上書き防止、別名保存のどれかを説明する。
        if _has(body, r"\bffmpeg\s+.*(?:-i\s+)"):
            if not _has(body, r"上書き|既存ファイル"):
                issues.append(
                    "変換先に既存ファイルがある場合の上書きリスクを説明する"
                )
            if not _has(body, r"(?<!\w)-n\b|(?<!\w)-y\b|別名|別の名前|異なる名前|"
                              r"異なるファイル名|出力先を変"):
                issues.append(
                    "上書きを避けるための -n または別名保存、"
                    "強制上書き -y の意味と注意点を示す"
                )

        if not (
            _has(body, r"ffprobe")
            or _has(body, r"再生.{0,24}(?:確認|チェック)|"
                          r"(?:確認|チェック).{0,24}再生")
            or (_has(body, r"変換後|出力ファイル|生成されたファイル")
                and _has(body, r"確認|再生|チェック"))
        ):
            issues.append(
                "変換後のファイルを再生またはffprobe等で確認する手順がない"
            )

        # 公式マニュアルの典型例を転載しただけで終わる記事を避ける。
        commands = re.findall(r"(?mi)^\s*(?:[$>]\s*)?(ffmpeg\s+-i\s+[^\n]+)$", body)
        manual = {
            "ffmpeg -i input.avi output.mp4",
            "ffmpeg -i input.avi -b:v 64k -bufsize 64k output.mp4",
            "ffmpeg -i input.avi -r 24 output.mp4",
        }
        if commands and all(
            " ".join(command.split()) in manual for command in commands
        ):
            issues.append(
                "ffmpeg公式マニュアルのサンプルだけでなく、"
                "読者の用途に合わせたオリジナルの入力・出力例を1つ加える"
            )

    docker_windows = (
        _has(context, r"docker(?:\s+desktop)?")
        and _has(context + "\n" + body, r"windows")
    )
    if docker_windows:
        # Dockerの技術要件だけで古いOSを推奨してしまわないようにする。
        if _has(body, r"Windows\s*10\b"):
            if not (
                _has(body, r"2025\s*年\s*10\s*月\s*14\s*日|2025[-/]10[-/]14")
                and _has(body, r"サポート終了|サポートが終了|通常サポート終了")
            ):
                issues.append(
                    "Docker記事でWindows 10を扱うなら、"
                    "通常版のサポート終了日（2025年10月14日）を明記する"
                )

        # 「要件を確認する」ことがゴールの記事では、確認経路が必要。
        checklist_goal = _has(context, r"要件|動作条件|事前チェック|システム条件")
        if checklist_goal and _has(body, r"\b8\s*GB\b|メモリ容量|RAM容量"):
            if not _has(
                body,
                r"タスク\s*マネージャ|msinfo32|Get-CimInstance|"
                r"設定\s*(?:→|>|＞).{0,40}バージョン情報|"
                r"システム情報.{0,20}メモリ|物理メモリ.{0,20}確認",
            ):
                issues.append(
                    "Dockerの必要メモリを述べるなら、Windows上で"
                    "搭載メモリを確認する画面経路かコマンドを示す"
                )
        if checklist_goal and _has(body, r"BIOS|UEFI|仮想化|virtualization"):
            if not _has(
                body,
                r"タスク\s*マネージャ|systeminfo|"
                r"Get-CimInstance\s+Win32_Processor|"
                r"CPU.{0,25}仮想化.{0,20}確認|"
                r"仮想化.{0,25}CPU.{0,20}確認",
            ):
                issues.append(
                    "Dockerの仮想化要件を述べるなら、"
                    "BIOSを変更する前に状態を確認する手順を示す"
                )

    return issues
