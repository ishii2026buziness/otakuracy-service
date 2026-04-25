---
name: otakuracy-analysis
description: otakuracyのIP同定分析（キーワード抽出状況確認・正規化・グラフクラスタリング）を実行する。ツイートコーパスからIPクラスタを分析したいときに使う。
---

# Otakuracy IP Analysis

otakuracy-service の tweet corpus を使ったIP同定分析を実行するスキル。

## 環境情報

- **K12リポジトリ**: `/home/kento/otakuracy-run`
- **DB**: `/srv/otakuracy/data/otakuracy.db`
- **G3リポジトリ**: `~/repos/github.com/ishii2025buziness/otakuracy-service`
- **PYTHONPATH**: `app/src:/common/src`
- **venv**: `.venv/bin/python`

## 分析の実行手順

### 1. データ状況確認

```bash
ssh k12 "cd /home/kento/otakuracy-run && PYTHONPATH=app/src:/common/src .venv/bin/python -c \"
import sqlite3
conn = sqlite3.connect('/srv/otakuracy/data/otakuracy.db')
events = conn.execute('SELECT COUNT(DISTINCT event_id) FROM event_keywords').fetchone()[0]
kws = conn.execute('SELECT COUNT(*) FROM event_keywords').fetchone()[0]
aliases = conn.execute('SELECT COUNT(*) FROM keyword_alias').fetchone()[0]
print(f'events: {events}, keywords: {kws}, aliases: {aliases}')
\""
```

### 2. 最新コードをK12に反映

```bash
# G3でpush済みであること前提
ssh k12 "cd /home/kento/otakuracy-run && git pull origin master -q"
```

### 3. キーワード未抽出イベントがある場合は抽出

```bash
ssh k12 "cd /home/kento/otakuracy-run && nohup PYTHONPATH=app/src:/common/src .venv/bin/python -c \"
import sqlite3
from collect.tweet_corpus.keyword_extractor import extract_keywords
conn = sqlite3.connect('/srv/otakuracy/data/otakuracy.db')
conn.row_factory = sqlite3.Row
result = extract_keywords(conn, limit=500)
print('[done]', result)
\" > /tmp/keyword_extract.log 2>&1 &
echo PID:\$!"
```

### 4. 表記ゆれ正規化（新キーワードが増えた場合）

```bash
ssh k12 "cd /home/kento/otakuracy-run && PYTHONPATH=app/src:/common/src .venv/bin/python app/src/normalize_keywords.py"
```

### 5. グラフクラスタリング分析（標準パラメータ）

```bash
ssh k12 "cd /home/kento/otakuracy-run && PYTHONPATH=app/src:/common/src .venv/bin/python app/src/ip_keyword_analysis.py --method graph --min-tf 0.1"
```

全手法を見たい場合:

```bash
ssh k12 "cd /home/kento/otakuracy-run && PYTHONPATH=app/src:/common/src .venv/bin/python app/src/ip_keyword_analysis.py --method all --min-tf 0.1"
```

## 標準パラメータ

| パラメータ | 標準値 | 意味 |
|---|---|---|
| `--min-tf` | `0.1` | TFがこれ未満のキーワードを除外（声優・アーティスト経由のノイズ抑制） |
| `--threshold` | `0.3` | グラフクラスタリングのコサイン類似度閾値 |
| `--method` | `graph` | 分析手法（graph推奨） |

## 設計ノート

- **keyword_alias**: 表記ゆれ正規化マッピング。`normalize_keywords.py` で生成
- **ジブリパーク vs スタジオジブリ**: 意図的に別クラスタ扱い（IPとして別物）
- **weight (TF)**: ツイート出現率。再計算する場合はAPI再呼び出し不要、ローカルで UPDATE できる
- 詳細設計: `docs/adr/0013-twitter-corpus-for-ip-identification.md`
