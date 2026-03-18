# Current Progress

## Objective

アニメ・ゲーム・VTuber IPのオタク向けイベントを収集するパイプライン。
IPホワイトリストから公式サイトをクロール → イベント抽出 → 重複除去 → /data/events_processed.json に保存。

## Status

collect ソースを移植完了。コンテナビルド未確認。

## Resume Here

```bash
# コンテナビルド確認
cd /home/kento/projects/0318/otakuracy-service
podman build -f container/Containerfile -t otakuracy .

# smoke テスト
podman run --rm -v /data/otakuracy:/data otakuracy python -m cli smoke

# check (whitelist が /data/whitelist.json にあること前提)
podman run --rm -v /data/otakuracy:/data otakuracy python -m cli check
```

## Next Actions

- [ ] コンテナビルドを通す
- [ ] /data/whitelist.json を既存データからコピーして動作確認
- [ ] claude CLI の認証をコンテナ内で通す（/auth/.env or volume mount）

## Blockers

- claude CLI のインストール方法をコンテナ内で確認する必要あり

## Last Verified

- Date: 2026-03-18
