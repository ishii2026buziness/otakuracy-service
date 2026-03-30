# Service Template

新サービスのひな形リポジトリ。

## 初回セットアップ

**BOOTSTRAP.mdが存在する場合、必ず最初にそれに従うこと。**

BOOTSTRAP.mdがない = セットアップ済み。

## 新サービスの作り方

```bash
gh repo create <service-name> --template ishii2025buziness/service-template --public --clone
cd <service-name>
git submodule update --init --recursive  # common submoduleを初期化
```

その後BOOTSTRAP.mdに従う。

## Submodules

- `common/` → [pipeline-common](https://github.com/ishii2025buziness/pipeline-common)（共通contracts・ヘルパー）
- `infra/` → [k12-network-notes](https://github.com/ishii2025buziness/k12-network-notes)（K12 IaC 正本）

### infra/ の扱い（KEN-252 / 2026-03-30）

`infra/` は `k12-network-notes` リポジトリの submodule です。

- **`infra/` ディレクトリを直接編集しない**
- K12 IaC の変更は必ず `k12-network-notes` 本体で行う:
  `~/repos/github.com/ishii2025buziness/k12-network-notes`
- submodule の参照先を更新する場合: `git submodule update --remote infra`
- 詳細: `k12-network-notes/docs/adr/0008-iac-single-source-of-truth.md`

#### 二重更新ガード（KEN-252 残課題 / 2026-03-30）

`scripts/guard-infra.sh` と `.github/workflows/guard-infra.yml` により、`infra/` への誤変更を検知する。

- **CI**: PR/push 時に自動実行。`infra/` に uncommitted な変更があれば CI が失敗する。
- **手動実行**: `bash scripts/guard-infra.sh`

##### infra/ を誤って編集した場合の復旧手順

```bash
# 変更を破棄して submodule を元の状態に戻す
git -C infra/ checkout .

# または submodule を HEAD の参照先にリセット
git submodule update --init infra

# 確認
bash scripts/guard-infra.sh
```

### submodule操作

```bash
# common更新
git submodule update --remote common

# infra更新
git submodule update --remote infra
```

## 構成

- `app/` — サービス本体（run/smoke/check CLI）
- `common/` — 共通ライブラリ（JobResult, ArtifactStore等）
- `container/` — Containerfile・entrypoint.shひな形
- `infra/` — インフラwiring（bootstrap後に設定）
- `docs/` — 設計・契約ドキュメント
- `skills/` — サービス固有スキル
- `progress/current.md` — 進捗・ハンドオフ
- `service.config.yaml` — サービス設定（bootstrap後に生成）

## ドキュメント

- `docs/contracts.md` — **実装時に必ず確認すること**。強制する契約と独自でよい部分を定義。
- `docs/architecture.md` — このテンプレートの設計意図と決定理由。

将来のエージェントが必要とする知識（設計決定の理由、契約、運用ルール等）は`docs/`以下に書いてAGENTS.mdから参照せよ。一時的な作業メモや実装詳細は残さない。

## Service Manifest

`service.manifest.yaml` はSE/PEの境界インタフェース。
**このファイルが存在しない場合、作業開始前に必ず生成すること。**

- スキーマ: https://github.com/ishii2025buziness/k12-network-notes/blob/main/schemas/service-manifest.schema.json
- 宣言するもの: `name`, `input`, `process`, `output`, `successCriteria`
- 宣言しないもの: schedule / secrets / metrics / alerts / deploy（Platform側の責務）

生成手順: `app/src/pipeline.py` 等を読んでスキーマに従いYAMLを生成し、CIのvalidationが通ることを確認する。
