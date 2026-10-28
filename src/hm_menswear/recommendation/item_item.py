"""Sparse binary item-item cosine; bounded item and customer blocks."""

from datetime import date

import numpy as np
from scipy.sparse import csr_array

from hm_menswear.recommendation.baselines import popularity, repeat_history
from hm_menswear.safety import PipelineError


def fit_item_item(
    snapshot,
    training_days,
    neighbors,
    popularity_days,
    history_days,
    *,
    minimum_pair_support=2,
    k=12,
    block_size=128,
):
    snapshot.validate()
    if training_days not in (90, 180) or neighbors not in (20, 50) or minimum_pair_support != 2:
        raise PipelineError("unsupported_item_item_configuration")
    size = len(snapshot.articles)
    users = len(snapshot.warm_ids)
    lower = date.fromisoformat(snapshot.cutoff).toordinal() - training_days + 1
    keep = snapshot.days >= lower
    matrix = csr_array(
        (np.ones(int(keep.sum()), dtype=np.float64), (snapshot.users[keep], snapshot.items[keep])),
        shape=(users, size),
    )
    matrix.sum_duplicates()
    matrix.data[:] = 1.0
    counts = np.asarray(matrix.sum(axis=0)).ravel()
    graph_indices, graph_values, graph_ptr = [], [], [0]
    for left in range(0, size, block_size):
        cooccurrence = (matrix[:, left : left + block_size].T @ matrix).tocsr()
        for local in range(cooccurrence.shape[0]):
            item = left + local
            a, b = cooccurrence.indptr[local : local + 2]
            ids, support = cooccurrence.indices[a:b], cooccurrence.data[a:b]
            valid = (ids != item) & (support >= minimum_pair_support)
            ids, support = ids[valid], support[valid]
            scores = support / np.sqrt(counts[item] * counts[ids])
            order = np.lexsort((ids, -scores))[:neighbors]
            graph_indices.extend(ids[order])
            graph_values.extend(scores[order])
            graph_ptr.append(len(graph_indices))
    graph = csr_array(
        (
            np.asarray(graph_values),
            np.asarray(graph_indices, dtype=np.int32),
            np.asarray(graph_ptr, dtype=np.int64),
        ),
        shape=(size, size),
    )
    pop, recent = popularity(snapshot, history_days, k)
    _, tie_counts = popularity(snapshot, popularity_days, k)
    predictions = repeat_history(snapshot, pop, k)
    personalized = np.zeros(users, dtype=np.bool_)
    history_sizes = np.diff(matrix.indptr)
    width = min(k, size)
    for left in range(0, users, block_size):
        scores = (matrix[left : left + block_size] @ graph).tocsr()
        for local in range(scores.shape[0]):
            user = left + local
            if history_sizes[user] < 2:
                continue
            a, b = scores.indptr[local : local + 2]
            ids, values = scores.indices[a:b], scores.data[a:b]
            positive = values > 0
            ids, values = ids[positive], values[positive]
            if not len(ids):
                continue
            order = np.lexsort((ids, -tie_counts[ids], -values))
            selected = list(ids[order][:width])
            seen = set(selected)
            for item in predictions[user]:
                if len(selected) == width:
                    break
                if item not in seen:
                    selected.append(item)
                    seen.add(item)
            predictions[user] = selected
            personalized[user] = True
    return {
        "predictions": predictions,
        "popularity": pop,
        "recent_counts": tie_counts,
        "personalized": personalized,
        "graph_indptr": graph.indptr,
        "graph_indices": graph.indices,
        "graph_values": graph.data,
    }
