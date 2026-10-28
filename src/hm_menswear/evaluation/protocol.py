"""Versioned seven-day split contract; reject accidental overlapping label windows."""

import json
from datetime import date, timedelta
from pathlib import Path

from hm_menswear.safety import PipelineError
from hm_menswear.validation.values import valid_date


def validate_protocol(protocol):
    try:
        if protocol["k"] != 12 or protocol["version"] != "menswear-seven-day-v1":
            raise ValueError
        if not all(valid_date(protocol[key]) for key in ["source_start", "source_end"]):
            raise ValueError
        start = date.fromisoformat(protocol["source_start"])
        last = date.fromisoformat(protocol["source_end"])
        if start > last:
            raise ValueError
        for split in ["validation", "test"]:
            window = protocol[split]
            if not all(valid_date(window[key]) for key in ["cutoff", "start", "end"]):
                raise ValueError
            cutoff = date.fromisoformat(window["cutoff"])
            left = date.fromisoformat(window["start"])
            right = date.fromisoformat(window["end"])
            if (
                not start <= cutoff < left < right <= last + timedelta(days=1)
                or left != cutoff + timedelta(days=1)
                or right != left + timedelta(days=7)
            ):
                raise ValueError
        if (
            protocol["validation"]["end"] > protocol["test"]["start"]
            or protocol["test"]["cutoff"] < protocol["validation"]["cutoff"]
        ):
            raise ValueError
        if (
            protocol["population"] != "any_segment_identity_observed_by_cutoff"
            or protocol["candidates"] != "menswear_purchased_by_cutoff"
            or protocol["relevance"] != "distinct_future_menswear_articles_including_unavailable"
            or protocol["no_future_purchase"] != "zero_ap_and_recall_in_primary_population"
        ):
            raise ValueError
        if protocol["popularity_windows"] != [7, 14, 28] or protocol["family_tie_order"] != [
            "popularity",
            "repeat_history",
            "item_item",
        ]:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise PipelineError("invalid_temporal_evaluation_protocol") from None
    if (
        protocol.get("item_training_windows") != [90, 180]
        or protocol.get("neighbors") != [20, 50]
        or protocol.get("minimum_pair_support") != 2
        or protocol.get("repeat_purchase_recommendations") is not True
    ):
        raise PipelineError("invalid_temporal_evaluation_protocol")
    return protocol


def load_protocol(path="config/evaluation.json"):
    return validate_protocol(json.loads(Path(path).read_text()))
