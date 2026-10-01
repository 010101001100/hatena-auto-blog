# はてなブログ 自動記事生成＆自動投稿

GitHub Actionsで定期実行し、OpenAI APIで日本語記事を生成して、はてなブログAtomPub APIへ投稿します。

## できること
- 毎日 08:17（Asia/Tokyo）に自動実行
- 直近7記事のタイトルを取得して重複ネタを避ける
- 実用系のエバーグリーン記事を生成
- はてなブログへ下書きまたは公開投稿
- Actions画面から手動実行

## 必須 Secrets
Settings → Secrets and variables → Actions → Secrets に登録:
- OPENAI_API_KEY
- HATENA_ID
- HATENA_BLOG_ID
- HATENA_API_KEY

## 任意 Variables
同じ画面の Variables に登録できます:
- BLOG_THEME
- OPENAI_MODEL（未指定時 gpt-5.4-mini）
- BLOG_SYNTAX（markdown / hatena / plain）
- BLOG_CATEGORIES（例: 生活,便利）
- HATENA_DRAFT（true=下書き、false=公開。未指定時はtrue）
- DRY_RUN（true=生成だけで投稿しない）

最初は HATENA_DRAFT=true のまま手動実行して、生成内容を確認してください。

## テスト
GitHubの Actions → Hatena Auto Blog → Run workflow から実行できます。
