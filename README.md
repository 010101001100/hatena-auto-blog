# はてなブログ 高品質自動投稿

GitHub Actionsで1日2回、**テーマ選定 → Google検索で調査 → 執筆 → 編集チェック → はてなブログ公開**まで自動化します。

## 現在の構成

- 実行: 毎日 08:17 / 20:17（Asia/Tokyo）
- 標準モデル: Gemini 3.8 Flash
- 調査時はGoogle検索グラウンディング必須
- 検索ソースが2件未満なら、その回は投稿しない
- 直近最大50記事と比較して重複テーマを抑制
- 記事は2200〜3600字を目安
- 参考情報セクションと参照リンク2件以上を必須化
- 編集AIが6項目を採点し、全項目4/5以上だけ公開
- 不合格なら最大3回まで全文を書き直す
- 3回とも不合格なら投稿しない
- コード変更時のGitHub ActionsはDRY RUNなので実投稿しない

## 標準ジャンル

BLOG_THEME未設定時は以下に絞ります。

- PC設定・トラブル解決
- スマホ設定・データ整理
- Webサービス・AIツール活用
- バックアップ・ファイル管理
- 個人の作業効率化

医療・法律・投資・税務・危険作業、副業一般論、芸能・雑記は自動記事の対象外です。

## 品質チェック

公開前に以下を確認します。

1. 検索意図との一致
2. 具体性・再現性
3. 調査根拠との整合性
4. 構成・読みやすさ
5. 実用性
6. 過去記事との差別化

機械チェックでは、本文長、見出し数、手順/箇条書き、AI定型句、既存タイトル類似度、参考リンク数も検査します。

**品質より投稿本数を優先しません。**
検索が失敗したり、根拠が薄かったり、QAに落ちた日は投稿なしになります。

## 必須 Secrets

GitHubの Settings → Secrets and variables → Actions → Secrets に登録:

- GEMINI_API_KEY
- HATENA_ID
- HATENA_BLOG_ID
- HATENA_API_KEY

以前の設定でGemini APIキーを OPENAI_API_KEY という名前に保存している場合も、互換性のためそのまま動きます。
新しく整理する場合は GEMINI_API_KEY を推奨します。

## 任意 Variables

- BLOG_THEME — ブログの方向性を上書き

## ファイル

- quality_v2.py — 調査・執筆・品質判定・はてな投稿の本体
- quality_runner.py — 検索必須化、モデルフォールバック、追加品質ガード
- quality_entry.py — JSON崩れ時の再試行
- .github/workflows/auto-post.yml — 1日2回の実行設定
- main.py — 旧バージョン（現在は実行されません）

## 投稿を止める

Actions → Hatena Auto Blog → Disable workflow で停止できます。

GitHub Actionsのscheduled workflowは、GitHub側の混雑で開始時刻が遅れる場合があります。
