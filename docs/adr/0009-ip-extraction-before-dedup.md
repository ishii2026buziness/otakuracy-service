# ADR-0009: IP抽出をdedupより前に実行し、AI（Haiku）を使う

- **Status**: Accepted
- **Date**: 2026-03-21

## Context

ADR-0008 でイベント同一性判定のキーを「日付 + 会場 + IP」とした。
しかしイベントのIPは収集時点では不明であり、タイトルから抽出する必要がある。

現在の pipeline_v2 の順序：
```
discover → dedup（日付+会場） → persist
```

これには2つの問題がある：
1. dedup に IP が使えない（抽出していないため）→ 同日・同会場の別IP イベントを誤って同一視する
2. IP識別なしに persist しても event_ip_link が空になり、サービスの根幹（IP別イベント一覧）が成立しない

IP抽出の手段として以下を検討した：

- **文字列マッチ（ip_registry との照合）**: ip_registry が空の段階では機能しない。また表記ゆれ（「推しの子」vs「Oshi no Ko」vs「ぼざろ」）に対応できない
- **ルールベース（正規表現）**: イベントタイトルの構造はソースによって異なり、汎用ルールの作成・保守コストが高い
- **AI（LLM）**: タイトルの構造に依存せずIP名を抽出できる。バッチ化・キャッシュで低コスト化可能

## Decision

パイプラインの順序を以下に変更する：

```
discover
  → extract_ip（AI + 文字列マッチ）
  → resolve_ip（ip_registry に照合・candidate 登録）
  → dedup（日付 + 会場 + ip_id）
  → persist
```

### IP抽出の実装方針

```
1. ip_registry に既存エントリがあれば文字列マッチ（コスト0）
2. マッチしなかったものを Haiku でバッチ抽出（20件/リクエスト）
3. 抽出結果を ip_registry に candidate として upsert してキャッシュ
4. 抽出された ip_id を event レコードに紐づけて dedup のキーに使う
```

### モデル選択

- **Haiku**（claude-haiku-4-5）を使う
- IP名の抽出は分類タスクであり、高度な推論は不要
- バッチ化（20件まとめて1リクエスト）でコストを抑える
- 同じタイトルパターンはキャッシュで再利用

### IP が特定できない場合の扱い

- AI が「不明」と返した場合は ip_id = NULL のまま persist
- IP不明イベントはサービス表示対象外（後でバッチ再処理可能）
- `source_confidence` を下げてフラグとして使う

## 却下した案

- **ルールベース抽出**: 保守コストが高く、新IPへの対応が遅れる
- **dedup後にIP抽出**: dedup のキーに IP が使えず、ADR-0008 の方針と矛盾する
- **GPT-4o 等の高性能モデル**: 分類タスクに対してオーバースペック。コスト増

## Consequences

- pipeline_v2 の dedup ステージより前に `extract_ip` → `resolve_ip` ステージを挿入する（KEN-83 を修正）
- ANTHROPIC_API_KEY が pipeline の実行に必須になる
- ip_registry が育つほど文字列マッチの割合が増え AI コストが下がる
- IP不明イベントが一定数発生する（初期は特に多い）。この比率をモニタリング指標にする
