# Bank ALM research: earnings, economic value and liquidity

An AI-assisted personal research project using public data for **Regions Bank, FDIC certificate 12368, at December 31, 2025**. It combines a reproducible source pipeline, a balance-sheet stress engine, a dated swap and collateral ledger, historical deposit-cost analysis and an inspectable local report. It is portfolio research, not employment at the bank or a production treasury system.

## Problem

A rate hedge can improve economic value while creating a cash call. A security balance can look liquid while being pledged. A fitted deposit beta can look plausible while predicting worse than a constant benchmark. The project makes those conflicts explicit instead of treating a favorable earnings result as a complete risk decision.

## Method

The source pipeline pins exact official FDIC and Federal Reserve payloads, their definitions, retrieval timestamps and checksums. The bank identity and accounting totals reconcile before any scenario runs. The opening balance sheet has $157.412 billion in assets, $131.987 billion in deposits and $18.131 billion in consolidated equity. The reported 2025 NII of $5.059 billion remains separate from modeled forward earnings.

The engine projects a twelve-month balance-sheet run-off, deposit repricing and withdrawal requests, capped funding, security sales and retained earnings. EVE discounts longer-horizon assumed cash flows. The hedge extension adds a five-year pay-fixed swap with actual monthly dates, a locked first floating fixing, segregated received collateral and an explicit month-twelve closeout. The fitted Treasury curve serves as a disclosed single-curve proxy.

The primary case replaces aggregate asset buckets with reconciled public maturity/repricing bands. It constrains sale inventory using reported pledged securities and adds explicit operating-cost and credit-loss scale assumptions. The original aggregate case remains a separately labeled reference. Policies share limits, are selected from a finite grid, and are frozen before further scenario and model-assumption challenges.

## Findings worth defending

| Evidence | Finding | Practical interpretation |
|---|---|---|
| 44 quarterly bank observations; 36 training and eight holdout quarters | Estimated total deposit-cost beta is 0.34154 | Aggregate cost response is descriptive and does not identify customer behavior |
| Fixed 2024–2025 holdout | Lag-model RMSE 41.46 bps; persistence 19.15 bps | Keep the disclosed 0.5 primary assumption and challenge it; do not promote a weaker fitted model |
| Reported securities encumbrance | $20.926 billion pledged | Total securities cannot be equated with freely saleable inventory |
| Annual 2025 source flows | Noninterest expense $4.166 billion; net loan chargeoffs $513 million | Add cost/credit scale proxies; do not call the resulting objective GAAP net income |
| Source and model extensions | A policy conclusion depends on asset composition, collateral access and behavioral assumptions | Preserve the original case and disclose why a revised primary case changes the answer |

The latest policy selection and challenge failures are shown in the verified local report. A candidate passing the selection grid is not a globally optimal policy or an empirically validated bank recommendation. Challenge failures remain visible; they are not used to quietly change the candidate or relax limits.

## Strongest counterargument

Public reporting bands combine fixed contractual maturity with floating next-repricing dates. They do not reveal exact contracts, customer behavior or collateral release rights. The model separates reset from repayment, but fixed/floating shares, representative dates, floating lives and prepayments remain assumptions. Pledged securities' principal receipts also require an explicit cash-release convention. Plausible alternatives can change both liquidity and the preferred hedge.

The deposit denominator uses adjacent domestic interest-bearing balances, not reported daily/weekly averages. The history was retrieved later; exact filing/publication dates remain unknown. Conditional holdout results use realized policy rates. These limits prevent a claim of point-in-time predictive validation even when arithmetic and accounting checks pass.

## Reproduce and inspect

From the repository root, using Python 3.11 or later:

```powershell
python scripts/fetch_bank_data.py --offline
python scripts/fetch_history.py --offline
python scripts/fetch_history.py --verify
python scripts/build_report.py
python scripts/verify_release.py
python -m unittest discover -s tests -v
node scripts/check_report.cjs output/report.html
```

Open `output/report.html` after a successful build. Inspect the source-coverage and calibration sections, compare the primary and original cases, and trace a stressed path from the initial event through terminal settlement. The release audit reconstructs saved accounting independently; source and output tampering must fail verification. The renderer check requires Node.js; the Python analysis uses the standard library.

See [source evidence](SOURCES.md), [calibration](CALIBRATION.md), [cash-flow coverage](CASH_FLOW_COVERAGE.md), [swap conventions](SWAP_CONVENTIONS.md) and the [five-minute walkthrough](INTERVIEW_WALKTHROUGH.md). The project demonstrates source control, financial modeling, numerical testing and clear treatment of uncertainty. It does not demonstrate realized P&L improvement, commercial deployment or complete model validation. AI assistance contributed to implementation and documentation and should be disclosed when discussing authorship.
