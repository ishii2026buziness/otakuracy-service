# Bootstrap

このファイルが存在する = 未セットアップ。
セットアップ完了後にこのファイルを削除すること。

## 手順

### 1. サービス名を設定

`service.config.yaml` を作成：

```yaml
service_name: <サービス名をここに記入>
infra:
  url: https://github.com/ishii2025buziness/k12-network-notes  # デフォルト。変える場合はここを書き換える
  type: k12
```

### 2. infra submoduleを追加

デフォルト（k12-network-notes）の場合：

```bash
git submodule add https://github.com/ishii2025buziness/k12-network-notes infra
git submodule update --init --recursive
```

別のインフラを使う場合は `service.config.yaml` の `infra.url` を変更してから上記コマンドのURLを差し替える。

### 3. app/pyproject.tomlのservice_nameを更新

`app/pyproject.toml` の `name = "service-name"` を実際のサービス名に変更。

### 4. app/src/pipeline.py のpipeline名を更新

`pipeline="service-name"` を実際のサービス名に変更。

### 5. このファイルを削除

```bash
git rm BOOTSTRAP.md
git commit -m "bootstrap: initialize <サービス名>"
```
