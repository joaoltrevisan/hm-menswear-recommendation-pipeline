"""Deterministic recent popularity and repeat-history, with explicit repeat allowance."""

from datetime import date

import numpy as np

from hm_menswear.safety import PipelineError


def popularity(snapshot, window_days, k=12):
    if window_days not in (7, 14, 28):
        raise PipelineError("unsupported_popularity_window")
    size = len(snapshot.articles)
    lifetime = np.bincount(snapshot.items, minlength=size)
    lower = date.fromisoformat(snapshot.cutoff).toordinal() - window_days + 1
    recent = np.bincount(snapshot.items[snapshot.days >= lower], minlength=size)
    order = np.lexsort((np.arange(size), -lifetime, -recent)).astype(np.int32)
    return order[: min(k, size)], recent


def repeat_history(snapshot, pop, k=12):
    width = min(k, len(snapshot.articles))
    n_users = len(snapshot.warm_ids)
    predictions = np.empty((n_users, width), dtype=np.int32)
    if not width:
        return predictions
    pairs = snapshot.users.astype(np.int64) * len(snapshot.articles) + snapshot.items
    unique, inverse = np.unique(pairs, return_inverse=True)
    users = (unique // len(snapshot.articles)).astype(np.int32)
    items = (unique % len(snapshot.articles)).astype(np.int32)
    counts = np.bincount(inverse)
    latest = np.full(len(unique), -1, dtype=np.int32)
    np.maximum.at(latest, inverse, snapshot.days)
    order = np.lexsort((items, -counts, -latest, users))
    ordered_items = items[order]
    indptr = np.r_[0, np.cumsum(np.bincount(users, minlength=n_users))]
    for user in range(n_users):
        selected = list(ordered_items[indptr[user] : indptr[user + 1]][:width])
        seen = set(selected)
        for item in pop:
            if len(selected) >= width:
                break
            if item not in seen:
                selected.append(item)
                seen.add(item)
        predictions[user] = selected
    return predictions


def fit_baseline(snapshot, family, window_days, k=12):
    snapshot.validate()
    pop, recent = popularity(snapshot, window_days, k)
    if family == "popularity":
        predictions = np.tile(pop, (len(snapshot.warm_ids), 1))
    elif family == "repeat_history":
        predictions = repeat_history(snapshot, pop, k)
    else:
        raise PipelineError("unsupported_baseline_family")
    return {"predictions": predictions, "popularity": pop, "recent_counts": recent}
