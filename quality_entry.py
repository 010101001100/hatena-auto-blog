import json
import sys

import quality_runner as runner

q = runner.q
_base_write = q.write_article
_base_critique = q.critique


def retry_write(api_key, model, theme, memo, sources, titles, revision=""):
    last = None
    for attempt in range(2):
        try:
            extra = revision
            if attempt:
                extra = (
                    revision
                    + "\n\n前回は出力JSONが壊れました。本文の品質は維持しつつ、"
                    + "JSON文字列を正しくエスケープし、JSONオブジェクト以外を出力しないでください。"
                )
            return _base_write(api_key, model, theme, memo, sources, titles, extra)
        except (json.JSONDecodeError, ValueError) as e:
            last = e
            print(f"WARNING: 記事JSONの解析に失敗。再生成します: {e}")
    raise last


def retry_critique(api_key, model, article, memo, sources, titles):
    last = None
    for attempt in range(2):
        try:
            return _base_critique(api_key, model, article, memo, sources, titles)
        except (json.JSONDecodeError, ValueError) as e:
            last = e
            print(f"WARNING: 品質判定JSONの解析に失敗。再判定します: {e}")
    raise last


q.write_article = retry_write
q.critique = retry_critique

if __name__ == "__main__":
    try:
        raise SystemExit(q.main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
