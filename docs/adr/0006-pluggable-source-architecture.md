# ADR-0006: 収集ソースをプラガブルなアーキテクチャに統一する

- **Status**: Accepted
- **Date**: 2026-03-21

## Context

初期実装では各コレクタークラス（EplusClient, EventernoteClient等）が共通インターフェースを持たず独立して存在していた。

問題：
- ソースの追加・削除のたびに `cli.py` と `pipeline.py` を直接変更する必要がある
- ソースのon/offが `--sources` フラグの文字列分岐のみで管理されていた
- 各ソースの品質（取得件数・エラー率・鮮度）を横断的に評価する仕組みがなかった
- 費用対効果の悪いソースを外しにくい

収集範囲は「どこまでも広げられる曖昧なドメイン」であり、費用対効果を最大化するためにソースのin/outが容易な設計が必要。

## Decision

`EventSource` ABC（抽象基底クラス）を定義し、全ソースを準拠させる。

```python
class EventSource(ABC):
    SOURCE_ID: str
    TIER: int  # 1=プライマリ, 2=補助, 3=IP発見
    COLLECTION_METHOD: str  # requests / playwright / api / agent

    @abstractmethod
    def collect_raw(self) -> list[RawEventRecord]: ...
    def health_check(self) -> SourceHealth: ...
```

ソースのon/offは `sources.yaml` で管理し、コードを触らずに制御できるようにする。
ソース評価指標（カバレッジ・構造化度・安定性・コスト・鮮度・ToS・価格取得可否）を `docs/sources.md` に定義し、採用・除外の判断基準を明文化する。

## Consequences

- 新ソースの追加は `EventSource` を継承したクラスを作るだけ
- `health_check()` でCIや監視から疎通確認ができる
- 既存クラスのリファクタが必要（EplusClient等）
