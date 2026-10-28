# Source assessment and independent reconciliation

Assessment date: 2026-10-28 (America/Sao_Paulo). Source: [official competition data](https://www.kaggle.com/competitions/h-and-m-personalized-fashion-recommendations/data). The user has already obtained all three files through authorized access; no new login, download, images or submission file is required.

This is an independent educational case study with a simulated service, not a commercial engagement or H&M affiliation. The [official competition overview](https://www.kaggle.com/c/h-and-m-personalized-fashion-recommendations/overview) records closure on May 9, 2022. No current prize participation is implied.

## Method and evidence limits

The implementer independently streamed the original bytes for SHA-256 and scanned every CSV with Python 3.14.7 standard-library `csv.reader(strict=True)`, preserving strings and checking record widths. Dimensions were checked for duplicate keys and required ID formats. Dates were validated against the calendar; distinct Menswear price tokens were parsed with `Decimal`. The five original transaction fields formed equality groups for measuring repeated occurrences only, never deletion. No original record was edited. Input size/mtime checks bracketed the scan. Source archives/CRC were not rechecked: the local inputs here are extracted CSVs, and the previous inventory's archive CRC is not claimed as a newly executed check.

A private inspection script and machine-readable aggregate report are retained alongside the local data under `stage_1_audit/`, outside this repository. The invocation is `python3 stage_1_audit/inspect_source.py <data-directory> <private-report.json>`. The script is an exploratory audit tool, not the future pandas pipeline and not a pytest test. Full production parsing, idempotency, SQL and temporal logic must receive their own automated tests in authorized stages.

The first comparison draft omitted window boundary metadata and consequently reported four comparison-field mismatches. The audit was corrected to include inclusive boundary labels corresponding to the scanned half-open intervals and rerun. This was an inspection-output defect, not a discrepancy in source data. Final measured results and hashes below agree with the supplied inventory. No claim is made that every conceivable defect or semantic ambiguity has been ruled out.

## Immutable file manifest

| File | Bytes | Data rows | Columns | SHA-256 |
| --- | --- | --- | --- | --- |
| `articles.csv` | 36,127,865 | 105,542 | 25 | `25f21882053517f7684ea43f524225a9481a7bb9aab9cf0abfc7fe8c4576a72b` |
| `customers.csv` | 207,135,859 | 1,371,980 | 7 | `abf3450c37ee1c16124e0d3379371153f5371148742efdcfe44c97c0445df6b2` |
| `transactions_train.csv` | 3,488,002,253 | 31,788,324 | 5 | `fff5e3b35c1b26016aa0bf2231be9525bc766eed32c94f1653420b465aef84fa` |

Headers match the supplied inventory. Purchase columns are `t_dat`, `customer_id`, `article_id`, `price`, `sales_channel_id`; customer columns are `customer_id`, `FN`, `Active`, `club_member_status`, `fashion_news_frequency`, `age`, `postal_code`. All catalog identifiers/codes will be preserved as text, including `article_id`, `product_code`, taxonomy codes, colour codes, department and garment codes; descriptive name fields and `detail_desc` are text. Original article IDs are ten digits with leading zero; customer IDs are 64 lowercase hexadecimal characters. No duplicate dimension IDs or malformed record widths were found.

## Confirmed scope and quality

| Observation | Recomputed result |
| --- | --- |
| Exact catalog scope | `index_group_name == "Menswear"` |
| Catalog counts by group | Menswear 12,553; Ladieswear 39,737; Baby/Children 34,711; Sport 3,392; Divided 15,149 |
| Menswear purchase occurrences | 1,771,053 |
| Distinct Menswear customers | 339,126 |
| Source and Menswear dates | 2018-09-20 through 2020-09-22; 734 distinct Menswear purchase dates |
| Unknown article references in full history | 0 |
| Unknown customer references | 0 in Menswear; independent scan also found 0 in full history |
| Empty transaction fields | 0 in full history and Menswear |
| Distinct invalid dates in full history | 0 |
| Invalid/nonfinite or negative distinct Menswear price tokens | 0 / 0 |
| Missing descriptions | 14 in Menswear; 416 in full catalog |
| Identical Menswear purchase groups with multiplicity >1 | 123,650 groups |
| Additional equal occurrences beyond first | 162,214, all retained |
| Menswear channel-code counts | `1`: 796,709; `2`: 974,344 |

Counts are recorded item-purchase occurrences, not number of orders, baskets or physical units inferred from pack names. The source lacks an explicit order ID, sizes, returns, exposures and verified stock availability.

| Optional customer field | Empty in full registry (1,371,980) | Empty among distinct Menswear customers (339,126) |
| --- | --- | --- |
| FN | 895,050 | 201,174 |
| Active | 907,576 | 203,934 |
| club_member_status | 6,062 | 726 |
| fashion_news_frequency | 16,009 | 2,255 |
| age | 15,861 | 2,339 |

Observed nonempty FN/Active token is `1.0`; absence must not become false. `fashion_news_frequency` contains both literal `NONE` and `None`; preserve these source values rather than conflating them with empty fields. Optional values are snapshot metadata without historical validity dates, so they are excluded from initial ranking.

## Window reconciliation and population consequences

| Count | Validation | Reserved test |
| --- | --- | --- |
| Future label dates, inclusive | Sep 9–15, 2020 | Sep 16–22, 2020 |
| Occurrences | 15,448 | 13,607 |
| Distinct future Menswear buyers | 6,573 | 5,793 |
| Distinct future Menswear articles | 2,139 | 2,048 |
| Known customers at cutoff from any past segment | 1,351,314 | 1,356,709 |
| Known customers with past Menswear purchases | 334,909 | 337,212 |
| Known customers with no past Menswear purchase | 1,016,405 | 1,019,497 |
| Future Menswear buyers within known population | 6,043 | 5,349 |
| Future Menswear buyers first observed after cutoff | 530 | 444 |
| Eligible past-purchased Menswear candidates | 12,283 | 12,378 |
| Distinct future articles with no prior purchase | 95 | 79 |

Known-customer population counts use the minimal identity/date/reference observation contract: source dimension IDs, references and dates were checked across all segments. Non-Menswear prices/channels were not fully validated in this audit and are not registry inputs. Thus these counts do not certify accepted non-Menswear purchase facts. In this source, no invalid dates or unknown references were found.

These are aggregate source-inspection counts, not evaluation scores. The prospective population differs substantially from future buyers; the protocol reports both all-known-customer and buyer-conditioned metrics, plus warm/cold cohorts. Future-first customers stay in a separate retrospective diagnostic. Future-only articles remain irretrievable relevant labels, with explicit attainability reporting. No products, customer preferences or parameters were selected using reserved-test outcomes.

## Semantics and unresolved evidence

The official Data page was read in the browser on the assessment date. It confirms a seven-day horizon and explains that equal purchase rows can represent repeated purchases. It also describes scoring future buyers including those without past history; this project declares its own prospective population and separately named conditional metrics rather than claiming competition equivalence.

The inspected official description does not establish a currency, a reversal of price scaling, or a `sales_channel_id` -> store/online mapping. [Price-scale discussion 310496](https://www.kaggle.com/competitions/h-and-m-personalized-fashion-recommendations/discussion/310496) contains a participant hypothesis about a factor of 590 and uncertain currency, not verified organizer confirmation in the inspected replies. This is not adopted. Preserve exact `price_source_units` and codes `1`/`2`; no conversion, currency, real revenue or store/online label. These ambiguities do not block ID/date-based ranking. Any later semantic labeling requires source evidence and a contract update.

## Access, use and acquisition instructions

The [official rules](https://www.kaggle.com/competitions/h-and-m-personalized-fashion-recommendations/rules), inspected on the assessment date, describe non-commercial research/education use and restrictions on disclosure to people without the required access. This is an educational simulation. Do not redistribute data, customer records, per-user outputs, derived model mappings or database dumps through Git, even privately. Code licensing is separate from data terms. Source access is already authorized according to the user; no new rule acceptance was performed here.

For another authorized user/environment: obtain access through the official competition page under the applicable rules, download only `articles.csv`, `customers.csv`, and `transactions_train.csv`, keep originals outside Git, and verify the manifest. No images or `sample_submission.csv` are needed. If files differ from the pinned manifest, register a new candidate release and stop additive loading for review. Do not use an unofficial mirror to bypass access. Download automation is outside the current stage and is unnecessary on this machine.
