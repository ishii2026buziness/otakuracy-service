# Current Progress

## Objective

アニメ・ゲーム・VTuber IPのオタク向けイベントを収集・識別するパイプライン。
e+/Eventernote から生データをスクレイピング → IPを抽出（Haiku via Claude Gateway）→ 重複除去（日付+会場+IP）→ SQLite に永続化。

## Status

パイプライン再設計・実装完了。K12デプロイ待ち（手動操作 KEN-80）。

## 実装済み

### コア設計
- `app/src/collect/base.py` — EventSource ABC + RawEventRecord dataclass
- `app/src/db/schema.sql` — 6テーブル（ip_registry, event, event_source_record, event_ip_link, venue, price_offer）
- `app/src/db/repository.py` — IpRegistryRepo / EventSourceRecordRepo / EventRepo / EventIpLinkRepo
- `app/src/collect/dedup_v2.py` — 同一性判定: 日付+会場+IP（IP不明は判定不能）
- `app/src/collect/extract_ip.py` — IP抽出: ip_registryで文字列マッチ → 未マッチをHaiku(Claude Gateway)でバッチ処理
- `app/src/pipeline_v2.py` — 4ステージパイプライン: discover → extract_ip → dedup → persist
- `app/src/cli_v2.py` — コンテナエントリポイント（`python -m cli_v2 run`）

### ソースアダプタ
- `app/src/collect/eplus.py` — e+スクレイパー（EventSource継承、TIER=1）
- `app/src/collect/eventernote.py` — Eventernoteスクレイパー（EventSource継承、TIER=1）、日付セレクタバグ修正済み

### K12インフラ
- `k12-network-notes/nixos/modules/otakuracy.nix` — systemd oneshot + timer（JST 15:00）
- `k12-network-notes/nixos/hosts/k12/default.nix` — `k12.otakuracy.enable = true`
- `k12-network-notes/scripts/build-on-k12.sh` — otakuracy ビルドターゲット追加

## 設計決定（ADR）

| ADR | 内容 |
|-----|------|
| ADR-0008 | イベント同一性 = 日付+会場+IP（IP不明は除外） |
| ADR-0009 | IP抽出をdedupより前に実行、Haiku via Claude Gateway |

## Resume Here（次のステップ）

**KEN-80: K12手動デプロイ**（ブロッカー: ssh操作が必要）

```bash
# 1. otakuracy-service をK12にsyncしてビルド
cd ~/projects/0313/k12-network-notes
./scripts/build-on-k12.sh otakuracy

# 2. .env をK12に配置（ANTHROPIC_API_KEY必須）
ssh k12 "mkdir -p /srv/otakuracy/auth"
scp /path/to/.env k12:/srv/otakuracy/auth/.env

# 3. NixOS rebuild
ssh k12 "cd ~/k12-network-notes && sudo nixos-rebuild switch --flake .#k12"

# 4. 動作確認
ssh k12 "sudo systemctl start otakuracy && journalctl -u otakuracy -f"
```

**KEN-67: ソースon/off設定ファイル化**（未着手）
- `sources.yaml` で enabled/tier/schedule を管理
- pipeline_v2 起動時に読み込む

## Blockers

- なし（KEN-80 は手動操作待ち）

## Last Verified

- Date: 2026-03-21
- Pipeline実行: `uv run python -m cli_v2 run` で動作確認済み（discover/extract_ip/dedup/persistの4ステージ）
