# Funding and hedge decision: sourced extended case

**Case:** Regions Bank and consolidated subsidiaries, FDIC certificate 12368, December 31, 2025. Research artifacts retrieved and built October 2, 2026. Amounts below are USD. Figures are taken from the saved `output/analysis.json`, `research_evidence.json` and `robustness.json`, with challenge totals also exported in `robustness_summary.csv`.

**The current model selects 6% prefunding, borrowing before securities sales, and a 10% pay-fixed hedge. Fourteen of 30 candidates meet all selection-scenario limits.** The selected candidate maximizes worst-case modeled earnings among those feasible choices, but that worst case is a **$1.745 billion loss** under parallel -200 bp. Feasibility does not require positive earnings. The frozen policy then fails **9 of 34 broader challenges**. These results support a transparent model comparison, not a recommendation that Regions Bank execute the policy.

The policy raises **$9.445 billion** of fixed-rate prefunding and enters a hypothetical **$15.741 billion** five-year pay-fixed/receive-floating swap. Its fixed coupon is **3.7028%**, priced at par before the shock using a Treasury single-curve proxy. The upfront fee is **$1.574 million**; initial margin is **$314.824 million**. The instrument uses monthly ACT/365F dates and holds the first floating fixing unchanged across shocks.

## Earnings and the protection tradeoff

The comparison below uses the same sourced asset segments, starting deposit cost and business-cost assumptions. The reference has no prefunding or hedge and borrows before selling. Each EVE change is relative to that policy's own baseline. Amounts are billions.

| Scenario and measure | Unhedged reference | Selected 6% funding + 10% hedge |
|---|---:|---:|
| Baseline: raw bank NII | 4.936 | 4.617 |
| Baseline: modeled earnings after disclosed costs | 0.356 | 0.047 |
| +200 bp / 45% runoff: change in EVE | -6.327 | -4.459 |
| Same combined case: raw bank NII | 3.829 | 3.981 |
| Same combined case: hedge-adjusted interest earnings | 3.829 | 4.258 |
| Same combined case: modeled earnings after disclosed costs | -1.212 | 0.350 |
| Same combined case: minimum observed free cash | 2.361 | 2.361 |
| Parallel -200 bp: change in EVE | 3.486 | 1.446 |
| Same rate-down case: raw bank NII | 4.762 | 4.313 |
| Same rate-down case: hedge-adjusted interest earnings | 4.762 | 4.020 |
| Same rate-down case: modeled earnings after disclosed costs | 0.186 | -1.745 |

Raw bank NII includes bank asset interest less deposit/funding interest. Hedge-adjusted interest earnings add accrued swap coupons and posted-collateral interest. The selection objective then adds securities-sale PNL and terminal swap closeout, and deducts the swap fee, operating expense and new credit-loss proxy. It reconciles to the change in ending equity. It is **not forecast net income**.

Operating expense is anchored to reported 2025 noninterest expense of **$4.166 billion**, charged evenly across the 12 months. The annual new-loss rate is reported net chargeoffs of **$513 million** divided by opening net loans, applied monthly to beginning loan book. Loan runoff makes the realized modeled credit charge **$414.3 million** in the baseline, **$417.7 million** in the combined case and **$409.8 million** under -200 bp. The model excludes **$2.441 billion of historical noninterest income**, taxes, distributions and OCI. Historical provisions are context and are not charged again. Omitting that income makes the objective a deliberately incomplete earnings measure; its losses must not be presented as a forecast of the bank's actual profitability.

The selected rate-down outcome is **$1.792 billion below its own baseline**. A negative swap closeout of **$1.187 billion**, along with negative coupons, explains much of that downside. In the combined case, the terminal closeout is **+$1.156 billion**. Mark changes already enter equity along the path; closeout exchanges the derivative for cash or a payable without booking the PNL twice.

## Separate prefunding from the incremental hedge

| Combined +200 bp / 45% runoff policy | Change in EVE, bn | Modeled earnings, bn |
|---|---:|---:|
| No prefunding, no hedge | -6.327 | -1.212 |
| 6% prefunding, no hedge | -5.804 | -1.047 |
| 6% prefunding, 10% hedge | -4.459 | 0.350 |

Prefunding contributes **$522.9 million** of EVE-loss improvement and **$165.0 million** of combined-case earnings improvement. Adding the hedge at that same funding choice contributes another **$1.345 billion** of EVE-loss improvement and **$1.397 billion** of earnings improvement, including collateral, funding and sale effects.

The hedge also reduces rate-down earnings by **$1.498 billion** relative to the same prefunding with no hedge. The zero-hedge prefunded candidate has a better worst earnings result, but violates the EVE constraint. The selected policy therefore pays an earnings price to satisfy the modeled interest-rate-risk limit; it does not improve every outcome.

## Liquidity capacity is limited

Common constraints are a **$2.361 billion** free-cash floor, **$15.741 billion** additional-funding cap, **$4.533 billion** maximum EVE loss, and no unfunded withdrawal, margin or payment obligation beyond the $1 numerical tolerance. These are research limits. The original 80%-of-securities sale limit also applies, but reported encumbrance narrows sale availability further.

Official reported securities total **$33.894 billion**, of which **$20.926 billion** are pledged in aggregate. Proportional allocation of pledges across segments, together with exclusion of equity securities, produces **$12.682 billion** of modeled opening unpledged debt eligible for sale. This is a sourced constraint with an assumed allocation, not identified security-level availability.

The selected combined case reaches the full funding cap: **$19.656 billion** total wholesale funding including opening debt. It sells **$5.336 billion** of securities book and realizes **$478.9 million** of sale losses. Its EVE-loss headroom is only **$73.9 million**. The largest initial-plus-variation collateral requirement is **$1.802 billion** under -200 bp. Up to **$1.352 billion** of received variation margin in the combined case remains segregated and cannot fund withdrawals.

## The strongest counterargument is model uncertainty

The policy was frozen before the additional challenge runs; failing results did not change its size or limits.

| Challenge family | Pass | Fail |
|---|---:|---:|
| Unseen rate/runoff combinations | 15 | 5 |
| Deposit behavior and CPR | 3 | 3 |
| Discount/projection curve assumptions | 3 | 1 |
| Asset split, contractual life and pledged proceeds | 4 | 0 |
| **Total** | **25** | **9** |

Several 60%-runoff cases exhaust free cash and leave withdrawal requests unpaid. At +300 bp and 40% runoff, EVE falls **$5.576 billion**, breaching the limit despite positive modeled earnings. In the combined case, a beta of 0.9, five-year deposit lives or zero CPR also breaches the EVE limit. Zero CPR gives a **$6.409 billion** EVE loss. Even the Treasury proxy shifted upward 25 bp gives a **$4.604 billion** EVE loss. The worst challenge earnings are **-$2.786 billion** at -300 bp and 40% runoff. These cases are hypothetical tests, not observed future outcomes or failure probabilities.

Reported maturity/repricing bands do not reveal their fixed/floating mix. The primary case assumes **20% fixed** within the other-loan category, including a **$49.958 billion** near-maturity-or-reset band. That assumption determines how much principal returns early instead of merely repricing. Changing the fixed share to 10% or 40% keeps the tested combined case feasible but moves earnings to **$80.4 million** or **$570.1 million**. Floating contractual life is separately assumed; an 84-month minimum also remains feasible in the saved challenge.

The primary case releases modeled pledged-security principal into free cash. Actual collateral terms may require substitution or retained proceeds. The conservative alternate retains those proceeds as non-interest-bearing pledged cash through month 12; the frozen combined case remains feasible, but earnings fall from **$349.8 million to $242.3 million**. Passing these four chosen segment challenges does not validate the assumptions or cover their joint extremes. [Cash-flow coverage](CASH_FLOW_COVERAGE.md) records the full scope bridges and residuals.

The historical deposit-cost fit does not resolve this uncertainty. It uses **44 quarters**, training through 2023 and holding out 2024–2025. The fitted persistent-response beta is **0.342**, but holdout RMSE is **41.46 bp**, worse than **19.15 bp** for training-end persistence. The engine therefore retains the **0.5 research beta** and includes the fitted value in sensitivity. This is an explicit unresolved assumption, not evidence that 0.5 was empirically validated. Deposit-cost denominators are adjacent-quarter balance means; reported daily averages and exact historical publication timestamps were unavailable.

## Keep the original case separate

The preserved aggregate v2 comparison selected **6% prefunding and a 5% hedge**, with 22/30 feasible candidates and 24/30 broader challenges passing. It excluded the current cost overlays and sourced segment inventory. Its larger positive earnings are not directly comparable with the current objective. Results match the unchanged original zero-hedge fixture within $0.0001 for cross-platform monetary rounding; that is regression evidence, not support for treating the earlier strategy as the current choice.

The final primary audit independently checks **248 saved paths and 1,637,045 numerical comparisons**, with maximum accounting residual below **$0.0001**. This establishes arithmetic consistency of the saved results. It does not establish actual coupons, borrower behavior, funding access, execution liquidity, SOFR hedge pricing or intramonth cash sufficiency. Later retrieved source vintages also prevent a publication-time historical-backtest claim.

## Interview walkthrough

1. Reconcile the bank legal entity, gross-to-net loan bridge and pledged securities before discussing a hedge.
2. Explain the negative worst-case earnings and why the EVE constraint makes the higher-earnings zero-hedge alternative infeasible.
3. Separate prefunding attribution from adding the swap, then trace collateral and terminal closeout without double counting.
4. Show the nine failed frozen-policy challenges and identify contract-level repricing, prepayment and collateral-release evidence as the next research priority.
