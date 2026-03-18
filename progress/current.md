# Current Progress

## Objective

アニメ・ゲーム・VTuber IPのオタク向けイベントを収集するパイプライン。
IPホワイトリストから公式サイトをクロール → イベント抽出 → 重複除去 → /data/events_processed.json に保存。

## Status

移植完了。K12デプロイ未着手。

## 設計決定

- `run` (毎日): fetch-all-events + build-processed
- `run-whitelist` (週次): whitelist-update + whitelist-fill-urls
- 1コンテナイメージ、systemd timer 2本（NixOSモジュール内）

## Resume Here

次のステップはK12デプロイ。/gsd:new-milestone か手動で以下を実施：

1. `infra/nixos/modules/otakuracy.nix` 作成（oneshot.nix テンプレートベース、timer 2本）
2. `infra/nixos/hosts/k12/default.nix` に `k12.otakuracy.enable = true;` 追記
3. `cli.py` / `pipeline.py` に `run-whitelist` コマンド追加
4. `infra/containers/build-on-k12.sh` に otakuracy ビルド処理追記
5. `/srv/otakuracy/auth/claude-dir/` を volume mount（claude CLI 認証）
6. `.env.example` 作成
7. K12でビルド → NixOS rebuild → 動作確認

## Blockers

- claude CLI のコンテナ内認証方法を確認（claude-dir volume mount パターン、auto-matome 参照）

## Last Verified

- Date: 2026-03-18
