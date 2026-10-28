# Stage 5 verification and independent review

Status: personalized recommender and frozen holdout workflow implemented; synthetic verification and review in progress. Actual validation/refit/test will follow a clean reviewed code commit. Stage 4 measured baselines remain documented separately; no personalized or final-test score is claimed yet.

Implemented: binary sparse item-item cosine with distinct-customer pair support, bounded computation blocks, deterministic 90/180-day by20/50-neighbor search, fixed validation-derived tie/fallback parameters, personal-signal flags, model artifact checks and CLI comparison. Immutable release-level test reservation, exact registered comparison validation, committed receipt before labels, atomic all-model results, serialized ownership and stored-result replay protect the holdout workflow.

Initial complete regression: **140 tests passed in12.93 seconds**, no skips, including required PostgreSQL/container-log safety. Additional ownership/release uniqueness checks follow before final review. Synthetic examples cover cosine/support, duplicate preservation versus binary projection, diagonal exclusion, tie/pruning invariance, lookback boundary, history fallback, complete search, tampered report refusal, freeze-before-labels, interrupted resume and no-read completed replay.

## Code review outcome

The same sole read-only reviewer approved the final source with **no mandatory findings or remaining optional suggestions**. Their reporting obligation was implemented: full prospective and known-buyer reports include aggregate personalization/history/popularity/no-candidate path counts. Implementer final full regression: **140 passed in12.73 seconds**. Independent full regression: **140 passed in12.53 seconds**; after the counter addition, **23 affected tests passed in3.15 seconds**. No skips in required PostgreSQL/log-safety verification. Installed/source parity, Ruff, diff and offline lock checks passed. No actual holdout data or customer arrays were accessed in review.

Reviewed source is committed before actual-data model fitting. Actual comparison and final-test aggregate results will be recorded and independently verified in a separate results delivery.

## Actual comparison, final test and results review

Reviewed code `204897a7ff93ea7f0b3cb32d22bb4054c63bed9d` was pushed before actual fitting. All ten validation configurations and ten fixed refits completed. Validation retained repeat_history W=7; item-item did not improve the declared primary metric. [Measured comparison and test tables](recommendation_results.md) include prospective/buyer cohorts, unavailable labels and personalization/fallback counts. The selected recipe's final primary MAP@12 is0.00022207389, Recall@12 is0.00057269175, and coverage is0.98456940.

The same reviewer independently reconciled every table and path partition, all twenty manifests' code/runtime/lock provenance, one immutable receipt, ten refits completed before it and ten matching result records afterward. Actual completed replay exported identical stored JSON while counts remained one receipt and ten results. No test-based reselection occurred. Final outcome: **approved, no mandatory findings or optional suggestions**. Review used aggregates/manifests/registry metadata only, without customer arrays or labels. Stage 5 is complete.
