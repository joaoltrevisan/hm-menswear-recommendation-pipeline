# Stage 6 integration verification and independent review

Status: final operational integration implemented; checks/review in progress. Added a finite historical arrival command with gap/overlap handling and bounded transient retries, explicit retraining of the immutable validation-selected recipe, stored test report export independent of label access, customer stdin recommendations, opt-in shell/launchd schedule examples and a synthetic CLI walkthrough. No schedule or deployment was installed. Model algorithms and the Stage 5 selection are unchanged.

Verification results, clean-environment checks, sole-reviewer findings/fixes and actual local operational demonstration follow before final delivery.

## Implementer verification

Full regression: **144 tests passed in12.04 seconds**, no skips, with required PostgreSQL/container-log safety. Locked offline reconciliation/install into a separate existing verification environment followed by full regression: **144 passed in13.05 seconds**, no skips. A genuinely new virtual environment was then created entirely from the offline lock/cache: its synthetic complete CLI walkthrough passed **1 test in8.46 seconds**. These are distinct checks; the new environment's walkthrough is not claimed as a full new-environment regression.

Ruff lint/format, diff checks, all local Markdown targets, shell syntax and launchd plist parsing passed. CLI help includes all documented actions. The standalone demo wrapper is also executed before review. The walkthrough uses synthetic contract/provenance injection confined to tests; production source/hash/clean-code guards remain active. It creates/deletes only isolated synthetic databases/logins and does not read the competition data.

## Mandatory retry correction

The reviewer found a mandatory operational defect: recomputing the next uncovered interval on every retry could advance a second week if the first publication committed but its outcome was lost. The scheduler now plans once before publication and retains that exact date tuple through its bounded retry loop. Every publication retry starts a fresh loader attempt for the same interval; an already committed interval becomes a no-op. Planning retries can repeat only while no interval has yet been selected.

A new synthetic PostgreSQL integration deliberately commits the first window and then raises an OperationalError to simulate a lost outcome. It verifies retry_count=1, a no-op second attempt, exactly one completed September1–8 interval and two preserved identical purchase occurrences. The unit retry test also checks that successful planning occurs once and every publication receives the same tuple. Final implementer regression: **145 passed in12.45 seconds**, no skips. The lock-installed verification environment was resynchronized after the fix and its CLI/uncertain-commit integration tests passed **2 in1.06 seconds**. Ruff lint/format and diff checks passed. The reviewer re-verifies the correction before the code commit.

Original source byte hashes were re-read at final integration: all three CSVs still match the pinned SHA-256 values. GitHub visibility was independently queried and remains private. The initial standalone demo wrapper passed one test in0.92 seconds; its shell code is unchanged by the retry correction. No scheduler, deployment or public visibility change was installed.

## Independent final code re-review

The same sole technical reviewer approved the correction: mandatory **P2 resolved**, with **no remaining mandatory findings or optional suggestions**. Independent full regression from the lock-installed verification environment: **145 passed in12.70 seconds**, no skips. Installed source/resources match; Ruff, lock consistency, diff, shell syntax, plist and Markdown-link checks passed. No actual customer data or files were changed by review.

The corrected reviewed source is committed before actual-source selected-recipe retraining. A final local operational demonstration will verify finite-source exhaustion, the frozen selected recipe at the source-end cutoff, a private recommendation query, stored-report export and unchanged holdout receipt/result counts.
