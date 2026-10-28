"""Ranking metrics with explicit empty-relevance and empty-population conventions."""

from hm_menswear.safety import PipelineError


def ranking_scores(predictions, relevant, k=12):
    predictions = list(predictions)
    if len(predictions) > k or len(predictions) != len(set(predictions)):
        raise PipelineError("predictions_must_be_unique_and_at_most_k")
    relevant = set(relevant)
    if not relevant:
        return 0.0, 0.0
    hits = 0
    precision_sum = 0.0
    for rank, item in enumerate(predictions, 1):
        if item in relevant:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / min(k, len(relevant)), hits / len(relevant)


def mean_or_none(total, denominator):
    return total / denominator if denominator else None


def coverage(items, candidates, population_size):
    items = set(items)
    candidates = set(candidates)
    if not population_size or not candidates:
        return None
    if not set(items) <= set(candidates):
        raise PipelineError("recommendation_outside_candidate_universe")
    return len(set(items)) / len(set(candidates))
