"""
event_keywords の全ユニークキーワードをClaude Gatewayに渡して
表記ゆれ正規化マッピングを生成し、keyword_alias テーブルに保存する。

Usage:
    python normalize_keywords.py [--db PATH] [--dry-run]
"""
import json
import os
import sqlite3
import argparse
from urllib.request import Request, urlopen

GATEWAY_URL = os.getenv("CLAUDE_GATEWAY_URL", "http://127.0.0.1:18080")
GATEWAY_CALLER = "otakuracy"
MODEL = "claude-haiku-4-5-20251001"

_PROMPT = """\
以下はアニメ・マンガ・ゲーム・VTuber・アイドル等のイベントのツイートから抽出したキーワード一覧です。
同一のIP・作品・キャラクター・アーティストを指す表記ゆれを統合し、代表形（canonical）を決めてください。

ルール:
- 明らかに同一のものだけグループ化する（確信がなければ別々に残す）
- canonicalは最も公式・一般的な表記を選ぶ（例: BanG Dream → BanG Dream!）
- 1キーワードだけのグループ（ゆれなし）は出力不要
- 固有名詞のみ対象（一般語・英数字のみのものは無視）

キーワード一覧:
{keywords}

以下のJSON形式で返してください:
[
  {{"canonical": "BanG Dream!", "aliases": ["BanG Dream", "BanGDream"]}},
  {{"canonical": "スタジオジブリ", "aliases": ["ジブリ", "スタジオジブリ", "ジブリパーク"]}},
  ...
]
表記ゆれが見つからなければ空配列 [] を返してください。
"""


def _call_gateway(keywords: list[str]) -> list[dict]:
    prompt = _PROMPT.format(keywords="\n".join(f"- {k}" for k in keywords))
    payload = {
        "caller": GATEWAY_CALLER,
        "provider": "claude",
        "model": MODEL,
        "prompt": prompt,
        "response_format": "json",
        "execution_mode": "sync",
    }
    req = Request(
        f"{GATEWAY_URL.rstrip('/')}/v1/generate",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("success"):
        raise RuntimeError(f"Gateway error: {result.get('error_message')}")
    output = result["output_text"].strip()
    start = output.find("[")
    end = output.rfind("]") + 1
    if start == -1 or end <= start:
        return []
    return json.loads(output[start:end])


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keyword_alias (
            alias     TEXT PRIMARY KEY,
            canonical TEXT NOT NULL
        )
    """)
    conn.commit()


def normalize_keywords(db_path: str, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    _ensure_table(conn)

    keywords = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT keyword FROM event_keywords ORDER BY keyword"
        ).fetchall()
    ]
    print(f"[normalize] {len(keywords)} unique keywords → Claude Gateway", flush=True)

    groups = _call_gateway(keywords)
    print(f"[normalize] {len(groups)} normalization groups found", flush=True)

    inserted = 0
    for g in groups:
        canonical = g.get("canonical", "").strip()
        aliases = g.get("aliases", [])
        if not canonical or not aliases:
            continue
        for alias in aliases:
            alias = alias.strip()
            if alias == canonical:
                continue
            print(f"  {alias!r:35} → {canonical!r}", flush=True)
            if not dry_run:
                conn.execute(
                    "INSERT OR REPLACE INTO keyword_alias (alias, canonical) VALUES (?, ?)",
                    (alias, canonical),
                )
                inserted += 1

    if not dry_run:
        conn.commit()

    print(f"[normalize] done: {inserted} alias entries saved", flush=True)
    return {"groups": len(groups), "aliases": inserted}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/srv/otakuracy/data/otakuracy.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    normalize_keywords(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
