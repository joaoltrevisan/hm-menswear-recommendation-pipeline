# Stage 4 verification and independent review

Status: code and synthetic verification approved by the same sole independent read-only technical reviewer. Standing user authorization covers subsequent stages without new start approvals. Actual-data fitting follows the reviewed code commit; aggregate validation results will be reviewed and recorded separately. The final test remains reserved.

Implemented: read-only repeatable as-of snapshots with coverage checks, past-only candidate/identity mappings, recent popularity and repeat-history baselines, deterministic ranking/fallback, manual ranking metrics and prospective/buyer-cohort aggregation, private immutable model artifacts, clean-source/installed-code provenance, registered-artifact serving, model/evaluation CLI commands and a predeclared versioned protocol.

Implementer regression: **131 tests passed in 9.51 seconds**, no skips. Independent reviewer regression: **131 passed in 9.58 seconds**, no skips. Both required PostgreSQL and actual container-log safety verification. Ruff lint/format, offline lock consistency and diff checks passed. The production provenance guard refused uncommitted modeling code as intended. Tests cover synthetic baseline flow, cutoff/future-candidate refusal, manual AP/Recall/coverage examples, empty populations/catalogs, unique history filler, deterministic model content, corrupt/unregistered artifact refusal, and protocol boundaries.

The reviewer reported **no mandatory findings and no optional suggestions** for the code scope. Temporal SQL filters/coverage, occurrence-count popularity, history ordering/filler, primary/buyer/warm/cold denominators, future-only relevance handling and reserved-test refusal were verified. No real-data performance result is claimed at this code milestone.

The source mart is unchanged from Stage 3. No uncertain customer attributes are model inputs. Tests use only independent synthetic IDs/data and fabricated provenance inside isolated databases. Actual model packages and reports stay in private local storage; only aggregate results will be documented.

## Actual source validation and final review

Code commit `017a6eab7a1214d091899b1afd710099179477ac` was pushed privately before fitting. The six-configuration actual-source validation completed, selecting repeat_history with a 7-day filler. [Measured results](baseline_results.md) report primary MAP@12 0.00027589144, Recall@12 0.00068664089 and coverage 0.98453147 over 1,351,314 past-known identities and 12,283 candidates. All six models share the past-only snapshot of 1,741,998 occurrences.

The same independent reviewer verified the six reports/manifests, complete grid, selection, documentation transcription and weighted/conditional population reconciliation. Read-only registry aggregates confirmed six September 8 models, six validation runs and **zero test sessions**. Final outcome: **approved, no mandatory findings or optional suggestions**. Review accessed aggregates/manifests only, without customer rows or arrays. Stage 4 is complete; personalized comparison and the frozen final-test workflow proceed in Stage 5.
