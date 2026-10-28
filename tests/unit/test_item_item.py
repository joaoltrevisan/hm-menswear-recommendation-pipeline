"""Independent small binary-support/cosine examples and deterministic ranking."""

from datetime import date, timedelta

import numpy as np
import pytest
from scipy.sparse import csr_array

from hm_menswear.recommendation.artifacts import recommend
from hm_menswear.recommendation.item_item import fit_item_item
from hm_menswear.recommendation.snapshot import Snapshot


def snapshot(users, items, *, days=None, n_users=None, n_items=None):
    n_users = max(users) + 1 if n_users is None else n_users
    n_items = max(items) + 1 if n_items is None else n_items
    ids = np.array([f"{u:064x}" for u in range(n_users)], dtype="S64")
    return Snapshot(
        "synthetic",
        "2020-09-08",
        ids,
        ids.copy(),
        np.array([f"{i:010}" for i in range(n_items)], dtype="S10"),
        np.array(users, dtype=np.int32),
        np.array(items, dtype=np.int32),
        np.full(len(users), date(2020, 9, 8).toordinal(), dtype=np.int32)
        if days is None
        else np.array(days, dtype=np.int32),
    ).validate()


def graph(fitted, size):
    return csr_array(
        (fitted["graph_values"], fitted["graph_indices"], fitted["graph_indptr"]),
        shape=(size, size),
    )


def test_binary_cosine_support_no_diagonal_and_history_fallback():
    s = snapshot([0, 0, 0, 1, 1, 1, 2, 2, 3], [0, 1, 1, 0, 1, 2, 1, 2, 3])
    r = fit_item_item(s, 90, 20, 7, 7, block_size=1)
    g = graph(r, 4)
    assert g.nnz == 4
    assert g[0, 1] == pytest.approx(2 / np.sqrt(6))
    assert g[1, 2] == pytest.approx(2 / np.sqrt(6))
    assert g[0, 2] == 0 and not g.diagonal().any()
    assert r["personalized"].tolist() == [True, True, True, False]
    assert r["predictions"][0].tolist() == [1, 0, 2, 3]
    assert r["predictions"][3].tolist() == [3, 1, 0, 2]
    model = {
        "model_id": "synthetic",
        "manifest": {"cutoff": s.cutoff, "family": "item_item"},
        "arrays": {"known_ids": s.known_ids, "warm_ids": s.warm_ids, "articles": s.articles, **r},
    }
    assert recommend(model, f"{3:064x}")["strategy"] == "insufficient_item_signal_history_fallback"
    assert recommend(model, f"{0:064x}")["strategy"] == "item_item"
    assert all(len(set(row)) == 4 for row in r["predictions"].tolist())
    from hm_menswear.evaluation.evaluate import evaluate_rankings

    report = evaluate_rankings(model, {s.warm_ids[0]: {s.articles[0]}})
    assert report["recommendation_paths_primary"]["warm_item_item"] == 3
    assert report["recommendation_paths_primary"]["warm_history_fallback"] == 1
    assert sum(report["recommendation_paths_primary"].values()) == 4
    assert sum(report["recommendation_paths_known_buyers"].values()) == 1


def test_top_neighbors_ties_are_item_id_order_and_block_size_invariant():
    s = snapshot([0] * 26 + [1] * 26, list(range(26)) * 2)
    a = fit_item_item(s, 90, 20, 7, 7, block_size=3)
    b = fit_item_item(s, 90, 20, 7, 7, block_size=128)
    g = graph(a, 26)
    assert g.indices[:20].tolist() == list(range(1, 21))
    assert np.all(np.diff(g.indptr) == 20)
    for key in a:
        np.testing.assert_array_equal(a[key], b[key])


def test_window_includes_cutoff_minus_89_and_excludes_cutoff_minus_90():
    cutoff = date(2020, 9, 8)
    s = snapshot(
        [0, 0, 1, 1, 2, 2, 3, 3],
        [0, 1, 0, 1, 2, 3, 2, 3],
        days=[(cutoff - timedelta(days=d)).toordinal() for d in [89, 89, 89, 89, 90, 90, 90, 90]],
    )
    r = fit_item_item(s, 90, 20, 7, 7)
    g = graph(r, 4)
    assert g[0, 1] == 1 and g[2, 3] == 0
    assert r["personalized"].tolist() == [True, True, False, False]
