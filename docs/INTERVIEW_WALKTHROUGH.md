# Five-minute interview walkthrough

Use this as a spoken outline and open `output/report.html` beside it. This is an AI-assisted personal research project. It is not employment at Regions, client work, a deployed bank system or evidence of realized financial savings. AI assistance contributed to implementation and documentation; explain only work you can reproduce and defend.

## 0:00–0:35 — The question

“This project asks how a bank's earnings, economic value and ability to fund withdrawals can react differently to the same rate shock. A hedge that improves economic value can still consume cash through collateral. I wanted a small, inspectable model that makes those tradeoffs visible and preserves failures rather than forcing a successful recommendation.”

Show the report's distinction between bank net interest income, modeled earnings and economic value of equity.

## 0:35–1:15 — Establish the entity and the evidence

“The starting point is Regions Bank, FDIC certificate 12368, at December 31, 2025. It has $157.412 billion of reported assets and $131.987 billion of deposits. This is the insured bank entity, not its publicly traded holding company. Consolidated equity includes the reported noncontrolling interest. Exact FDIC responses, definitions, URLs and hashes let the source balances be rebuilt offline.

“The discount curve comes from a dated Federal Reserve fitted Treasury curve. Both data sources were retrieved later, so I do not claim they are the exact historical information set available on the observation date.”

Open provenance or `docs/SOURCES.md`.

## 1:15–2:00 — Add the hedge without losing the cash accounting

“The second stage adds a five-year payer-fixed swap entered at base-curve par before the shock. The first floating fixing stays locked; later coupons come from the shocked curve. Monthly dates and actual day fractions drive the schedule. The Treasury curve is a transparent projection-and-discounting proxy, not a SOFR dealer valuation.

“A falling-rate shock can create a negative swap value and a margin call. Posted collateral uses free cash; received collateral is segregated with a matching return liability. At month twelve, the model pays the coupon and closes the remaining swap value. The closeout exchanges an already marked position for cash, so it cannot book the gain twice.”

Show the opening event, collateral chart and final ledger row.

## 2:00–2:45 — Let better evidence change the primary case

“The original model used aggregate asset buckets. The primary case now starts with reported maturity and repricing bands, reconciles them to the same balance sheet, and separates nonaccrual assets and residual securities. It also includes operating-cost and credit-loss scale assumptions anchored to reported annual figures.

“Those changes can change the selected hedge. The original aggregate case stays visible as a reference. Each candidate faces the same funding and risk limits, and its EVE change is measured against its own unshocked starting portfolio. The selected policy is then held fixed for additional stress and assumption challenges.”

Show the source-coverage table and the selected-versus-reference comparison. Quote the current selection from the latest verified report, not an older screenshot.

## 2:45–3:30 — Explain the negative calibration result

“I would highlight the failed calibration before the attractive charts. The dataset has 44 bank quarters. Quarterly deposit expense is reconstructed from year-to-date reporting, divided by an average of domestic interest-bearing deposit balances, and matched with calendar-quarter policy-rate means.

“The constrained lag model trains through 2023 and is tested on 2024–2025. Its total beta is about 0.342, but holdout RMSE is 41.46 basis points versus 19.15 for persistence. The primary case therefore keeps the disclosed 0.5 beta assumption; the estimate becomes a sensitivity. Realized policy rates, later data revisions and an endpoint-average denominator make this a conditional historical exercise, not a live forecast.”

Show the calibration benchmark table.

## 3:30–4:10 — Explain why reported securities are not all available cash

“The source reports $20.926 billion of pledged securities. The model allocates that encumbrance proportionally and excludes equity and nonaccrual debt from forced sales. That makes the modeled opening sale inventory smaller than total securities. The allocation is an assumption because public totals do not identify the actual pledged positions.

“There is another distinction: blocking a sale does not settle whether principal paid by a pledged security becomes usable cash. The treatment of that cash needs a stated release or collateral-substitution assumption. I would not infer those contractual terms from a stock balance.”

Show the encumbrance assumptions and applicable challenge result.

## 4:10–5:00 — Give the strongest counterargument

“The strongest objection is that public bands mix contractual maturity with the next floating-rate reset. A reset does not repay principal. The model separates those dates, but fixed-rate shares, representative dates and floating contractual lives are still assumed. Changing those choices can change EVE, principal receipts and the preferred hedge.

“The tests and independent ledger reconstruction establish arithmetic and accounting consistency. They do not establish that the behavior matches Regions. My next priority would be actual average deposit balances, documented filing vintages, better contractual cash flows and collateral release terms. The project's useful result is a reproducible decision process that shows where a conclusion depends on assumptions.”

## Eight likely technical questions

### 1. Why measure both NII and EVE?

NII measures interest income less interest expense over the modeled twelve months. EVE discounts longer-lived asset and liability cash flows under assumed repricing and deposit lives. They answer different questions and use different horizon conventions here. The policy earnings objective also includes swap coupons, collateral interest, sale gains or losses and terminal closeout, less the swap fee and primary-case operating/credit costs. It excludes noninterest income, taxes and other components of GAAP net income.

### 2. How do you prove that the swap is initially at par?

Set the fixed coupon to the discounted projected floating coupons divided by the fixed-leg accrual annuity. At base inception, the two legs have equal PV and the net value is zero. There is no notional exchange. The first floating rate is fixed before the shock, so shocked floating coupons cannot simply all be replaced by a newly par floating leg. Tests separately cover that locked coupon, discounted coupon sums and conditional PV rollforward.

### 3. Why can a hedge improve EVE and still hurt liquidity?

The derivative can offset asset duration while requiring initial and variation margin. Cash posted as collateral remains an asset but is unavailable for withdrawals. The model applies the same borrowing and securities-sale limits to those calls. Unpaid obligations and unposted required margin are explicit breaches, and later recovery does not erase an earlier breach. Positive received margin is not reused.

### 4. Why not use the estimated beta instead of the assumed 0.5?

The estimated total beta loses to simple benchmarks on the untouched chronological holdout. Its lag coefficients also depend on strongly correlated rate inputs and exhibit instability across expanding samples. A precise-looking estimate is not sufficient evidence to replace an assumption. The 0.5 remains an assumption too; both it and alternatives must be challenged. This regression does not identify deposit decay or customer withdrawal behavior.

### 5. Is the historical exercise free of look-ahead bias?

Holdout targets cannot affect coefficient fitting, and missing periods are never filled from future observations. However, it is not a point-in-time forecast: contemporaneous policy-rate averages are realized inputs, source records were retrieved later, and actual bank-quarter publication times remain unknown. Publication/submission fields stay null. The documentation distinguishes the authenticated FFIEC submission-time service from the general public availability procedure.

### 6. How do you avoid treating a floating-rate reset as a maturity?

Each floating segment has separate reset and contractual maturity fields. Coupons change after the assumed reset; principal follows the separate amortization/maturity schedule. Reported bands constrain the maturity of assumed fixed-rate portions or the next reset of assumed floating portions. They do not identify the fixed/floating split or the floating contractual life. Those choices are disclosed and belong in model-risk challenges.

### 7. How is a forced security sale priced, and what can be sold?

Eligible unpledged debt is sold within a common book-value cap. The model applies the ratio of shocked to base PV for remaining assumed cash flows to book value. That is a relative-price proxy, not a live executable bid or proof of accounting classification. Amortization and prior sales reduce inventory. Encumbrance allocation, market depth, execution haircuts and the treatment of pledged principal remain important boundaries.

### 8. What evidence supports the implementation, and what is still unvalidated?

Raw source hashes and accounting identities check the starting data. Analytical pricing identities, conservation tests, deliberate tampering tests and an independent reconstruction of saved ledgers check the implementation. The report build must pass its controls and release audit. Frozen-policy challenges test specified hypothetical alternatives without reselection. None of this validates actual bank customer behavior, market execution, regulatory compliance or performance in an unobserved future crisis.

## Before the interview

Run the commands in the [case study](PROJECT_CASE_STUDY.md), check the current verified report, and rehearse one failing scenario as well as the selected policy. Be ready to change a deposit-life or fixed/floating assumption and explain why the result moves. Describe AI assistance candidly; do not claim a professional deployment, unaided implementation or business impact the project has not demonstrated.
