# ADR-0011: 正規IP空間のソース選定

- **Date**: 2026-03-21
- **Status**: Accepted

## Context

ADR-0010で正規IP空間の概念を定義した。本ADRでは「どのソースを正規IP空間のベースとして採用するか」をジャンル別に決定する。

権威ソースが満たすべき性質:

- **安定したID**: 同一エントリが常に同じIDで参照できる
- **正規名称**: 表記ゆれの「正解」として使える公式名が取れる
- **機械可読API**: プログラムから照合・取得できる
- **コミュニティ認知**: そのジャンルで「ここが正しい」という共通認識がある

## Decision

### 採用ソース

| ジャンル | 権威ソース | 正規ID | 正規名 |
|----------|------------|--------|--------|
| アニメ/マンガ | AniList | `media.id` | `title.native` |
| VTuber | Holodex | `channel.id` (= YouTube channel ID) | `channel.name` |

### ゲームの除外

ゲームジャンルはイベント数が限定的なため、正規空間の対象外とする。将来的にゲーム関連イベントの観測が増えた場合に別途ADRで対応する。

## Rationale

### AniList（アニメ/マンガ）

- GraphQL APIで `media.id`（整数）と `title.native`（日本語原題）が取得可能
- IDは削除・変更されにくく安定している
- `title.native` は原語タイトルを返すため、日本作品であれば日本語名が得られる
- AniListはアニメ・マンガを同一 `Media` エンティティで管理しており、単一の正規空間として扱える

### Holodex（VTuber）

- `channel.id` はYouTube channel IDと同一であり、Googleが管理する永続的なID
- VTuber専門の集約サービスとしてコミュニティ認知が高い
- channel IDベースのため、Holodexが廃止されてもYouTube側でIDは有効

## Consequences

- ip_registryの `canonical_source` フィールドは `"anilist"` または `"holodex"` を値として持つ
- ip_registryの `canonical_id` フィールドはそれぞれの正規IDを格納する
- 写像（Haiku）はイベント処理時にオンデマンドでAniList/Holodex APIを参照して正規IDを解決する
- ゲーム・その他ジャンルのIPはイベントで観測されても正規IDなしで登録される（`canonical_source = null`）
