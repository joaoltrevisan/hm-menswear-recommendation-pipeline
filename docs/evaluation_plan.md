# Temporal recommendation and evaluation protocol

Status: predeclared Stage 1 proposal. No model fitted or recommendation metric measured. Dataset inspection counts do not constitute model results.

## Cutoffs and isolation

| Use | Past available to fit | Seven-day labels (half-open) |
| --- | --- | --- |
| Validation and parameter selection | Through 2020-09-08 inclusive | `[2020-09-09, 2020-09-16)` |
| Reserved final test | Retrain selected recipe through 2020-09-15 inclusive | `[2020-09-16, 2020-09-23)` |

Cutoff means end of source date, without invented intraday order. All candidates, popularity, pair similarities, customer history, first observations and lookback filters use dates <= cutoff. No random primary split, future popularity, full-history item normalization, globally fitted encoders, or future label-driven customer selection for the prospective primary population. Catalog taxonomy is an explicit static scope assumption, not proof of historical stock. No customer demographic/snapshot attributes or product content features are used initially.

Source inspection may verify supplied window counts but must not tune a model, inspect future product preferences, or select parameters from test labels. Freeze the protocol/configuration hash before modeling. Stage 5 records the selected recipe and validation report before a separate explicit final-test command. That command evaluates the selected solution once, with parameters frozen and baselines refitted by their validation-selected settings. Comparing frozen baselines is descriptive, never a reason to reselect after test. A correction after consuming the test must be disclosed as a corrected analysis, not another untouched holdout.

## Population, candidates, and relevance

At cutoff `c`, primary population `U(c)` is all customers with at least one valid identity/date/reference observation in any product segment on or before `c`. Observation validity requires a structurally parsed record, nonempty format-valid customer/article IDs that resolve to the pinned dimension keys, and a canonical calendar-valid date. Prices, channels and optional customer attributes are not observation-registry inputs; their rejection does not erase otherwise valid evidence that a customer was observed. A registry observation is not an accepted Menswear purchase fact. Only a customer ID and its earliest observed date are used from other segments. This population is fixed without future labels, excludes people first observed after cutoff, and does not assume that the undated customer registry existed historically. It is broader than Menswear buyers; low primary MAP due to inactivity is expected, and must not be disguised by filtering future nonbuyers out.

Partition `U(c)` into warm customers (>=1 past Menswear purchase) and known Menswear cold start (no past Menswear purchase). Generate identical popularity fallback lists for cold customers; aggregate their scores efficiently without materializing millions of repeated lists. History length <2 distinct items and no nonzero similarity signals also trigger fallback, reported separately from zero-history cold start.

Primary candidates `C(c)` are Menswear articles with >=1 valid purchase on or before cutoff. This is a past-evidence proxy for availability, not verified current stock. No future first-sale article may appear. The static 12,553-product catalog is never itself the eligibility list. The same candidates apply to every model. If fewer than 12 candidates exist, return every available distinct article; if none, return an empty list and explicit reason. Repeat purchase recommendations are allowed because observed behavior can include repeat buying; never automatically remove bought products.

For each customer, relevant set `R(u)` is the distinct Menswear article IDs bought in the following seven days. Preserve all original purchase occurrences in the mart. **Keep future-only/noncandidate products in relevance denominators:** they are irretrievable misses, not removed to improve scores. Report distinct relevant products and customer-item labels without past evidence, and attainable recall (`|R intersect C| / |R|`). Labels are never used in training/candidate construction.

Primary metrics average across every customer in `U(c)`; customers without future Menswear purchases contribute zero AP and zero Recall by explicit convention. Report their count/fraction and future-buyer rate. Also report buyer-conditioned metrics for `B(c) = {u in U(c): |R(u)| > 0}` with denominator and warm/cold subdivisions. These conditional numbers measure ranking among future buyers, not conversion or a prospective population selection rule.

An additional diagnostic covers future Menswear buyers first observed after cutoff. They are outside `U(c)`, receive the same precomputed cold fallback, and are scored only in a separately labeled retrospective new-customer buyer cohort. Never mix them into the prospective primary denominator. Customers never observed in source purchases can still request the popularity fallback via CLI; they have no measurable prospective label cohort here.

## Metrics, denominators, and manual fixtures

Let ordered unique predictions be `p_1 ... p_m`, `m <= 12`; `hit(k)` indicates a relevant article at position `k`. `P(k) = sum(hit(j), j<=k)/k`.

`AP@12(u) = sum(P(k)*hit(k), k=1..m) / min(12, |R(u)|)` for nonempty relevance; zero otherwise.

`MAP@12 = sum(AP@12(u), u in population) / number_of_customers_in_population`.

`Recall@12(u) = |set(predictions) intersect R(u)| / |R(u)|` for nonempty relevance; zero otherwise. Mean Recall@12 uses the same population denominator as MAP. Never divide by 12 for recall or by returned-list length for AP. An empty population yields null/not-applicable, never NaN passed off as a real score.

`Catalog coverage@12 = number_of_distinct_recommended_articles_for_population / |C(c)|`. If no candidates or population, report null with counts. State cutoff, candidate count, population and cohort with every coverage figure. An optional full scoped-catalog fraction uses a separately named denominator of 12,553 and is not substituted for eligible-catalog coverage. Coverage measures exposure diversity, not ranking quality or sales.

Synthetic manual example: `R={A,B,C}`, predictions `[A,X,B]` gives AP `(1 + 2/3)/3 = 5/9`, Recall `2/3`; a second user with empty relevance contributes zero, so two-user MAP is `5/18` and mean Recall `1/3`. With candidates `{A,B,X,Y,Z}`, union recommendations `{A,X,B}` gives coverage `3/5`. A future-only relevant `C` remains a miss. Additional fixtures cover >12 relevant items, duplicate prediction rejection, duplicate label collapse, no hits, short lists, empty candidates and empty cohorts.

## Baselines and personalized challenger

1. **Recent popularity:** count preserved Menswear purchase occurrences in the last `W` days ending at cutoff. Rank count descending, then lifetime past count descending, then lexical `article_id` ascending. Zero-recent candidates are filled by lifetime past count then ID. `W in {7,14,28}` selected only on validation.
2. **Repeat-history baseline:** distinct previously purchased candidate items ordered by last purchase date descending, past occurrence count descending, then ID ascending. Append unselected recent-popularity items to 12. No intraday/basket assumptions or future metadata. This explicitly tests the value of allowing repeat purchases.
3. **Sparse item-item cosine:** build a binary customer-item interaction array from Menswear purchases in the last `L` days (`L in {90,180}`), using only past data. Repeated purchases stay in source but one user-item contributes one binary interaction to similarity, reducing domination by repeated lines. Pair support is distinct co-purchasing customers, not same-day orders. Normalize item columns using only training counts; remove self edges; discard pair support <2; retain strongest `N in {20,50}` neighbors per item with similarity descending, ID ascending. Compute in item blocks and immediately prune; never create a dense customer-item or full item-item matrix. Score candidates by sum of similarities from each customer's distinct training items. Positive scores descending, then recent popularity, then ID; fill unselected positions with the selected repeat-history baseline. Fewer than two distinct training items, absent vectors, or no positive scores use that baseline; it in turn falls back to popularity for no history.

All ranking ties are deterministic. Neighbor pruning can be directed; score using stored source-item outgoing neighbors and document that convention. Request the exact same model/config/cutoff twice -> same IDs/order. No performance improvement is assumed.

Predeclare the small search: 3 popularity settings, one history strategy using each setting, and 4 item-item settings using the winning popularity setting. Select by **primary validation MAP@12**, then primary Recall@12, then simpler family (popularity before repeat-history before item-item), then lexically sorted configuration JSON. Report all validation trials, runtimes, candidate sizes, warm/cold/cohort counts and fallbacks. Do not select by final test. The selected production recipe may be a baseline; the personalized challenger remains implemented and documented even if it loses.

The model manifest records cutoff, input release and committed batch coverage, data/contract/config hashes, code commit, exact dependency lock, random seed where applicable, candidate/ID mappings, ranking rules and artifact checksums. Full fitted artifacts, customer histories, per-user evaluations and predictions are private; only reviewed aggregate results can be committed. This local Menswear universe/population differs from the original competition; scores are not leaderboard-comparable.
