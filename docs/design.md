# otakuracy 設計書

> 最終更新: 2026-03-21
> 関連文書: [docs/sources.md](sources.md) — ソースカタログ & 評価設計

---

## サービス概要

アニメ・マンガ・VTuber・ゲームのIPに関連するリアル/オンラインイベントを自動収集・キュレーションするサービス。
収集したデータを無料公開しつつ、パーソナライズ・通知・APIアクセスで課金につなげる。

---

## マネタイズ設計

```
Free      イベント一覧閲覧（日時・場所・内容）
            ↓
Premium   パーソナライズ・高度検索・レコメンド・通知アラート（サブスク）
            ↓
API       データ提供・従量課金（B2B・開発者向け）
```

### Free
- イベント一覧（日時・場所・内容・カテゴリ）の閲覧
- 基本的なカテゴリ/エリアフィルタ

### Premium（サブスク）
- お気に入りIP無制限登録
- IP × エリア × カテゴリ複合の通知アラート
- 販売開始・抽選締切の先行通知
- パーソナルフィード・レコメンド
- 高度な検索・絞り込み（価格帯・販売状態等）

### API（従量課金）
- イベントデータのAPI提供（APIキー認証）
- 使用量メータリング
- データ品質が上がるほど単価を上げられる構造

---

## 収集方針

### ドメイン優先度
1. **アニメ・マンガ**（主力）
2. VTuber（サブ、最低限ホロライブ・にじさんじ）
3. ゲーム（後回し）

### 地理・形態
- 日本国内リアルイベント + オンライン配信イベント
- 将来的な海外展開は設計上考慮しておく（area_code 等）

### アクティブIP方針
**「現在イベントが存在するIPだけを追う」を システム制約としてコードに落とす。**

whitelist.json は廃止し、状態を持つ `ip_registry` に移行する。

---

## ドメインモデル

### ip_registry
IPの台帳。状態遷移で活動性を管理する。

```
ip_id, display_name, official_url
status: candidate → active → cooling → inactive → blocked
activation_score       # イベント頻度・ソース多様性等から計算
last_event_seen_at
last_verified_at
sources                # どのソースから発見されたか
aliases                # 表記ゆれ辞書
domain_tags            # anime / manga / vtuber / game
```

**アクティブ判定ルール（案）:**
- 直近90日でイベント2件以上 → `active`
- 直近30日で高信頼イベント1件 → `active`
- 91〜180日更新なし → `cooling`
- 180日超更新なし → `inactive`
- 手動 override 可

### event
ユーザーに見せる正規化イベント。

```
event_id, title, summary
category: popup_store / collab_cafe / live / exhibition / stage / campaign / online
status: announced → onsale → sold_out → ended / cancelled
start_at, end_at, tz
venue_id, area_code, is_online
official_url, primary_ticket_url
hero_image_url
price_min, price_max, currency
ticketing_type: lottery / first_come / free / unknown
source_confidence
first_seen_at, last_seen_at
```

### event_source_record
各ソースから見えた生データ。dedup・再処理のために生を保存。

```
source_record_id, source_type, source_url, fetched_at
raw_title, raw_body, raw_price_text, raw_venue_text, raw_date_text
parser_confidence, parse_version
event_id  # 正規化後に紐づく
```

### event_ip_link
イベントとIPの関係（confidence付き）。

```
event_id, ip_id
relation_type: primary / featured / cast_related / brand_related
confidence
```

### price_offer
価格情報（席種・時期別に複数持てる）。

```
event_id, label, price, currency
sales_start_at, sales_end_at, availability
source_url
```

### venue
```
venue_id, name, prefecture, area_code, lat, lng
```

### user_follow / alert_rule（Premium機能）
```
user_id → ip_id（フォロー）
user_id, ip_id, area_code, category, alert_type（アラートルール）
```

---

## ソース役割分担

| Tier | ソース | 役割 |
|---|---|---|
| **1 プライマリ** | e+、Eventernote | イベントの大量取得・価格/会場/販売状態の主取得・IPアクティブ判定のシグナル |
| **2 補助** | 公式サイト（Playwright + claude -p） | 正式性確認・チケットサイト未掲載の補完（popup/cafe/展示系）。active IPのみを対象 |
| **3 IP発見** | AniList、アニメイト、VTuber | IP discovery のみ。イベントデータとしては使わない |

### カテゴリ別プライマリソース
- `live / stage` → チケットサイト（e+等）優先
- `popup / cafe / exhibition` → 公式サイト + listing 優先
- `vtuber` → 所属事務所/タレント告知優先

---

## パイプライン設計

`run-whitelist` と `run` の分離を廃止し、単一パイプラインに統合する。

```
1. discover_events
   e+ / Eventernote 等から raw event candidates を大量取得

2. extract_entities
   IP名・会場・価格・日付・イベント種別を抽出

3. resolve_ip
   ip_registry に照合。新規は candidate として登録

4. score_ip_activity
   IPごとの活動性スコアを計算 → status を更新

5. refresh_official
   active / cooling のIPのみ公式サイトを確認（全IPを毎日回さない）

6. merge_events
   cross-source dedup / identity resolution

7. publish
   DB更新 → Read API → 通知キュー
```

### 実行スケジュール（案）
- `discover_events` → 1日複数回（鮮度が通知課金の価値）
- `refresh_official` → 日次（active IPのみ）
- `score_ip_activity` → 日次
- `inactive` IPの再探索 → 月次

---

## dedup 方針

`canonical_url + start_date` は廃止。**identity resolution** に変える。

1. **source内dedup**: 正規化タイトル + 日付レンジ + 会場 + IP候補
2. **cross-source merge**: タイトル類似度・開始日近接・venue一致・IP一致をスコア化
3. **シリーズ対応**: ライブツアー・巡回展示は `event_series` + `event_occurrence` に分離

---

## DB方針

- 初期: **SQLite**（K12単体運用、シンプルに始める）
- APIを公開・ユーザーが増えた段階で PostgreSQL に移行
- `event_source_record`（生データ）は別ファイルかテーブルに保存して再処理を可能にする

---

## API設計（Read API）

### 無料エンドポイント
```
GET /events          # 一覧（フィルタ: category, area, date_from, date_to）
GET /events/{id}     # 詳細
GET /ips             # IP一覧
GET /ips/{id}        # IP詳細 + upcoming events
```

### Premium エンドポイント
```
GET /feeds/personalized   # パーソナルフィード
POST /favorites           # お気に入り登録
POST /alerts              # アラートルール設定
```

### API（従量課金）
```
APIキー認証 + 使用量メータリング
/v1/events, /v1/ips 等（上記と同等だが高レートリミット・bulk取得可）
```

---

## スクレイピング防御（将来対応）

データ資産の保護。ユーザーとデータが育ったタイミングで実装する。

- レート制限 + ページネーション制御
- APIキー必須化（大量取得はAPI経由のみ）
- JS rendering 必須化（Next.js SSR等）
- robots.txt の明示
- 利用規約でスクレイピング禁止を明記
- honeypot フィールド

---

## 収集戦略：スクレイピング vs AI の切り分け

非構造データが前提。「どのフィールドをどの手段で取るか」を事前に設計し、AIコストを最小化する。

### 基本原則

```
① rawをスクレイピングで取得（常に全フィールドのraw_*を保存）
② 構造化済みフィールドはそのままパース（AI不要）
③ 構造化できなかったフィールドだけAIへ（バッチ化・安いモデル）
④ 公式サイト探索だけPlaywright+Agent（最後の手段）
```

### フィールド別取得手段

| フィールド | 手段 | 理由 |
|---|---|---|
| タイトル | スクレイピング | ほぼ必ずラベルがある |
| URL | スクレイピング | そのまま |
| 日時（チケットサイト） | スクレイピング | 構造化済みが多い |
| 会場名（チケットサイト） | スクレイピング | 構造化済みが多い |
| 価格（チケットサイト） | スクレイピング | e+等は構造化 |
| 販売状態 | スクレイピング | クラス名等で判別可 |
| 日時（非標準表記） | AI | 「3月上旬」「来春」等 |
| 価格（本文埋め込み） | AI | 「¥3,500（税込）+手数料」等 |
| IPタグ特定 | AI | タイトルから判断が必要 |
| content_type分類 | AI | popup/live/cafe等の判断 |
| 公式サイトからのイベント抽出 | Agent | 非構造HTML、最後の手段 |

### グラウンディング設計

AIが出した値の信頼性を担保するために：

- `source_url` + `raw_*` フィールドを**必ず保存**（後から検証可能に）
- AI抽出フィールドには `extracted_by: "ai"` + `confidence: float` を付与
- `parse_version` を記録して再処理に備える
- 生データ（`event_source_record`）は正規化後も削除しない

### コスト最適化

- AIへのリクエストは**バッチ化**（1件ずつ叩かない）
- IPタグ・分類など「分類タスク」は安いモデルで十分
- キャッシュ：同じ `source_url` の再取得はスキップ
- 公式サイトAgent（Playwright+claude-p）は `active` IPのみ、週次に限定

---

## ロードマップ

### Phase 1: 収集基盤の再設計（現在）
- [ ] `whitelist.json` → `ip_registry`（SQLite）に移行
- [ ] e+ / Eventernote をプライマリイベントソース化
- [ ] イベントスキーマ拡張（price, sales_status, source_confidence 等）
- [ ] dedup を identity resolution に変更
- [ ] パイプラインを単一フローに統合
- [ ] K12 デプロイ

### Phase 2: 品質改善
- [ ] IP alias 辞書
- [ ] activity scoring の精緻化
- [ ] coverage / precision メトリクス
- [ ] official site は active IP の verification に限定

### Phase 3: サービス公開（Free tier）
- [ ] Read API
- [ ] フロントエンド（イベント一覧サイト）

### Phase 4: 課金（Premium tier）
- [ ] ユーザー認証
- [ ] フォロー・アラートルール
- [ ] 通知配信（プッシュ / メール）
- [ ] パーソナルフィード・レコメンド

### Phase 5: API 公開（従量課金）
- [ ] APIキー発行・管理
- [ ] 使用量メータリング・Billing
- [ ] スクレイピング防御
