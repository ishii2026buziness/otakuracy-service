"""
IP同定のための keyword 分析スクリプト。
4手法（TF-IDF / PMI / BM25 / Graph Clustering）を実装。

Usage:
    python ip_keyword_analysis.py [--method all|tfidf|pmi|bm25|graph] [--top N] [--db PATH]
"""
import math
import argparse
import sqlite3
from collections import defaultdict


def load_data(conn: sqlite3.Connection):
    """event_keywords と event テーブルからデータ読み込み。"""
    rows = conn.execute(
        "SELECT ek.event_id, e.title, ek.keyword, ek.weight "
        "FROM event_keywords ek "
        "INNER JOIN event e ON ek.event_id = e.event_id"
    ).fetchall()

    # event_id → {keyword: tf}
    event_kws: dict[str, dict[str, float]] = defaultdict(dict)
    # event_id → title
    event_titles: dict[str, str] = {}
    # keyword → set of event_ids
    kw_events: dict[str, set[str]] = defaultdict(set)

    for event_id, title, keyword, weight in rows:
        event_kws[event_id][keyword] = weight
        event_titles[event_id] = title
        kw_events[keyword].add(event_id)

    # event_id → tweet count (dl for BM25)
    tweet_counts = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT event_id, COUNT(*) FROM event_tweet_link GROUP BY event_id"
        ).fetchall()
    }
    return event_kws, event_titles, kw_events, tweet_counts


# ─── TF-IDF ──────────────────────────────────────────────────────────────────

def run_tfidf(event_kws, event_titles, kw_events, top_n=5):
    N = len(event_kws)
    print(f"\n{'='*60}")
    print(f"[TF-IDF]  N={N} events")
    print(f"{'='*60}")

    idf: dict[str, float] = {
        kw: math.log((N + 1) / (len(evs) + 1)) + 1  # smoothed IDF
        for kw, evs in kw_events.items()
    }

    scores: dict[str, list[tuple[float, str]]] = {}
    for event_id, kws in event_kws.items():
        ranked = sorted(
            [(tf * idf[kw], kw) for kw, tf in kws.items()],
            reverse=True,
        )
        scores[event_id] = ranked

    for event_id, ranked in sorted(scores.items(), key=lambda x: x[1][0][0] if x[1] else 0, reverse=True)[:20]:
        top = ranked[:top_n]
        title = event_titles.get(event_id, "?")[:30]
        kw_str = ", ".join(f"{kw}({s:.3f})" for s, kw in top)
        print(f"  {title:<32} {kw_str}")

    # IDF分布: IP名らしいキーワード（高IDF）vs 汎用語（低IDF）
    print("\n  [IDF分布] 高IDF（IP名候補）:")
    for kw, val in sorted(idf.items(), key=lambda x: -x[1])[:15]:
        df = len(kw_events[kw])
        print(f"    {kw:<20} idf={val:.3f}  df={df}")
    print("\n  [IDF分布] 低IDF（汎用語候補）:")
    for kw, val in sorted(idf.items(), key=lambda x: x[1])[:10]:
        df = len(kw_events[kw])
        print(f"    {kw:<20} idf={val:.3f}  df={df}")

    return scores, idf


# ─── PMI ─────────────────────────────────────────────────────────────────────

def run_pmi(event_kws, event_titles, kw_events, top_n=5):
    N = len(event_kws)
    print(f"\n{'='*60}")
    print(f"[PMI]  N={N} events")
    print(f"{'='*60}")

    # P(kw) ≈ df / N  （イベント出現率）
    p_kw = {kw: len(evs) / N for kw, evs in kw_events.items()}

    pmi_scores: dict[str, list[tuple[float, str]]] = {}
    for event_id, kws in event_kws.items():
        ranked = []
        for kw, tf in kws.items():
            if tf == 0 or p_kw[kw] == 0:
                continue
            # PMI = log( P(kw|event) / P(kw) ) = log( tf / p_kw )
            pmi = math.log(tf / p_kw[kw])
            ranked.append((pmi, kw))
        ranked.sort(reverse=True)
        pmi_scores[event_id] = ranked

    for event_id, ranked in sorted(pmi_scores.items(), key=lambda x: x[1][0][0] if x[1] else -99, reverse=True)[:20]:
        top = ranked[:top_n]
        title = event_titles.get(event_id, "?")[:30]
        kw_str = ", ".join(f"{kw}({s:.2f})" for s, kw in top)
        print(f"  {title:<32} {kw_str}")

    return pmi_scores


# ─── BM25 ────────────────────────────────────────────────────────────────────

def run_bm25(event_kws, event_titles, kw_events, tweet_counts, top_n=5, k1=1.5, b=0.75):
    N = len(event_kws)
    print(f"\n{'='*60}")
    print(f"[BM25]  N={N} events  k1={k1}  b={b}")
    print(f"{'='*60}")

    avgdl = sum(tweet_counts.get(ev, 30) for ev in event_kws) / max(N, 1)

    idf_bm25: dict[str, float] = {
        kw: math.log((N - len(evs) + 0.5) / (len(evs) + 0.5) + 1)
        for kw, evs in kw_events.items()
    }

    bm25_scores: dict[str, list[tuple[float, str]]] = {}
    for event_id, kws in event_kws.items():
        dl = tweet_counts.get(event_id, avgdl)
        ranked = []
        for kw, tf in kws.items():
            idf_val = idf_bm25[kw]
            tf_norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
            score = idf_val * tf_norm
            ranked.append((score, kw))
        ranked.sort(reverse=True)
        bm25_scores[event_id] = ranked

    for event_id, ranked in sorted(bm25_scores.items(), key=lambda x: x[1][0][0] if x[1] else 0, reverse=True)[:20]:
        top = ranked[:top_n]
        title = event_titles.get(event_id, "?")[:30]
        kw_str = ", ".join(f"{kw}({s:.3f})" for s, kw in top)
        print(f"  {title:<32} {kw_str}")

    return bm25_scores


# ─── Graph Clustering (Cosine + Union-Find) ───────────────────────────────────

def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if (na and nb) else 0.0


class _UF:
    def __init__(self, keys):
        self.p = {k: k for k in keys}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, x, y):
        self.p[self.find(x)] = self.find(y)

    def groups(self):
        g = defaultdict(list)
        for k in self.p:
            g[self.find(k)].append(k)
        return dict(g)


def run_graph_clustering(event_kws, event_titles, top_n=5, threshold=0.3):
    events = list(event_kws.keys())
    N = len(events)
    print(f"\n{'='*60}")
    print(f"[Graph Clustering]  N={N} events  cosine threshold={threshold}")
    print(f"{'='*60}")

    uf = _UF(events)
    edge_count = 0
    strong_edges: list[tuple[float, str, str]] = []

    for i in range(N):
        for j in range(i + 1, N):
            sim = _cosine(event_kws[events[i]], event_kws[events[j]])
            if sim >= threshold:
                uf.union(events[i], events[j])
                edge_count += 1
                if sim >= 0.5:
                    strong_edges.append((sim, events[i], events[j]))

    groups = uf.groups()
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"  エッジ数: {edge_count}  クラスタ数(2件以上): {len(multi)}")

    print("\n  [クラスタ一覧] (2件以上のもの、上位20)")
    for root, members in sorted(multi.items(), key=lambda x: -len(x[1]))[:20]:
        print(f"\n  クラスタ ({len(members)}件):")
        for ev in members[:8]:
            top_kws = sorted(event_kws[ev].items(), key=lambda x: -x[1])[:3]
            title = event_titles.get(ev, "?")[:35]
            kw_str = ", ".join(k for k, _ in top_kws)
            print(f"    - {title:<37} [{kw_str}]")
        if len(members) > 8:
            print(f"    ... and {len(members)-8} more")

    print(f"\n  [高類似ペア] cosine>=0.5 (上位15)")
    for sim, ev_a, ev_b in sorted(strong_edges, reverse=True)[:15]:
        ta = event_titles.get(ev_a, "?")[:25]
        tb = event_titles.get(ev_b, "?")[:25]
        print(f"    {sim:.3f}  {ta:<27} <-> {tb}")

    return groups


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", default="all", choices=["all", "tfidf", "pmi", "bm25", "graph"])
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--db", default="/srv/otakuracy/data/otakuracy.db")
    parser.add_argument("--threshold", type=float, default=0.3, help="graph clustering cosine threshold")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    event_kws, event_titles, kw_events, tweet_counts = load_data(conn)

    total_events = len(event_kws)
    total_kws = sum(len(v) for v in event_kws.values())
    print(f"データ: {total_events} events, {total_kws} keyword entries, {len(kw_events)} unique keywords")

    if total_events == 0:
        print("データなし。抽出が完了してから実行してください。")
        return

    m = args.method
    if m in ("all", "tfidf"):
        run_tfidf(event_kws, event_titles, kw_events, top_n=args.top)
    if m in ("all", "pmi"):
        run_pmi(event_kws, event_titles, kw_events, top_n=args.top)
    if m in ("all", "bm25"):
        run_bm25(event_kws, event_titles, kw_events, tweet_counts, top_n=args.top)
    if m in ("all", "graph"):
        run_graph_clustering(event_kws, event_titles, top_n=args.top, threshold=args.threshold)


if __name__ == "__main__":
    main()
