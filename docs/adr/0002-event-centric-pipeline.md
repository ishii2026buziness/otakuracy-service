# ADR-0002: IP起点からイベント起点のパイプラインに転換する

- **Status**: Accepted
- **Date**: 2026-03-21

## Context

初期実装のパイプラインは「IP台帳（whitelist）→ 各IPの公式サイトを巡回 → イベント抽出」というIP起点の構造だった。

問題：
- 公式サイトを持たない・更新していないIPのイベントが取れない
- e+ / Eventernote はイベントデータ（日時・会場・販売状態）を保有しているにもかかわらず、ホワイトリスト用途（IP名の発見）にしか使っていなかった
- 新しいIPの発見がホワイトリスト更新タイミングに依存し、速報性がなかった

## Decision

「チケット・イベントサイトからイベント候補を大量取得 → IPを特定・登録 → 必要に応じて公式サイトで補完」というイベント起点に転換する。

パイプライン：
```
discover_events（e+/Eventernote等から一括取得）
→ extract_entities（IP・会場・価格・日付を抽出）
→ resolve_ip（ip_registryに照合、新規はcandidate登録）
→ score_ip_activity（活動性スコア更新）
→ refresh_official（active IPのみ公式サイトを補完確認）
→ merge_events（cross-source dedup）
→ publish（DB更新）
```

ソース役割分担：
- Tier 1（プライマリ）: e+, Eventernote
- Tier 2（補助）: 公式サイト（active IPのみ）
- Tier 3（IP発見のみ）: AniList, アニメイト

## 却下した案

- **公式サイト巡回をメインのまま維持**: IPごとにサイト構造が異なり高コスト・高ノイズ。料金や販売状態はチケットサイトの方が構造化されている。

## Consequences

- e+ / Eventernote のスクレイパーをイベント収集のプライマリとして再実装が必要
- 公式サイト巡回（Playwright + claude -p）のコストが大幅に下がる
- カテゴリによってプライマリソースが異なる（live→チケット系, popup/cafe→公式サイト）
