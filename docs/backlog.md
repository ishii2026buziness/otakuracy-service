# Backlog

優先度: 🔴 高 / 🟡 中 / 🟢 低

---

## データパイプライン

### 🟡 IP汚染: 中国語エントリのフィルタ漏れ
**症状**: 関連IPに `switch缉毒特搜班` 等の中国語コンテンツが表示される  
**原因**:
1. `populate_manami.py` — 日本語title/synonymが皆無なエントリを除外していない
2. `searcher.py` — `instr()` で単語境界なし部分一致のため「スイッチング」→「スイッチ」alias でヒット
3. manami-project が中国アニメ（donghua/manhua）を含むDB

**対処**:
- `populate_manami.py` に `if not any(_is_ja(s) for s in [raw_title] + synonyms): continue` を追加
- 既存DBから日本語ゼロのエントリを削除
- `searcher.py` にエイリアス最短長フィルタ or 単語境界チェックを追加

**暫定**: 関連IPセクションをUIから非表示 → データ汚染がユーザーに見えない状態を維持

---

### 🟢 start_time/end_time の前向きスクレイピング未対応
**症状**: バックフィル（既存データ）は完了済みだが、新規スクレイプ時に `raw_body` から `開演：HH:MM` を parse していない  
**対処**: `repository.py` の `_parse_datetime()` に start_time/end_time 抽出を組み込む

---

## UI / UX

### 🟡 関連IPセクション: 非表示化
**経緯**: 汚染データ + 確度バーが何を意味するか不明 + ユーザーが確度を意識すべきか議論の余地  
**対処**: 信頼度 > 閾値かつ日本語IPのみに絞るか、セクションごと削除

---

### 🟢 モバイル/タッチUI改善
**症状**: hover前提のインタラクションがタッチデバイスで機能しない可能性  
**対処**: カード・タグのインタラクションをタップ対応に見直す

---

### 🟢 イベントステータス体系の整理
**症状**: `status` カラムの値（announced/ongoing/ended）だけでは「チケット発売前」「販売中」「完売」が区別できない  
**対処**: `ticket_status` カラム追加、またはスクレイパーでの状態判定ロジック整理

---

## インフラ

### 🟢 k8s/ingress.yaml を k12-network-notes で管理
**現状**: `otakuracy-run/k8s/ingress.yaml` に保存済みだが、Traefik HelmChartConfig の変更（port 8900追加）はリポジトリ管理外  
**対処**: HelmChartConfig の変更を k12-network-notes に反映
