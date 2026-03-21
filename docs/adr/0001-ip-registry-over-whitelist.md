# ADR-0001: whitelist.json を廃止して ip_registry に置き換える

- **Status**: Accepted
- **Date**: 2026-03-21

## Context

初期実装では `whitelist.json` にIPを登録してイベント収集対象を管理していた。
フラットな辞書構造で、`ip_name` / `first_seen` / `source_titles` / `official_url` のみ保持。

以下の問題があった：
- 一度登録されたIPが永遠に残る（削除ロジックなし）
- 「アクティブなIPのみ追う」という方針がコードに反映されておらず、運用メモ止まり
- AniList（人気順）・アニメイト（商品売上）由来のIPが混入し、イベント活動とは無関係なIPが増殖する
- なぜそのIPが登録されているか追跡できない

## Decision

`whitelist.json` を廃止し、状態遷移を持つ `ip_registry` テーブル（SQLite）に置き換える。

状態: `candidate` → `active` → `cooling` → `inactive` / `blocked`

アクティブ判定ルール：
- 直近90日でイベント2件以上 → `active`
- 直近30日で高信頼イベント1件 → `active`
- 91〜180日更新なし → `cooling`
- 180日超更新なし → `inactive`

追加フィールド: `activation_score`, `last_event_seen_at`, `aliases`, `domain_tags`

## 却下した案

- **whitelist に is_active フラグを追加する**: 状態遷移が増えるにつれ管理が煩雑になる。JSONファイルでは検索・集計もできない。

## Consequences

- アクティブ判定が自動化され、非アクティブIPが自然に除外される
- 収集コストが下がる（inactive IPを高頻度で回さなくて済む）
- whitelist.json からのマイグレーションスクリプトが必要
- SQLite 依存が追加される
