# Measured personalized comparison and reserved final evaluation

All actual-source Stage 5 models were fitted from reviewed code commit `204897a7ff93ea7f0b3cb32d22bb4054c63bed9d` using the predeclared [protocol](../config/evaluation.json). The six baseline validation metrics exactly reproduce Stage 4. Validation chose **repeat_history with a 7-day popularity filler**. None of the four sparse item-item configurations improved primary MAP@12 over that baseline. The selected family/parameters were frozen before test labels; the test table is descriptive and does not reselect a model.

Training/validation: cutoff September 8, labels September 9–15, 2020. Refit/final test: cutoff September 15, labels September 16–22. Every final-test model uses the same snapshot `7ca5a7bf938e472b64e0b660a4d06d557f7724c4cecddc1f201d9f784199f151`: **1,757,446 past purchase occurrences**, **12,378 past-purchased candidates** and **1,356,709 past-known customer identities**. No uncertain customer metadata is used. Values below are fractions, not percentages.

| Configuration | Validation primary MAP@12 | Final primary MAP@12 | Final primary Recall@12 | Final primary coverage@12 |
|---|---:|---:|---:|---:|
| popularity W=7 | 0.00021957516 | 0.00018365318 | 0.00054103441 | 0.00096946 |
| popularity W=14 | 0.00021044770 | 0.00017344168 | 0.00051525316 | 0.00096946 |
| popularity W=28 | 0.00019760379 | 0.00016652495 | 0.00049258977 | 0.00096946 |
| repeat_history W=7 | 0.00027589144 | 0.00022207389 | 0.00057269175 | 0.98456940 |
| repeat_history W=14 | 0.00027059146 | 0.00021467458 | 0.00054256889 | 0.98456940 |
| repeat_history W=28 | 0.00026075313 | 0.00021134285 | 0.00053008329 | 0.98456940 |
| item_item L=90, N=20 | 0.00024184798 | 0.00019321840 | 0.00053894734 | 0.97237033 |
| item_item L=90, N=50 | 0.00024119756 | 0.00019318655 | 0.00054100414 | 0.97237033 |
| item_item L=180, N=20 | 0.00023075955 | 0.00018642408 | 0.00052829320 | 0.96542252 |
| item_item L=180, N=50 | 0.00023126915 | 0.00018551716 | 0.00052503777 | 0.96534174 |

## Selected recipe: population and buyer diagnostics

Primary includes every identity observed in any segment by cutoff. It contains **1,351,360 customers with no future Menswear purchase**, assigned AP/Recall=0. Labels contain 5,793 buyers: 5,349 already known (3,879 warm, 1,470 cold), plus 444 future-first buyers shown separately. Buyer-conditioned results are retrospective diagnostics and must not replace the primary population score.

| Cohort | Population | Future buyers | MAP@12 | Recall@12 | Coverage@12 |
|---|---:|---:|---:|---:|---:|
| primary | 1,356,709 | 5,349 | 0.00022207389 | 0.00057269175 | 0.98456940 |
| warm | 337,212 | 3,879 | 0.00064228549 | 0.00156029284 | 0.98456940 |
| cold | 1,019,497 | 1,470 | 0.00008308339 | 0.00024602975 | 0.00096946 |
| buyers_known | 5,349 | 5,349 | 0.05632634909 | 0.14525632019 | 0.50177735 |
| buyers_warm | 3,879 | 3,879 | 0.05583562090 | 0.13564049224 | 0.50177735 |
| buyers_cold | 1,470 | 1,470 | 0.05762127061 | 0.17063033150 | 0.00096946 |
| future_first_buyers | 444 | 444 | 0.05710324096 | 0.14786929787 | 0.00096946 |

Test labels contain **79 distinct articles without past purchase evidence**, representing **210 distinct customer/item labels** across all future buyers. They remain misses in all relevance denominators. Candidates are past purchase evidence, not historical stock/availability truth. The selected recipe serves repeat-history lists to 337,212 warm customers and the shared popularity filler to 1,019,497 known-cold customers.

## Personalization versus fallback

The four item models all use the validation-chosen 7-day popularity tie/filler and history baseline. Pair support>=2 counts distinct customers, not repeated source occurrences. Both neighbor settings have the same eligibility counts within each lookback:

| Lookback | Validation warm personalized | Validation warm history fallback | Test warm personalized | Test warm history fallback |
|---|---:|---:|---:|---:|
| 90 days |48,149|286,760|47,327|289,885|
| 180 days |75,815|259,094|76,979|260,233|

All item variants additionally serve the common popularity filler to 1,016,405 validation known-cold and 1,019,497 test known-cold customers. These aggregate path counts partition the full prospective population; reports also include known-buyer path counts. No customer mappings or per-user lists are published.

## Holdout receipt and reproducibility

One immutable source-release test reservation froze the exact ten refit IDs, comparison and validation winner before label access. Its recipe SHA-256 is `f41d2bf024d2f1100806767164bed231be355650a9211e36425521393cc50551`. The workflow reads the seven-day label set once and stores all ten results atomically. A completed replay returns those stored metrics without reading labels; a changed recipe or protocol cannot create a second reservation for this release. The selected recipe remains fixed regardless of the final table's ordering.

Private commands: `compare-models --output ../hm-menswear-work/reports/model-validation.json`, then `final-test --comparison ../hm-menswear-work/reports/model-validation.json --output ../hm-menswear-work/reports/final-test.json`. Environment and locked installation are documented in the [model runbook](model_operations.md). Actual validation fit/save/evaluation loop observations ranged 2.679–5.956 seconds, excluding shared snapshot queries/setup; they are not end-to-end throughput or an SLA. Models, source mappings, receipt JSON and full private reports remain outside Git.

This is one historical validation week and one reserved test week, with no uncertainty interval, online experiment or causal sales measurement. Results do not establish commercial lift, current-season relevance or competition leaderboard comparability. High repeat-history coverage reflects diverse past-item exposure rather than proof of useful recommendations. More complex modeling did not win this declared comparison; retaining the measured baseline is the intended outcome of evidence-based selection.
