"""Prospective denominators, buyer diagnostics, and distinct future relevance."""

import hashlib
import uuid
from datetime import date

import numpy as np
from psycopg.types.json import Jsonb

from hm_menswear.evaluation.metrics import coverage, mean_or_none, ranking_scores
from hm_menswear.evaluation.protocol import validate_protocol
from hm_menswear.extraction.source import canonical_json
from hm_menswear.recommendation.snapshot import require_coverage
from hm_menswear.safety import PipelineError


def read_labels(conn, model, split, protocol):
    window = protocol[split]
    if model["manifest"]["cutoff"] != window["cutoff"]:
        raise PipelineError("model_cutoff_does_not_match_evaluation_split")
    release = uuid.UUID(model["manifest"]["release_id"])
    labels = {}
    digest = hashlib.sha256()
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        require_coverage(
            conn, release, date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
        )
        rows = conn.execute(
            "SELECT DISTINCT customer_id,article_id FROM mart.purchase_events WHERE release_id=%s AND purchase_date>=%s AND purchase_date<%s ORDER BY customer_id,article_id",
            (release, window["start"], window["end"]),
        )
        for customer, article in rows:
            customer = customer.encode("ascii")
            article = article.encode("ascii")
            labels.setdefault(customer, set()).add(article)
            digest.update(customer + b":" + article + b"\n")
    return labels, digest.hexdigest()


def evaluate_rankings(model, labels, k=12):
    arrays = model["arrays"]
    known = arrays["known_ids"]
    warm = arrays["warm_ids"]
    articles = arrays["articles"]
    predictions = arrays["predictions"]
    pop = arrays["popularity"]
    candidate_ids = set(articles.tolist())
    names = [
        "primary",
        "warm",
        "cold",
        "buyers_known",
        "buyers_warm",
        "buyers_cold",
        "future_first_buyers",
    ]
    totals = {name: {"ap": 0.0, "recall": 0.0, "buyers": 0, "exposure": set()} for name in names}
    unavailable = set()
    unavailable_pairs = 0
    attainable = 0.0
    known_buyers = 0
    for customer, relevant in labels.items():
        known_index = int(np.searchsorted(known, customer))
        is_known = known_index < len(known) and known[known_index] == customer
        warm_index = int(np.searchsorted(warm, customer))
        is_warm = warm_index < len(warm) and warm[warm_index] == customer
        chosen = predictions[warm_index] if is_warm else pop
        ap, recall = ranking_scores(articles[chosen].tolist(), relevant, k)
        missing = relevant - candidate_ids
        unavailable.update(missing)
        unavailable_pairs += len(missing)
        if is_known:
            known_buyers += 1
            attainable += len(relevant & candidate_ids) / len(relevant)
            group = "warm" if is_warm else "cold"
            cohorts = ["primary", group, "buyers_known", "buyers_" + group]
        else:
            cohorts = ["future_first_buyers"]
        for cohort in cohorts:
            total = totals[cohort]
            total["ap"] += ap
            total["recall"] += recall
            total["buyers"] += 1
            total["exposure"].update(chosen.tolist())
    sizes = {
        "primary": len(known),
        "warm": len(warm),
        "cold": len(known) - len(warm),
        "buyers_known": known_buyers,
        "buyers_warm": totals["buyers_warm"]["buyers"],
        "buyers_cold": totals["buyers_cold"]["buyers"],
        "future_first_buyers": totals["future_first_buyers"]["buyers"],
    }
    warm_exposure = set(np.unique(predictions).tolist())
    totals["warm"]["exposure"] = warm_exposure
    totals["cold"]["exposure"] = set(pop.tolist()) if sizes["cold"] else set()
    totals["primary"]["exposure"] = warm_exposure | totals["cold"]["exposure"]
    cohorts = {}
    for name in names:
        values = totals[name]
        population = sizes[name]
        cohorts[name] = {
            "population": population,
            "future_buyers": values["buyers"],
            "no_future_purchase_customers": population - values["buyers"],
            "map_at_12": mean_or_none(values["ap"], population),
            "recall_at_12": mean_or_none(values["recall"], population),
            "catalog_coverage_at_12": coverage(
                values["exposure"], range(len(articles)), population
            ),
        }
    return {
        "cutoff": model["manifest"]["cutoff"],
        "candidate_count": len(articles),
        "k": k,
        "cohorts": cohorts,
        "future_label_customers": len(labels),
        "distinct_relevant_articles": len(set().union(*labels.values())) if labels else 0,
        "future_articles_without_past_evidence": len(unavailable),
        "customer_item_labels_without_past_evidence": unavailable_pairs,
        "attainable_recall_among_known_buyers": mean_or_none(attainable, known_buyers),
        "no_future_purchase_convention": "zero_ap_and_recall",
        "relevance": "distinct_articles_including_unavailable",
    }


def evaluate_model(conn, model, protocol, *, split="validation", test_session=None):
    validate_protocol(protocol)
    if split not in ("validation", "test"):
        raise PipelineError("unsupported_evaluation_split")
    if split == "test":
        raise PipelineError("reserved_test_requires_frozen_comparison_workflow")
    if (
        model["manifest"]["protocol_sha256"]
        != hashlib.sha256(canonical_json(protocol).encode()).hexdigest()
    ):
        raise PipelineError("model_protocol_mismatch")
    labels, label_digest = read_labels(conn, model, split, protocol)
    report = evaluate_rankings(model, labels, protocol["k"])
    report.update(
        model_id=model["model_id"],
        family=model["manifest"]["family"],
        parameters=model["manifest"]["parameters"],
        split=split,
        label_snapshot_sha256=label_digest,
        protocol_sha256=hashlib.sha256(canonical_json(protocol).encode()).hexdigest(),
    )
    with conn.transaction():
        conn.execute(
            "INSERT INTO evaluation.runs(evaluation_id,model_id,protocol_sha256,config_sha256,split,test_session_id,cohort_counts,metrics) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                uuid.uuid4(),
                model["model_id"],
                report["protocol_sha256"],
                hashlib.sha256(canonical_json(report["parameters"]).encode()).hexdigest(),
                split,
                test_session,
                Jsonb({name: value["population"] for name, value in report["cohorts"].items()}),
                Jsonb(report),
            ),
        )
    return report
