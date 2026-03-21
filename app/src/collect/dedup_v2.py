"""Identity resolution based dedup (replaces canonical_url+start_date approach)."""
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional
from .base import RawEventRecord


def normalize_title(title: str) -> str:
    """表記ゆれを吸収する正規化。全角→半角、記号除去、lowercase。"""
    # NFKCで全角→半角
    t = unicodedata.normalize("NFKC", title)
    # 括弧内の付加情報除去: 【...】《...》（...）
    t = re.sub(r"[【《〈〔\[（(][^】》〉\]）)]*[】》〉\]）)]", "", t)
    # 空白・記号を除去して lowercase
    t = re.sub(r"[\s\-_・　]+", " ", t).strip().lower()
    return t


def title_similarity(a: str, b: str) -> float:
    """Jaccard similarity on character 2-grams of normalized titles."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    def bigrams(s): return {s[i:i+2] for i in range(len(s)-1)}
    ba, bb = bigrams(na), bigrams(nb)
    intersection = len(ba & bb)
    union = len(ba | bb)
    return intersection / union if union else 0.0


@dataclass
class DeduplicatedEvent:
    """結果: 代表 RawEventRecord + マージされたレコードリスト"""
    primary: RawEventRecord
    merged: list[RawEventRecord]
    merge_score: float  # 最高スコア（同一ソース内は 1.0）


def dedup_within_source(records: list[RawEventRecord]) -> list[DeduplicatedEvent]:
    """
    Source内 dedup (KEN-75).
    同一ソース内で正規化タイトル+日付が近いものをマージ。
    """
    results: list[DeduplicatedEvent] = []
    used = set()

    for i, rec in enumerate(records):
        if i in used:
            continue
        group = [rec]
        for j, other in enumerate(records):
            if j <= i or j in used:
                continue
            sim = title_similarity(rec.raw_title, other.raw_title)
            # 日付も一致している場合のみマージ
            date_match = (
                rec.raw_date_text and other.raw_date_text and
                rec.raw_date_text[:10] == other.raw_date_text[:10]
            )
            if sim >= 0.8 and date_match:
                group.append(other)
                used.add(j)
        used.add(i)
        results.append(DeduplicatedEvent(
            primary=group[0],
            merged=group[1:],
            merge_score=1.0 if len(group) == 1 else 0.9,
        ))
    return results


def merge_across_sources(
    groups_by_source: dict[str, list[DeduplicatedEvent]]
) -> list[DeduplicatedEvent]:
    """
    Cross-source merge (KEN-76).
    異なるソース間でタイトル類似度・日付近接でマージ。
    """
    all_events: list[DeduplicatedEvent] = []
    for source_events in groups_by_source.values():
        all_events.extend(source_events)

    merged_indices = set()
    results: list[DeduplicatedEvent] = []

    for i, ev in enumerate(all_events):
        if i in merged_indices:
            continue
        group = [ev]
        for j, other in enumerate(all_events):
            if j <= i or j in merged_indices:
                continue
            if ev.primary.source_id == other.primary.source_id:
                continue  # same source — already handled above
            sim = title_similarity(ev.primary.raw_title, other.primary.raw_title)
            date_match = (
                ev.primary.raw_date_text and other.primary.raw_date_text and
                ev.primary.raw_date_text[:10] == other.primary.raw_date_text[:10]
            )
            if sim >= 0.7 and date_match:
                group.append(other)
                merged_indices.add(j)
        merged_indices.add(i)
        results.append(DeduplicatedEvent(
            primary=group[0].primary,
            merged=[g.primary for g in group[1:]],
            merge_score=max(g.merge_score for g in group),
        ))
    return results
