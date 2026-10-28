# Temporal models, immutable artifacts and evaluation

The case study reconstructs historical recommendations from source event dates. It assumes records are observable by the end of their source date; no ingestion-delay history is available to test that assumption. Current database ingestion timestamps are operational metadata, never model features. Full weekly batches may span a cutoff; training clips their covered interval and reads only events/observations at or before the cutoff in one repeatable-read, read-only database snapshot. This is an event-time reconstruction, not a claim about actual historical deployment latency.

## Inputs and baselines

The model role can read required purchase identity/date columns and the minimal customer observation registry. It cannot read customer age/FN/Active/status/postal data or source price/channel columns. Candidate articles come only from purchases observed by cutoff. The static catalog defines Menswear scope but does not establish historical stock availability. Training refuses missing committed source coverage. Snapshot validation forbids future events, future-only candidates, unsorted/duplicate mappings and warm customers without past evidence.

Recent popularity counts all preserved past occurrences in an inclusive W-day lookback ending at cutoff; ties use lifetime past count then article ID. History uses distinct user/item pairs ranked by latest source date, past occurrence count and article ID, then fills from recent popularity. Same-day records are not orders, and repeated source occurrences are retained. Repeat purchase recommendations remain allowed. Every list has at most 12 distinct candidate IDs; a smaller catalog returns fewer.

[Versioned protocol](../config/evaluation.json) fixes cutoffs, seven-day windows, populations, candidates, relevance, metrics, deterministic model selection and the small search. Stage 4 compares the two baselines at W=7,14,28 on validation only. Stage 5 adds four sparse item-item combinations (90/180 training days,20/50 neighbors,distinct-pair support>=2). Before seeing validation results, the protocol clarifies that item-item score ties use the best popularity configuration, history fallback uses the best repeat-history configuration, and zero-history fallback uses that repeat-history baseline's popularity filler. This resolves the filler/tie configuration explicitly without increasing the search.

## Clean-code provenance and private storage

Production training requires committed source/configuration/dependency files and verifies that the installed package bytes match the repository. Doc-only edits do not change algorithms, but model manifests still reference the actual HEAD commit and a separate source-tree hash. Synthetic tests supply an explicitly fabricated provenance identity inside isolated fixtures; production CLI offers no bypass. Reviewed code is committed before fitting actual-data models, so every measured model can be traced to an existing code revision.

Each immutable model manifest records release, as-of snapshot digest/covered windows, cutoff, family/parameters, protocol/lock/source-tree hashes, code commit, Python version, seed, counts and artifact hashes. The model ID is the SHA-256 of its canonical manifest. Restricted arrays include customer mappings and predictions and remain under HM_WORK_DIR/models with owner-only permissions, outside Git. NPZ loading disables pickle and verifies hashes, list sizes, uniqueness and candidate bounds. Files are atomically renamed only after writing; serving also requires a complete matching PostgreSQL registry row. An unregistered or corrupt artifact is refused. No model, mapping, row-level evaluation or actual recommendation export belongs in Git.

## Commands

Run from the project checkout after rebuilding its installed wheel from the lock and sourcing the private `.env`:

```sh
.tooling/bin/uv sync --locked --no-editable --no-build-isolation --reinstall-package hm-menswear-recommendation-pipeline
.venv/bin/hm-menswear train --model popularity --cutoff 2020-09-08 --window-days 14
.venv/bin/hm-menswear train --model repeat_history --cutoff 2020-09-08 --window-days 14
.venv/bin/hm-menswear compare-baselines --output ../hm-menswear-work/reports/baseline-validation.json
.venv/bin/hm-menswear evaluate --model-id <sha256> --split validation --output ../hm-menswear-work/reports/validation.json
.venv/bin/hm-menswear recommend --model-id <sha256> --customer <synthetic-64-hex-id> --k 12
```

Use actual customer inputs privately; committed examples contain no real identities. Recommendation output includes model/cutoff/product IDs and strategy, not the customer's identifier. Unknown customers receive the precomputed popularity fallback without inventing a customer record. Known customers without Menswear history are distinguished from entirely unobserved customers. With no candidates, return an empty list and explicit reason.

Training writes an immutable artifact; it does not update source data. Data loads do not retrain or replace models. Queries reference a specific model ID, so later source publication cannot silently change a list. Reports must be new files inside the private work directory; existing reports are not overwritten.

## Population and metric interpretation

Primary population includes every identity observed in any segment by cutoff, including people who make no future Menswear purchase (AP/Recall=0). Report warm and known Menswear-cold segments separately. Buyer-conditioned cohorts contain only future Menswear buyers within that prospective population; future-first buyers are a separately named retrospective diagnostic. These denominators are fixed by the declared protocol and must accompany results.

Relevant labels are distinct articles bought in the next seven days. Future-only/noncandidate articles remain misses in AP/Recall denominators. Coverage uses the eligible past-purchased catalog and predictions for the whole declared population, not only buyers. Cold predictions are identical and can contribute one shared exposure set without materializing millions of duplicate lists. Metrics on nonempty buyer labels can be computed once per buyer, then divided by the full prospective population; nonbuyers remain explicit zeros. Empty populations/candidate coverage are null/not applicable rather than misleading zero or NaN.

Validation labels use Sep 9–15,2020 only. Stage 4 refuses reserved-test evaluation. Parameters are selected by primary MAP@12, then primary Recall@12, then simpler family, then canonical configuration JSON. No improvement over popularity is promised. The later frozen comparison/test workflow must register its selection before accessing Sep 16–22 labels; test outcomes cannot reselect parameters. Local Menswear scores differ in universe/population from the original competition and are not leaderboard-comparable.
