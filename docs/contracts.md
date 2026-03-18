# Service Contracts

このテンプレートから作成したサービスが守るべき契約と、独自実装でよい部分を定義する。

## 強制（全サービス共通）

### CLI インタフェース

すべてのサービスは以下の3コマンドを持つこと：

```bash
python -m cli run    # パイプライン本体を実行
python -m cli smoke  # 軽量な疎通確認
python -m cli check  # 設定・依存の検証
```

### run の出力

`run` は必ず `JobResult` を返すこと（`common/contracts.py` 参照）。

### entrypoint.sh

コンテナ起動時の最終コマンドは `python -m cli run` であること。
`container/entrypoint.sh` をひな形として使い、この部分は変えない。

## 独自でよい（サービスごとに異なる）

- パイプラインの中身（何を収集・処理・出力するか）
- 認証の種類（Claude auth、YouTube tokens、Twitter cookies等）
- 依存パッケージ（`app/pyproject.toml`）
- Containerfileのビルド手順（システム依存パッケージ等）
