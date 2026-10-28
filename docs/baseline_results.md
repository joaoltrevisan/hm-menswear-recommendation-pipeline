# Measured baseline validation

Actual historical source, not synthetic fixtures. Training cutoff: **2020-09-08**. Labels: **2020-09-09 through 2020-09-15**. No reserved-test labels were accessed by this comparison. All six model manifests reference reviewed code commit `017a6eab7a1214d091899b1afd710099179477ac`, protocol SHA-256 `8187e4cdfd066e005e5cc006cdb595a08e93c3cc1f8814f528c30c71ff60b524` and the same input snapshot `44bdc860e6849a3e4492096e92485618c6758b99fdd754dab1d65e66a7b1bae3`.

The past snapshot contains **1,741,998 purchase occurrences**, **12,283 past-purchased candidates**, **1,351,314 identities observed in any segment**, including **334,909 Menswear-warm** and **1,016,405 known-cold** customers. Labels contain 6,573 buyers: **6,043** already known (4,270 warm,1,773 cold) and **530 future-first** buyers excluded from the prospective primary population and reported separately. The primary population includes **1,345,271 nonbuyers**, whose AP and Recall are zero.

All metrics are fractions. Primary MAP/Recall use the entire prospective population; the last column is a separately conditioned buyer diagnostic. Coverage uses all prospective predictions and the 12,283 eligible candidates.

| Family | Popularity days | Primary MAP@12 | Primary Recall@12 | Primary coverage@12 | Known-buyer MAP@12 |
|---|---:|---:|---:|---:|---:|
| popularity | 7 | 0.00021957516 | 0.00064224916 | 0.00097696 | 0.04910061 |
| popularity | 14 | 0.00021044770 | 0.00061250611 | 0.00097696 | 0.04705956 |
| popularity | 28 | 0.00019760379 | 0.00062608754 | 0.00097696 | 0.04418745 |
| repeat_history | 7 | 0.00027589144 | 0.00068664089 | 0.98453147 | 0.06169385 |
| repeat_history | 14 | 0.00027059146 | 0.00067198452 | 0.98453147 | 0.06050869 |
| repeat_history | 28 | 0.00026075313 | 0.00067144683 | 0.98453147 | 0.05830868 |

The predeclared selection rule chose **repeat_history with a 7-day popularity filler**. History ranks each customer's past items by last purchase date, occurrence count, then article ID; the 7-day parameter governs only the filler. The selected model's warm MAP/Recall are 0.00077299188/0.00181178644, and known-cold MAP/Recall are 0.00011209511/0.00031590149. Its known-buyer MAP/Recall are 0.06169385492/0.15354417372; these buyer-conditioned values must not replace the primary figures.

The label set includes **95 distinct future articles without past purchase evidence**, comprising **316 distinct customer/item labels** across all label buyers. They remain misses, including in relevance denominators. Historical-repeat coverage is high because every warm customer's list can expose different past products; high catalog coverage alone does not establish useful ranking, causal sales lift or inventory availability.

Run command: `hm-menswear compare-baselines --output ../hm-menswear-work/reports/baseline-validation.json`, after locked wheel installation and private configuration. Per-model fit/save/evaluation loop timings were 2.657–4.034 seconds, excluding the shared snapshot query and process setup; these are local observations, not an SLA. Private reports, mappings, recommendation arrays and model packages remain outside Git. The personalized comparison and reserved final test follow in Stage 5; no challenger improvement is assumed.
