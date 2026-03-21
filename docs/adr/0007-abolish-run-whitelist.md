# ADR-0007: run-whitelist を廃止してパイプライン本流に統合する

- **Status**: Accepted
- **Date**: 2026-03-21

## Context

初期実装では2つのジョブが完全に分離していた：

- `run-whitelist`（週次）: e+/Eventernote/AniList/アニメイト → IP名抽出 → whitelist.json
- `run`（日次）: whitelist.json → 公式サイト巡回 → events_processed.json

問題：
- `run-whitelist` は `pipeline.py` から呼ばれておらず未接続の状態だった
- 2つのジョブが分離しているため、イベント収集結果がIP活動性の更新に反映されない（鮮度ループが閉じていない）
- 新しいIPが発見されてから収集対象になるまでのラグが大きい

## Decision

`run-whitelist` を廃止し、単一パイプラインの一ステップとして統合する。

IP発見・登録・活動性スコアリングは `discover_events` → `resolve_ip` → `score_ip_activity` の流れで毎実行時に行われる。

## 却下した案

- **run-whitelist を pipeline.py から呼び出すだけにする**: 根本的な構造（IP起点パイプライン）が変わらないため、ADR-0002の方針と矛盾する。

## Consequences

- `pipeline.py` の `run` コマンドと `run-whitelist` コマンドの両方を廃止し、新しいパイプラインに置き換える
- IPの発見から収集までのラグが短縮される
- systemd timer は1本（または複数の頻度設定）に整理できる
