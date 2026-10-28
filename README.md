# H&M Menswear — Sales Data Pipeline & Recommendation System

Independent educational case study with a simulated service scenario. No employment, commission, affiliation with H&M, live internal integration, current competition participation, or commercial outcome is claimed.

**Status: Stage 1 proposal, awaiting user approval.** Source files are already available through authorized access. No production pipeline, PostgreSQL schema, model, dependency lock, or pytest suite has been implemented. Local source inspection is evidence about files, not a passing implementation test.

The proposed service preserves purchase occurrences, loads traceable Menswear data into PostgreSQL, and ranks up to 12 distinct articles for a seven-day horizon through a reproducible CLI. It starts with recent popularity and repeat-history baselines before testing sparse item-item similarity.

- [Source assessment](docs/source_assessment.md)
- [Architecture, record identity, and proposed table dictionary](docs/architecture.md)
- [Temporal evaluation and model selection protocol](docs/evaluation_plan.md)
- [Six stages, acceptance tests, and operations plan](docs/delivery_plan.md)
- [Independent technical review and actual checks](docs/review_stage_1.md)

Only Stage 1 is currently authorized. Approval of this proposal permits Stage 2 alone; every later stage requires its own approval. The repository starts private. Data, private artifacts, credentials, and local machine paths must never enter Git. Source rules apply separately from any future code license; see the source assessment for authorized acquisition instructions.
