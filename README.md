# H&M Menswear — Sales Data Pipeline & Recommendation System

Independent educational case study with a simulated service scenario. No employment, commission, affiliation with H&M, live internal integration, current competition participation, or commercial outcome is claimed.

**Status: Stage 4 temporal baselines verified and measured; personalized comparison follows.** Configuration, numbered PostgreSQL migrations, least-privilege groups, a dependency lock and synthetic tests are present. Historical preparation/loading is implemented and reconciled on the complete source; baseline ranking and temporal evaluation are implemented; personalized item-item comparison follows in Stage 5.

The proposed service preserves purchase occurrences, loads traceable Menswear data into PostgreSQL, and ranks up to 12 distinct articles for a seven-day horizon through a reproducible CLI. It starts with recent popularity and repeat-history baselines before testing sparse item-item similarity.

- [Measured baseline validation](docs/baseline_results.md)
- [Model and evaluation commands](docs/model_operations.md)
- [Stage 4 verification and review](docs/review_stage_4.md)
- [Historical pipeline commands and recovery](docs/pipeline_operations.md)
- [Stage 3 verification and review](docs/review_stage_3.md)
- [Setup, database commands and Stage 2 verification](docs/stage_2_operations.md)
- [Implemented schema and permission dictionary](docs/schema.md)
- [Stage 2 independent review](docs/review_stage_2.md)
- [Source assessment](docs/source_assessment.md)
- [Architecture, record identity, and proposed table dictionary](docs/architecture.md)
- [Temporal evaluation and model selection protocol](docs/evaluation_plan.md)
- [Six stages, acceptance tests, and operations plan](docs/delivery_plan.md)
- [Independent technical review and actual checks](docs/review_stage_1.md)

The user authorized continued work through all six stages without repeated start approvals. Each stage retains independent review, verification and a private commit. The repository starts private. Data, private artifacts, credentials, and local machine paths must never enter Git. Source rules apply separately from any future code license; see the source assessment for authorized acquisition instructions.
