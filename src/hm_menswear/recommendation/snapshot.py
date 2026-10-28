"""Event-date as-of training inputs; no customer metadata or future catalogue features."""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from hm_menswear.extraction.source import canonical_json
from hm_menswear.safety import PipelineError
from hm_menswear.validation.values import valid_date


def require_coverage(conn, release, start, end):
    windows = conn.execute(
        "SELECT batch_id,start_date,end_date FROM control.batches WHERE release_id=%s AND status='completed' AND start_date<%s AND end_date>%s ORDER BY start_date,end_date",
        (release, end, start),
    ).fetchall()
    cursor = start
    trace = []
    for batch, left, right in windows:
        if left > cursor:
            raise PipelineError("incomplete_temporal_coverage")
        cursor = max(cursor, min(right, end))
        trace.append(
            {
                "batch_id": str(batch),
                "start": max(left, start).isoformat(),
                "end": min(right, end).isoformat(),
            }
        )
    if cursor < end:
        raise PipelineError("incomplete_temporal_coverage")
    return trace


@dataclass
class Snapshot:
    release_id: str
    cutoff: str
    known_ids: np.ndarray = field(repr=False)
    warm_ids: np.ndarray = field(repr=False)
    articles: np.ndarray = field(repr=False)
    users: np.ndarray = field(repr=False)
    items: np.ndarray = field(repr=False)
    days: np.ndarray = field(repr=False)
    metadata: dict = field(repr=False, default_factory=dict)
    fingerprint: str = ""

    def validate(self):
        if (
            not valid_date(self.cutoff)
            or len(self.users) != len(self.items)
            or len(self.items) != len(self.days)
        ):
            raise PipelineError("invalid_training_snapshot")
        for values in [self.known_ids, self.warm_ids, self.articles]:
            if len(values) > 1 and not np.all(values[:-1] < values[1:]):
                raise PipelineError("snapshot_ids_not_unique_sorted")
        if len(self.days) and (
            self.days.max() > date.fromisoformat(self.cutoff).toordinal()
            or self.users.min() < 0
            or self.users.max() >= len(self.warm_ids)
            or self.items.min() < 0
            or self.items.max() >= len(self.articles)
        ):
            raise PipelineError("future_or_invalid_training_event")
        if len(self.warm_ids) != len(np.unique(self.users)):
            raise PipelineError("warm_customer_without_past_evidence")
        if len(self.articles) != len(np.unique(self.items)):
            raise PipelineError("candidate_without_past_evidence")
        if len(self.warm_ids):
            indices = np.searchsorted(self.known_ids, self.warm_ids)
            if np.any(indices >= len(self.known_ids)) or not np.array_equal(
                self.known_ids[indices], self.warm_ids
            ):
                raise PipelineError("warm_customer_not_known_at_cutoff")
        digest = hashlib.sha256(
            canonical_json(
                {"release_id": self.release_id, "cutoff": self.cutoff, "metadata": self.metadata}
            ).encode()
        )
        for values in [
            self.known_ids,
            self.warm_ids,
            self.articles,
            self.users,
            self.items,
            self.days,
        ]:
            digest.update(
                str(values.dtype).encode() + str(values.shape).encode() + values.tobytes()
            )
        self.fingerprint = digest.hexdigest()
        return self


def _id_array(conn, query, params, dtype):
    with conn.cursor(name="ids_" + uuid.uuid4().hex) as cursor:
        cursor.itersize = 50000
        cursor.execute(query, params)
        return np.fromiter((row[0].encode("ascii") for row in cursor), dtype=dtype)


def build_snapshot(conn, cutoff, protocol):
    if not valid_date(cutoff) or not protocol["source_start"] <= cutoff <= protocol["source_end"]:
        raise PipelineError("cutoff_outside_observed_source")
    end = date.fromisoformat(cutoff) + timedelta(days=1)
    start = date.fromisoformat(protocol["source_start"])
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        release = conn.execute(
            "SELECT active_release_id FROM control.lineage WHERE singleton"
        ).fetchone()[0]
        if release is None:
            raise PipelineError("no_active_source_release")
        windows = require_coverage(conn, release, start, end)
        manifest = conn.execute(
            "SELECT manifest_sha256 FROM control.releases WHERE release_id=%s", (release,)
        ).fetchone()[0]
        known = _id_array(
            conn,
            "SELECT customer_id FROM mart.customer_observations WHERE release_id=%s AND first_observed_date<=%s ORDER BY customer_id",
            (release, cutoff),
            "S64",
        )
        bounds = (release, start, cutoff)
        warm = _id_array(
            conn,
            "SELECT DISTINCT customer_id FROM mart.purchase_events WHERE release_id=%s AND purchase_date>=%s AND purchase_date<=%s ORDER BY customer_id",
            bounds,
            "S64",
        )
        articles = _id_array(
            conn,
            "SELECT DISTINCT article_id FROM mart.purchase_events WHERE release_id=%s AND purchase_date>=%s AND purchase_date<=%s ORDER BY article_id",
            bounds,
            "S10",
        )
        user_parts = []
        item_parts = []
        day_parts = []
        with conn.cursor(name="past_events") as cursor:
            cursor.execute(
                "SELECT customer_id,article_id,purchase_date FROM mart.purchase_events WHERE release_id=%s AND purchase_date>=%s AND purchase_date<=%s ORDER BY transaction_file_id,source_record_number",
                bounds,
            )
            while rows := cursor.fetchmany(50000):
                user_parts.append(
                    np.searchsorted(warm, np.array([r[0] for r in rows], dtype="S64")).astype(
                        np.int32
                    )
                )
                item_parts.append(
                    np.searchsorted(articles, np.array([r[1] for r in rows], dtype="S10")).astype(
                        np.int32
                    )
                )
                day_parts.append(
                    np.fromiter((r[2].toordinal() for r in rows), dtype=np.int32, count=len(rows))
                )

        def combine(parts):
            return np.concatenate(parts) if parts else np.empty(0, dtype=np.int32)

        metadata = {
            "source_manifest_sha256": manifest,
            "committed_windows": windows,
            "customer_metadata_used": False,
            "taxonomy": "static_scope_only",
            "availability": "past_purchase_evidence_only",
            "time_basis": "source_event_date_not_real_ingestion_delay",
        }
        return Snapshot(
            str(release),
            cutoff,
            known,
            warm,
            articles,
            combine(user_parts),
            combine(item_parts),
            combine(day_parts),
            metadata,
        ).validate()
