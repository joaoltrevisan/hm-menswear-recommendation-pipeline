"""Manual metric arithmetic and deterministic, strictly past-only ranking fixtures."""

from datetime import date
from fractions import Fraction

import numpy as np
import pytest

from hm_menswear.evaluation.evaluate import evaluate_rankings
from hm_menswear.evaluation.metrics import coverage, ranking_scores
from hm_menswear.recommendation.baselines import fit_baseline
from hm_menswear.recommendation.snapshot import Snapshot
from hm_menswear.safety import PipelineError


def synthetic_snapshot():
    cutoff = "2020-09-08"
    return Snapshot(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        cutoff,
        np.array(["a" * 64, "b" * 64], dtype="S64"),
        np.array(["a" * 64], dtype="S64"),
        np.array(["0000000001", "0000000002", "0000000003"], dtype="S10"),
        np.array([0, 0, 0, 0], dtype=np.int32),
        np.array([0, 0, 1, 2], dtype=np.int32),
        np.array(
            [
                date(2020, 9, 1).toordinal(),
                date(2020, 9, 1).toordinal(),
                date(2020, 9, 7).toordinal(),
                date(2020, 9, 7).toordinal(),
            ],
            dtype=np.int32,
        ),
    ).validate()


def test_manual_known_ap_recall_and_coverage():
    ap, recall = ranking_scores(["A", "X", "B"], {"A", "B", "C"})
    assert ap == pytest.approx(float(Fraction(5, 9)))
    assert recall == pytest.approx(float(Fraction(2, 3)))
    assert (ap + ranking_scores([], set())[0]) / 2 == pytest.approx(float(Fraction(5, 18)))
    assert coverage({"A", "X", "B"}, {"A", "B", "X", "Y", "Z"}, 2) == 3 / 5
    assert coverage(set(), set(), 0) is None


def test_more_than_twelve_relevant_items_and_duplicate_labels():
    predictions = list(range(12))
    relevant = list(range(20)) + [0, 0]
    assert ranking_scores(predictions, relevant) == (1, 12 / 20)
    assert ranking_scores([], {"A"}) == (0, 0)
    assert ranking_scores(["X"], set()) == (0, 0)
    with pytest.raises(PipelineError):
        ranking_scores(["A", "A"], {"A"})


def test_popularity_window_boundary_and_deterministic_ties():
    snapshot = synthetic_snapshot()
    model = fit_baseline(snapshot, "popularity", 7)
    assert model["popularity"].tolist() == [1, 2, 0]
    assert model["recent_counts"].tolist() == [0, 1, 1]
    assert np.array_equal(
        model["predictions"], fit_baseline(snapshot, "popularity", 7)["predictions"]
    )


def test_repeat_history_last_date_then_counts_then_id_and_repeat_allowed():
    snapshot = synthetic_snapshot()
    model = fit_baseline(snapshot, "repeat_history", 7)
    assert model["predictions"].tolist() == [[1, 2, 0]]
    assert len(set(model["predictions"][0])) == 3


def test_snapshot_cannot_contain_future_events_or_future_candidates():
    snapshot = synthetic_snapshot()
    snapshot.days[-1] = date(2020, 9, 9).toordinal()
    with pytest.raises(PipelineError, match="future"):
        snapshot.validate()
    snapshot = synthetic_snapshot()
    snapshot.articles = np.append(snapshot.articles, np.array(["0000000004"], dtype="S10"))
    with pytest.raises(PipelineError, match="candidate_without_past"):
        snapshot.validate()


def test_future_only_labels_stay_in_denominator_and_no_buyers_are_zero():
    snapshot = synthetic_snapshot()
    fitted = fit_baseline(snapshot, "repeat_history", 7)
    model = {
        "manifest": {"cutoff": snapshot.cutoff},
        "arrays": {
            "known_ids": snapshot.known_ids,
            "warm_ids": snapshot.warm_ids,
            "articles": snapshot.articles,
            **fitted,
        },
    }
    labels = {b"a" * 64: {b"0000000002", b"0000000009"}, b"c" * 64: {b"0000000009"}}
    report = evaluate_rankings(model, labels)
    assert report["cohorts"]["primary"]["population"] == 2
    assert report["cohorts"]["primary"]["no_future_purchase_customers"] == 1
    assert report["cohorts"]["primary"]["map_at_12"] == 0.25
    assert report["cohorts"]["primary"]["recall_at_12"] == 0.25
    assert report["cohorts"]["buyers_known"]["map_at_12"] == 0.5
    assert report["cohorts"]["future_first_buyers"]["population"] == 1
    assert report["future_articles_without_past_evidence"] == 1
    assert report["customer_item_labels_without_past_evidence"] == 2


def test_history_fills_from_popularity_without_repeating_items():
    snapshot = Snapshot(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "2020-09-08",
        np.array(["a" * 64, "b" * 64, "c" * 64], dtype="S64"),
        np.array(["a" * 64, "b" * 64], dtype="S64"),
        np.array(["0000000001", "0000000002"], dtype="S10"),
        np.array([0, 0, 1], dtype=np.int32),
        np.array([0, 0, 1], dtype=np.int32),
        np.array(
            [
                date(2020, 9, 1).toordinal(),
                date(2020, 9, 2).toordinal(),
                date(2020, 9, 3).toordinal(),
            ],
            dtype=np.int32,
        ),
    ).validate()
    fitted = fit_baseline(snapshot, "repeat_history", 7)
    assert fitted["predictions"].tolist() == [[0, 1], [1, 0]]


def test_empty_candidates_and_empty_populations_are_explicit():
    def model(known):
        empty = np.empty(0, dtype=np.int32)
        return {
            "manifest": {"cutoff": "2020-09-08"},
            "arrays": {
                "known_ids": np.array(known, dtype="S64"),
                "warm_ids": np.empty(0, dtype="S64"),
                "articles": np.empty(0, dtype="S10"),
                "predictions": np.empty((0, 0), dtype=np.int32),
                "popularity": empty,
            },
        }

    report = evaluate_rankings(model(["a" * 64]), {b"a" * 64: {b"0000000001"}})
    assert report["cohorts"]["primary"]["map_at_12"] == 0
    assert report["cohorts"]["primary"]["catalog_coverage_at_12"] is None
    report = evaluate_rankings(model([]), {})
    assert report["cohorts"]["primary"]["map_at_12"] is None
    assert report["cohorts"]["primary"]["recall_at_12"] is None


@pytest.mark.parametrize("field,value", [("start", "2020-09-08"), ("end", "2020-09-17")])
def test_protocol_rejects_overlapping_or_wrong_length_labels(field, value):
    from hm_menswear.evaluation.protocol import load_protocol, validate_protocol

    protocol = load_protocol()
    protocol["validation"][field] = value
    with pytest.raises(PipelineError, match="invalid_temporal_evaluation_protocol"):
        validate_protocol(protocol)
