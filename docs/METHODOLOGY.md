# Model methodology

The primary case combines reported Regions Bank balances and maturity/repricing bands with explicit cash-flow assumptions, business-cost overlays and hypothetical funding/hedge policies. It estimates sensitivity to rates and requested withdrawals. It is not the bank's internal ALM model, a net-income forecast, a regulatory compliance assessment or an execution recommendation. The original aggregate case remains a separately labeled comparison against unchanged regression fixtures, with $0.0001 monetary tolerance for cross-platform rounding.

## Legal entity, sources and reporting scope

The opening entity is Regions Bank and consolidated subsidiaries, FDIC certificate 12368, as of December 31, 2025. It is not Regions Financial Corporation. Total consolidated equity of $18.131 billion includes $60 million of noncontrolling interests; using parent-only equity would break the statement. Other assets and liabilities are explicit residual buckets. Interest-bearing cash of $7.607 billion divided by total cash of $11.845 billion sets the assumed earning share of subsequent free cash.

The [FDIC Financials API](https://api.fdic.gov/banks/docs) supplies balances, historical earnings/costs and asset bands. The [December 2025 FFIEC instructions](https://www.ffiec.gov/sites/default/files/data/reporting-forms/FFIEC031_FFIEC041_202512_i.pdf) define the bands. Securities bands total $33.147 billion plus $0.747 billion of equity securities, reconciling to $33.894 billion. Accruing loan bands total $95.425 billion plus $0.698 billion of nonaccrual loans, giving $96.123 billion gross; deducting the $1.556 billion allowance yields $94.567 billion net. Net book is allocated proportionately across gross loan segments, including nonaccrual. This allocation is assumed, not a reported segment allowance.

Raw response bytes, complete retrieval URLs, hashes, timestamps and transformation metadata are retained. Offline replay verifies source bytes and processed outputs, including when a copied project root is supplied. The instruction PDF was inspected through web research, but its direct byte download returned HTTP 403; the manifest does not claim a saved PDF hash. The bank and fitted Treasury zero curve share the observation date. Both are later retrieved vintages, with no established bank-quarter publication timestamp. Observation-date alignment does not make this an information-available-at-the-time backtest.

## Asset segmentation and cash flows

The primary reconstruction uses 26 reported bands and 52 modeled subsegments/residuals. `SCNM`, `SCPT`, `LNRS` and `LNOT` bands combine fixed remaining maturity with floating next repricing. The model assumes fixed shares of 90%, 90%, 80% and 20% respectively. Representative band horizons are 2, 8, 24, 48, 120 and 240 months. Fixed subsegments mature at that horizon. Floating subsegments reset there and mature at the later of 60 months or 12 months after reset. A reset never by itself redeems floating principal.

Loans and first-lien mortgage pass-through securities use level original principal installments plus prepayment. Other debt securities use bullets. Other MBS report weighted average life; 24- and 60-month fixed-rate bullet proxies represent their two disclosed bands and do not recover a contractual MBS schedule. A sale reduces remaining scheduled installments proportionately. All remaining performing principal is collected at modeled maturity, after which income stops. Nonaccrual and equity residuals have no modeled coupon or principal recovery and are valued at net book; additional loan-loss overlays can reduce the nonaccrual loan book.

Coupons and within-band fixed/floating splits remain assumptions. Floating coupons change after the reset month by the scenario change in the short-rate proxy, floored at zero. Annual CPR converts to monthly SMM as `1 - (1 - CPR)^(1/12)` and applies after scheduled principal. The same explicit CPR proxy governs loans and first-lien mortgage pass-throughs; it is not an independently calibrated MBS model. [CASH_FLOW_COVERAGE.md](CASH_FLOW_COVERAGE.md) details all source fields, exclusions and allocation assumptions.

The aggregate comparison instead uses a single fixed-coupon security bullet and two amortizing loan pools. Segmentation is optional in the engine and does not change this saved reference configuration.

## Discounting and EVE

For a cash flow at year `t`, PV is `CF(t) * exp(-(z(t) + spread) * t)`. Continuous zero yields interpolate linearly and remain flat beyond source endpoints. Non-swap coupons accrue at one twelfth of annual rate per model month. Loan and funding discount spreads are explicit constants. EVE is assumed asset PV less liability PV; it is not book equity. Cash, other assets/liabilities and separately identified static residuals stay at book.

Primary EVE and the operating ledger share security/loan schedules. Noninterest and interest-bearing deposits amortize over separate behavioral lifetimes for EVE. Interest-bearing deposits reprice after a lag using beta times the short-index change and a floor. Requested scenario runoff is accelerated to opening repayment in EVE, with the remaining deposits following their assumed schedule. The operating ledger instead stages withdrawals and otherwise retains deposit balances. These deliberately distinct conventions answer different ALM questions, not one identical lifetime business forecast.

Original wholesale funding reprices immediately and matures beyond the one-year ledger. Prefunding adds equal cash and fixed-rate three-year debt before the shock. Each policy EVE delta compares its own shocked and unshocked values, including the same par swap and upfront fee. Later reactive borrowing and sales do not enter opening EVE. Collateral exchanges substitute assets or add equal assets/liabilities; future collateral carry is measured in earnings.

EVE excludes future operating expense and new credit-loss overlays. Those one-year proxies are not calibrated lifetime credit/franchise cash flows. EVE therefore remains an interest-rate valuation before those future costs, while modeled earnings deducts them. The retained-pledged-proceeds challenge also changes cash availability and subsequent earnings without imposing a new opening EVE illiquidity haircut.

## Rate shapes, deposit evidence and nonlinear response

The selection set is the baseline plus parallel +/-200 bp, steepener, flattener, short-rate up/down and +200 bp with 45% deposit runoff. With `d=exp(-t/4)`, the steepener is `-65*d + 90*(1-d)` bp, flattener `80*d - 60*(1-d)` bp and short shocks `+/-250*d` bp. These are research scenarios, not prescribed supervisory shocks. Full node profiles are saved; headline bps for a shaped case refer to its quarter-year node.

The short index is `(exp(z(0.25)*0.25)-1)/0.25`. Floors apply to income yields and coupons. CPR responds as `min(maximum_CPR, base_CPR * exp(-sensitivity * short_index_change))`. Floors, prepayment, amortization, capped funding and sale availability create nonlinear results.

Historical deposit expense is converted from reported year-to-date to quarterly flow and divided by the mean of adjacent domestic interest-bearing deposit balances. That denominator approximates exposure; it is not a reported daily/weekly average. The latest annualized quarterly proxy, about 1.820%, anchors the primary starting deposit cost.

The lagged historical model uses 44 quarterly observations, with training from 2015 Q1 through 2023 Q4 and holdout from 2024 Q1 through 2025 Q4. Its fitted persistent-response beta is about 0.342. Holdout RMSE of 41.46 bp is worse than the 19.15 bp training-end persistence benchmark. Accordingly, the engine retains the 0.5 research beta, adds the estimate to sensitivity and does not present either as a validated forecast. The holdout conditions on realized policy rates and later data vintages; it is not a live forecast or publication-time backtest. Full fit diagnostics and denominator limitations are saved with research evidence.

## Business costs and financial measures

The primary annual operating-expense rate is reported 2025 noninterest expense, $4.166 billion, divided by opening total assets. Each month deducts opening assets times that annual rate divided by 12. Expense reduces equity and accrues a payment obligation, then settles subject to available free cash.

The annual new credit-loss rate is reported 2025 net loan chargeoffs, $513 million, divided by opening net loans. Each month deducts beginning net loan book times that rate divided by 12, before principal. It is a noncash reduction of loans and equity, allocated across all net loan segments, including nonaccrual. It is an assumed future loss proxy; opening allowance is already reflected in net book and is not deducted again. Historical provisions remain context and are not added to the charge. The charge declines with runoff, so annual modeled losses differ from $513 million.

The measures are distinct:

| Saved measure | Definition |
|---|---|
| `nii_12m_usd` | Bank asset interest less deposit/funding interest |
| `hedge_adjusted_interest_earnings_usd` | Bank NII plus net swap coupons and posted-collateral interest |
| `modeled_earnings_usd` | Above plus securities-sale PNL and terminal swap closeout, less swap fee, operating expense and new credit loss when enabled |
| `delta_eve_usd` | Opening shocked EVE less the same policy/configuration's unshocked EVE |

The primary objective excludes noninterest income, including reported 2025 income of $2.441 billion, taxes, distributions, other omitted fees and OCI. It is not GAAP net income and has no positive-profit constraint. Accrued unpaid amounts still reduce equity. With the derivative closed at month 12, modeled earnings equal ending equity less opening equity. The aggregate comparison excludes business-cost overlays and therefore has a different earnings basis.

## Monthly accounting and constrained liquidity

Opening prefunding and the swap fee/mark/collateral occur at time zero. Each later month follows this order:

1. Earn bank interest on beginning balances and accrue deposit/funding interest. Earn posted-collateral interest on the prior actual balance.
2. Accrue operating expense and reduce loan book/equity for new credit loss. Collect loan and security principal; transfer any retained pledged portion to restricted cash.
3. Recognize swap coupon and ex-coupon mark changes. At month 12 exchange the remaining derivative for its closeout amount.
4. Release excess posted collateral, segregate received variation margin, add new withdrawal requests and calculate funding need.
5. Raise cash by the chosen borrowing/selling order, subject to both global and remaining-inventory caps. Settle payment obligations, initial margin, variation margin and withdrawal requests in that order.

Assets run off without replacement originations or reinvestment. Deposit interest/noninterest proportions remain at their opening mix as withdrawals settle. Borrowing adds equal cash and debt, begins accruing in the next month and is not repaid in this horizon. Its cap includes prefunding plus reactive draws; availability and pricing remain assumed.

Security sales remove book, add cash and recognize proceeds minus book in equity. Each segment's sale price ratio is stressed/base PV of its remaining modeled flows, using their respective CPR assumptions. Aggregate ratio is proceeds divided by book sold. This relative-PV convention does not claim reported securities are actually at par. The original cap is 80% of opening securities. The primary additional constraint allocates reported $20.926 billion of pledges proportionately and excludes equity securities, leaving $12.682 billion of initial unpledged debt eligible for sale. Sales never consume pledged book; principal runoff reduces its remaining balance proportionately.

Default `release_on_payment` makes collected security principal free cash, assuming maturity proceeds can be released without substitution. The separate `retain_cash_collateral` challenge transfers the beginning pledged share of collected principal into `pledged_cash_usd`, earns no interest on it and retains it through month 12. `pledged_principal_cash_flow_usd` records the transfer. It preserves assets/equity but cannot finance withdrawals, costs or swap margin. No terminal release is invented. This tests a legal-liquidity assumption not established by aggregate source data.

Unsettled withdrawal requests remain deposit liabilities and retry later; unpaid costs/coupons/fees become payment payables. Unfunded margin is disclosed without inventing posted assets. Historical breaches remain after recovery. The engine introduces no negative or balancing cash. Continuing a path after an uncured margin/payment breach is diagnostic and does not assume counterparty forbearance.

## Swap and collateral accounting

Thirty policies combine prefunding of 0%, 3% or 6% of opening assets, borrowing-first or selling-first liquidity, and payer-swap notionals of 0%, 5%, 10%, 15% or 20% of assets. The five-year swap pays monthly ACT/365F using trade-day/month-end dates with no holiday adjustment. It is struck at unshocked par before stress; the first fixing is held, later coupons follow shocked forwards, and deterministic discount-factor ratios roll the curve. This is a Treasury proxy, not market SOFR projection/discounting.

The model assumes bilateral collateralized-to-market treatment, not actual cleared settlement: 2% initial margin, one-basis-point upfront fee and zero variation threshold. Posted initial/variation margin replaces free cash with collateral assets. Received margin is segregated with an equal return liability and cannot finance the bank. Received interest and the amount owed to its provider net to zero. Posted collateral earns the disclosed curve-implied interval rate on actual prior posted balance. No counterparty default, legal netting, execution spread or intramonth margin path is modeled.

A signed derivative asset and matching equity mark are recognized at opening and updated each month. Net coupons and ex-coupon mark changes are distinct. Terminal settlement converts the derivative to cash or a payable with no second PNL recognition; marks telescope to the terminal value. Actual swap collateral is released/returned at closeout, while any retained pledged-security cash remains restricted. The full balance sheet includes free/restricted cash, loans, securities, other assets, derivative and posted/received collateral against deposits, funding, other liabilities, collateral-return liability, payables and equity.

## Selection, challenges and reverse stress

All candidates share a 1.5%-of-assets free-cash floor, 10%-of-assets additional funding cap, the applicable security-sale caps, a 25%-of-opening-equity EVE-loss limit and zero permitted unfunded withdrawals, margin or payment obligations within tolerance. The objective maximizes worst modeled earnings across the baseline and seven named scenarios. Negative objective values are allowed. A candidate cannot become feasible by weakening a risk limit. If none passes, the highest-objective infeasible candidate is labeled diagnostic and remains unselected.

Selection is finite-grid, in-sample model comparison. The saved primary choice is 6% prefunding with a 10% hedge, 14/30 feasible; the preserved aggregate choice is 6% with 5%, 22/30 feasible. Frozen-policy challenges do not reoptimize after failures. Primary challenges comprise 20 unseen rate/runoff combinations, six behavioral cases, four alternate curve cases and four asset-segmentation/collateral-release cases: 25 pass and nine fail. The aggregate comparison passes 24 of 30. These are hypothetical model challenges, not empirical future outcomes, scenario probabilities or proof of robustness. Alternate curve cases recalibrate hypothetical inception par coupons; they do not revalue an already executed unchanged trade.

The unhedged reverse-stress grid reports the first failing sampled cell in ascending parallel shock, then runoff order. This is not a continuous minimum shock, a shared severity ranking or a bank failure probability. Behavioral sensitivity varies beta, deposit maturity and CPR under +/-200 bp; each modified set uses its own baseline. Deposit maturity changes both buckets to the chosen value, while primary defaults differ by bucket. Selected-policy NII changes use its own baseline, separately from the unhedged reference.

## Validation and remaining evidence

Inputs reject broken accounts, nonfinite values, invalid dates/rates/tenors, incompatible source scopes and malformed configurations. Engine checks cover every computed opening/month-end path. Independent verification reconstructs saved cash, debt, deposits, earnings, derivatives, collateral, restricted cash and per-segment inventories, including principal/loss/sale conservation and pledged availability. Technical checks use an absolute $1 tolerance; actual saved residuals are far smaller than source rounding. A modeled risk breach is a valid financial finding, not a numerical failure.

Full compressed artifacts retain all segment evidence; presentation JSON is a reduced view, and raw-source replay remains offline. Meaningful tests cover analytical PV, reset without redemption, final principal collection once, notional-invariant sale pricing after amortization, source tamper rejection, exhausted liquidity, costs, collateral segregation, unpaid obligations, unchanged zero-hedge regression and restricted-principal wealth conservation. These establish implementation consistency without validating assumed contract behavior.

The strongest unresolved evidence is actual fixed/floating exposure within the reported bands, contractual floating maturities, prepayment behavior, deposit durability and contractual pricing, legal collateral release, actual funding capacity and market hedge curves. Cash limits cover time zero and month ends, leaving intramonth peaks unobserved. The [Basel interest-rate-risk framework](https://www.bis.org/committees/bcbs/basel-framework/standard/srp/31/inforce/2026-01-01/published/2024-07-16) supplies conceptual earnings/EVE terminology; this application does not claim to implement the standard or its supervisory requirements.
