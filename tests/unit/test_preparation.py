"""Synthetic CSV contracts, temporal formats, preserved occurrences and null semantics."""

import json
import sqlite3

import pytest

from hm_menswear.extraction.source import capture_sources, records, strict_count
from hm_menswear.safety import PipelineError
from hm_menswear.transformation.prepare import build_artifact
from tests.synthetic_source import write_source


def prepare(tmp_path, transactions=None, chunk_size=2):
    raw = tmp_path / "raw"
    work = tmp_path / "work"
    contract = write_source(raw, transactions=transactions)
    manifest = capture_sources(raw, work, contract=contract, pinned=False)
    metadata = build_artifact(manifest, work / "prepared", chunk_size)
    return metadata, work / "prepared" / "prepared.sqlite"


def test_logical_ordinals_zeros_duplicates_scope_and_optional_values(tmp_path):
    metadata, path = prepare(tmp_path)
    assert metadata["summary"]["valid_menswear_rows"] == 4
    assert metadata["summary"]["valid_out_of_scope_rows"] == 1
    assert metadata["summary"]["identical_purchase_groups"] == 1
    assert metadata["summary"]["additional_identical_occurrences"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT ordinal FROM purchases ORDER BY ordinal").fetchall() == [
            (1,),
            (2,),
            (3,),
            (5,),
        ]
        assert (
            db.execute("SELECT article_id FROM purchases WHERE ordinal=1").fetchone()[0]
            == "0000000001"
        )
        attrs = json.loads(
            db.execute("SELECT attributes FROM customers WHERE ordinal=1").fetchone()[0]
        )
        assert attrs["FN"] is None and attrs["Active"] is None
        assert attrs["fashion_news_frequency"] == "None"
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 3
        assert (
            "multiline"
            in json.loads(
                db.execute("SELECT attributes FROM catalog WHERE ordinal=4").fetchone()[0]
            )["detail_desc"]
        )


@pytest.mark.parametrize("token", ["2020-02-30", "09/01/2020", "2020/09/01", "2020-9-01", ""])
def test_invalid_heterogeneous_missing_dates_are_rejected_once(tmp_path, token):
    metadata, path = prepare(tmp_path, [[token, "a" * 64, "0000000001", "0.01", "1"]])
    assert metadata["summary"]["rejected_rows"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM purchases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM rejections").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 0


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "", "١", "1e1000000", "1e-1000000"])
def test_prices_reject_but_valid_identity_observation_is_retained(tmp_path, price):
    metadata, path = prepare(tmp_path, [["2020-09-01", "a" * 64, "0000000001", price, "1"]])
    assert metadata["summary"]["rejected_rows"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 1


def test_duplicate_dimension_ids_fail_entire_preparation(tmp_path):
    raw = tmp_path / "raw"
    work = tmp_path / "work"
    contract = write_source(raw, duplicate_customer=True)
    manifest = capture_sources(raw, work, contract=contract, pinned=False)
    with pytest.raises(PipelineError, match="duplicate_dimension_identifier"):
        build_artifact(manifest, work / "partial", 2)


@pytest.mark.parametrize(
    "contents", ["a,b\n1\n", "a,b\n1,2,3\n", 'a,b\n"unterminated,2', "a,a\n1,2\n", "a,b\n1,\x00\n"]
)
def test_structural_corruption_never_skips_rows(tmp_path, contents):
    path = tmp_path / "synthetic.csv"
    path.write_text(contents)
    with pytest.raises(PipelineError):
        strict_count(path, ["a", "b"])


def test_chunk_size_does_not_change_multiline_record_identity(tmp_path):
    raw = tmp_path / "raw"
    contract = write_source(raw)
    columns = contract["files"]["articles.csv"]["columns"]
    assert list(records(raw / "articles.csv", columns, 1)) == list(
        records(raw / "articles.csv", columns, 3)
    )


def test_originals_unchanged_and_changed_bytes_rejected_by_pinned_manifest(tmp_path):
    raw = tmp_path / "raw"
    contract = write_source(raw)
    originals = {name: (raw / name).read_bytes() for name in contract["files"]}
    with pytest.raises(PipelineError, match="source_digest_mismatch"):
        capture_sources(raw, tmp_path / "work", contract=contract, pinned=True)
    assert all((raw / name).read_bytes() == value for name, value in originals.items())


def test_zero_prices_and_unknown_references_have_explicit_dispositions(tmp_path):
    rows = [
        ["2020-09-01", "a" * 64, "0000000001", "0", "1"],
        ["2020-09-01", "f" * 64, "0000000001", "0.01", "1"],
        ["2020-09-01", "a" * 64, "0000000099", "0.01", "1"],
    ]
    metadata, path = prepare(tmp_path, rows)
    assert metadata["summary"]["valid_menswear_rows"] == 1
    assert metadata["summary"]["rejected_rows"] == 2
    with sqlite3.connect(path) as db:
        assert set(r[0] for r in db.execute("SELECT primary_reason FROM rejections")) == {
            "unknown_customer_reference",
            "unknown_article_reference",
        }


def test_valid_leap_day_is_preserved(tmp_path):
    metadata, path = prepare(tmp_path, [["2020-02-29", "a" * 64, "0000000001", "0.000001", "1"]])
    assert metadata["summary"]["valid_menswear_rows"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT purchase_date,price FROM purchases").fetchone() == (
            "2020-02-29",
            "0.000001",
        )
