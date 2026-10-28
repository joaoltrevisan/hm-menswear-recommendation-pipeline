"""Small independently fabricated source files, never copied source customer records."""

import csv
from pathlib import Path

from hm_menswear.extraction.source import source_contract


def write_source(directory, *, transactions=None, duplicate_customer=False):
    directory = Path(directory)
    directory.mkdir(parents=True)
    contract = source_contract()
    contract["namespace"] = "synthetic-test-source"
    columns = contract["files"]["articles.csv"]["columns"]
    articles = []
    for article, scope, description in [
        ("0000000001", "Menswear", "Synthetic basic"),
        ("0000000002", "Divided", "Synthetic excluded"),
        ("0000000003", "Sport", "Synthetic excluded"),
        ("0000000004", "Menswear", "Synthetic, quoted\nmultiline"),
    ]:
        row = {name: "" for name in columns}
        row.update(article_id=article, index_group_name=scope, detail_desc=description)
        articles.append([row[name] for name in columns])
    customers = [
        ["a" * 64, "", "", "ACTIVE", "None", "49.0", "synthetic-postal"],
        ["b" * 64, "1.0", "1.0", "", "", "", "synthetic-postal"],
        ["c" * 64, "", "", "", "NONE", "", "synthetic-postal"],
    ]
    if duplicate_customer:
        customers.append(customers[0])
    transactions = (
        transactions
        if transactions is not None
        else [
            ["2020-09-01", "a" * 64, "0000000001", "0.01", "1"],
            ["2020-09-01", "a" * 64, "0000000001", "0.01", "1"],
            ["2020-09-08", "a" * 64, "0000000001", "0.02", "2"],
            ["2020-09-02", "b" * 64, "0000000002", "0.03", "1"],
            ["2020-09-09", "c" * 64, "0000000004", "0.04", "2"],
        ]
    )
    for name, rows in [
        ("articles.csv", articles),
        ("customers.csv", customers),
        ("transactions_train.csv", transactions),
    ]:
        with (directory / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(contract["files"][name]["columns"])
            writer.writerows(rows)
    return contract
