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


def normalize_venue(venue: str) -> str:
    """会場名の正規化（NFKC + lowercase + 空白除去）。"""
    v = unicodedata.normalize("NFKC", venue)
    v = re.sub(r"[\s　]+", "", v).lower()
    return v


def _same_event(a: RawEventRecord, a_ip: str | None,
                b: RawEventRecord, b_ip: str | None) -> bool:
    """
    同一イベント判定。IP が特定できていることが前提。

    1. date + venue + ip が全て一致 → 確実に同一
    2. date + ip が一致 + title類似(≥0.6) → 高確率同一（会場表記が異なるソース間対応）

    IP が不明（None）な場合は同一と判定しない。
    IP が特定できていないイベントは dedup の根拠がないため除外する。
    """
    # IP不明は判定不能
    if not a_ip or not b_ip:
        return False
    if a_ip != b_ip:
        return False

    date_a = (a.raw_date_text or "")[:10]
    date_b = (b.raw_date_text or "")[:10]
    if not date_a or not date_b or date_a != date_b:
        return False

    venue_a = normalize_venue(a.raw_venue_text or "")
    venue_b = normalize_venue(b.raw_venue_text or "")
    venue_match = bool(venue_a and venue_b and venue_a == venue_b)

    if venue_match:
        return True
    if title_similarity(a.raw_title, b.raw_title) >= 0.6:
        return True  # 会場表記がソース間で違うケースのフォールバック
    return False


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


def dedup_within_source(
    records: list[RawEventRecord],
    ip_map: dict[str, str | None] | None = None,  # {source_url: ip_id}
) -> list[DeduplicatedEvent]:
    """
    Source内 dedup (KEN-75 / KEN-82).
    同一ソース内で日付+会場+IPに基づいてマージ。
    """
    if ip_map is None:
        ip_map = {}

    results: list[DeduplicatedEvent] = []
    used = set()

    for i, rec in enumerate(records):
        if i in used:
            continue
        group = [rec]
        rec_ip = ip_map.get(rec.source_url)
        for j, other in enumerate(records):
            if j <= i or j in used:
                continue
            other_ip = ip_map.get(other.source_url)
            if _same_event(rec, rec_ip, other, other_ip):
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
    groups_by_source: dict[str, list[DeduplicatedEvent]],
    ip_map: dict[str, str | None] | None = None,
) -> list[DeduplicatedEvent]:
    """
    Cross-source merge (KEN-76 / KEN-82).
    異なるソース間で日付+会場+IPに基づいてマージ。
    """
    if ip_map is None:
        ip_map = {}

    all_events: list[DeduplicatedEvent] = []
    for source_events in groups_by_source.values():
        all_events.extend(source_events)

    merged_indices = set()
    results: list[DeduplicatedEvent] = []

    for i, ev in enumerate(all_events):
        if i in merged_indices:
            continue
        group = [ev]
        ev_ip = ip_map.get(ev.primary.source_url)
        for j, other in enumerate(all_events):
            if j <= i or j in merged_indices:
                continue
            if ev.primary.source_id == other.primary.source_id:
                continue  # same source — already handled above
            other_ip = ip_map.get(other.primary.source_url)
            if _same_event(ev.primary, ev_ip, other.primary, other_ip):
                group.append(other)
                merged_indices.add(j)
        merged_indices.add(i)
        results.append(DeduplicatedEvent(
            primary=group[0].primary,
            merged=[g.primary for g in group[1:]],
            merge_score=max(g.merge_score for g in group),
        ))
    return results
