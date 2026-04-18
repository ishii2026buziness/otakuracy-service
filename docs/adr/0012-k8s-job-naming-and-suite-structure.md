# ADR-0012: k8s ジョブ命名規約とスイート構造

**Status**: Accepted  
**Date**: 2026-04-18

## Context

otakuracy のバッチ処理は複数の独立したジョブで構成される（pipeline, ip-link-search, ip-link-agent 等）。
将来的にジョブが増えたとき、命名やパッケージ構造に一貫性がないと管理が困難になる。

## Decision

### k8s リソース命名

| 項目 | 規約 | 例 |
|---|---|---|
| リソース名 | `otakuracy-<job名>` | `otakuracy-ip-link-search` |
| ラベル | `app: otakuracy` 必須 | 全ジョブ共通 |
| namespace | `default` | 全ジョブ共通 |

`kubectl get all -l app=otakuracy` で otakuracy 関連の全リソースが一覧できる状態を維持する。

### Python パッケージ構造（スイート）

関連する複数ジョブは `collect/<suite>/` としてサブパッケージにまとめる。

```
app/src/collect/
    ip_link/          ← スイート（ip-link-search + ip-link-agent）
        __init__.py
        searcher.py   ← ip-link-search ジョブのロジック
        agent.py      ← ip-link-agent ジョブのロジック
```

### CLI 命名

```
cli_<suite>_<job>.py
```

例: `cli_ip_link_search.py`, `cli_ip_link_agent.py`

### 独立性の原則

- 各 CLI は単体で完結する（他ジョブへの依存なし）
- スイートはあくまで **関連性の表現**であり、実行順序の強制ではない
- ジョブ間の連携は DB の状態（`event_ip_link` のレコード有無等）を介して行う

## Consequences

- `kubectl get all -l app=otakuracy` が唯一の運用ダッシュボードとして機能する
- 新しいジョブを追加するときは必ずこの命名規約に従う
- スイートに収まらない単独ジョブは `collect/<job>.py` に直置きしてよい
