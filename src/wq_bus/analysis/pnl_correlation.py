"""pnl_correlation.py — Compute pairwise PnL correlation among submitted alphas."""
from __future__ import annotations

from wq_bus.analysis.stats_helpers import pearson
from wq_bus.data import knowledge_db


def compute_pairwise_corr(
    brain_client,
    threshold: float = 0.7,
    min_overlap: int = 100,
    recent_n: int | None = None,
) -> list[dict]:
    """Compute pairwise Pearson correlation for all submitted alpha PnL series.

    For each submitted alpha:
    1. Try cache: knowledge_db.get_pnl()
    2. On miss: brain_client.get_pnl() + knowledge_db.upsert_pnl()

    Then compute all pairs; store results via knowledge_db.upsert_pnl_corr.
    Returns list of high-correlation pair dicts (|pearson| >= threshold).

    Args:
        brain_client: BrainClient instance (has .get_pnl(alpha_id)).
        threshold: Absolute correlation threshold for 'high' pairs.
        min_overlap: Minimum overlapping date points required.
        recent_n: If set (>0), cap analysis to the most recent N submitted
            alphas. Critical for large portfolios — runtime is O(n²) and
            each uncached PnL is one HTTP call. None or 0 disables the cap.
    """
    alpha_ids = knowledge_db.list_submitted_alpha_ids()
    if recent_n and recent_n > 0 and len(alpha_ids) > recent_n:
        # list_submitted_alpha_ids returns insertion order; take the tail
        # (most recent submissions). Adjust upstream if a different ordering
        # is desired.
        alpha_ids = alpha_ids[-recent_n:]

    # Fetch PnL series for each alpha (cache-first)
    series_map: dict[str, list[tuple[str, float]]] = {}
    for alpha_id in alpha_ids:
        cached = knowledge_db.get_pnl(alpha_id)
        if cached:
            series_map[alpha_id] = cached
        else:
            fetched = brain_client.get_pnl(alpha_id)
            if fetched:
                knowledge_db.upsert_pnl(alpha_id, fetched)
            series_map[alpha_id] = fetched

    # Build date-indexed dicts for fast overlap computation
    indexed: dict[str, dict[str, float]] = {
        aid: {date: pnl for date, pnl in series}
        for aid, series in series_map.items()
        if series
    }

    high_corr_pairs: list[dict] = []
    ids = list(indexed.keys())

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a_id, b_id = ids[i], ids[j]
            a_map = indexed[a_id]
            b_map = indexed[b_id]

            # Find overlapping dates
            common_dates = sorted(set(a_map) & set(b_map))
            n_overlap = len(common_dates)
            if n_overlap < min_overlap:
                continue

            xs = [a_map[d] for d in common_dates]
            ys = [b_map[d] for d in common_dates]

            r = pearson(xs, ys)
            if r is None:
                continue

            knowledge_db.upsert_pnl_corr(a_id, b_id, r, n_overlap)

            if abs(r) >= threshold:
                high_corr_pairs.append({
                    "alpha_a": a_id,
                    "alpha_b": b_id,
                    "pearson": r,
                    "n_overlap": n_overlap,
                })

    return high_corr_pairs
