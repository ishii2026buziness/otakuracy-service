# App

サービス本体のコード。

## 開発

```bash
cd app
uv run python -m cli run
uv run python -m cli smoke
uv run python -m cli check
```

## 共通ライブラリ

`../common/` にJobResult, ArtifactStore, job_cliなどがある。
pyproject.tomlで `path = "../common"` として参照する。
