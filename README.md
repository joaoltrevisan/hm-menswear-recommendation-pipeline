# H&M Menswear — Sales Data Pipeline & Recommendation System


Independent educational case study and sales-data integration/recommendation pipeline with a simulated service scenario. No employment, commission or affiliation with H&M is claimed. This project reconstructs historical recommendations; it has no live internal integration or current competition participation.


**Status: all six stages implemented and independently reviewed.** The Python/PostgreSQL pipeline preserves and reconciles **1,771,053 Menswear purchase occurrences**, with immutable file/record identities, atomic dated publication, idempotent replays, concurrency protection and failure recovery.

From a portfolio perspective, the project demonstrates historical sales-data integration, PostgreSQL loading, immutable record handling, idempotent reruns, operational recovery and explicit model evaluation. The repository also documents logs and opt-in scheduling examples; no scheduler is installed automatically. The CLI trains and compares past-only popularity, repeat-history and sparse item-item models, then returns up to 12 distinct articles for a seven-day horizon.


The declared ten-configuration validation selected **repeat history with a 7-day popularity filler**. Item-item did not improve the primary validation metric. On the reserved final week, the selected recipe measured **MAP@12 0.00022207389**, **Recall@12 0.00057269175** and **catalog coverage 0.98456940** over **1,356,709 identities known before cutoff**, including nonbuyers assigned zero. Buyer-conditioned diagnostics use different denominators and are reported separately. This is one historical test week, not measured sales lift or competition leaderboard performance.


Start with the [complete operational walkthrough](docs/operations.md): locked installation, private configuration, PostgreSQL setup, historical loading, comparison, immutable final-test reservation, explicit selected-recipe retraining and recommendation queries. `scripts/demo.sh` runs an independently synthetic CLI walkthrough in isolated PostgreSQL databases without competition-file access. Cron/launchd examples are opt-in and have not been installed. The source ends on September 22,2020; later seven-day forecasts are unobserved historical horizons.


- [Measured comparison and reserved final evaluation](docs/recommendation_results.md)
- [Measured baseline validation](docs/baseline_results.md)
- [Historical pipeline commands and recovery](docs/pipeline_operations.md)
- [Model and evaluation commands](docs/model_operations.md)
- [Implemented schema and permission dictionary](docs/schema.md)
- [PostgreSQL setup and security](docs/stage_2_operations.md)
- [Source assessment and authorized-data conditions](docs/source_assessment.md)
- [Architecture and record identity](docs/architecture.md)
- [Predeclared evaluation plan](docs/evaluation_plan.md)
- [Delivery plan and acceptance criteria](docs/delivery_plan.md)


Exactly one independent read-only technical reviewer reviewed each implementation stage. Verification records: [Stage 1](docs/review_stage_1.md), [Stage 2](docs/review_stage_2.md), [Stage 3](docs/review_stage_3.md), [Stage 4](docs/review_stage_4.md), [Stage 5](docs/review_stage_5.md), [Stage 6](docs/review_stage_6.md).


The repository remains private. Source CSVs, private model/customer mappings, reports, logs and credentials stay outside Git. Obtain competition data only through authorized access; no data is redistributed or licensed with this code. No deployment, public visibility change or Kaggle submission was performed.

