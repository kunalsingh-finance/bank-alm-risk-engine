# Bank ALM research engine — implementation contract

Build a reproducible local research application for one bank legal entity. Source balances and historical earnings from an official FDIC snapshot. Reconstruct simplified cash flows with explicit assumptions; this does not recover the bank's internal ALM model.

## Inputs

- `data/processed/bank_snapshot.json`: schema_version, bank_name, certificate, as_of, legal_entity, source_records, balance_sheet_usd, totals_usd, earnings, field_mapping, derived_field_notes, reconciliations.
- `balance_sheet_usd`: cash, securities, loans, other_assets, noninterest_deposits, interest_deposits, wholesale_funding, other_liabilities, equity. Money is USD. Assets = cash + securities + loans + other_assets. Liabilities + equity = deposit buckets + wholesale_funding + other_liabilities + equity.
- `data/processed/curve.json`: as_of, source, source_sha256, tenors_years, zero_rates (annual continuously compounded decimals). Source dates must be no later than the bank date. Interpolation is linear in zero rates; endpoints flat.
- `configs/assumptions.json`: all behavioral, tenor, coupon, repricing, capital/funding, scenario and policy choices, each documented as research assumptions. Public balances and model assumptions must remain visibly distinguishable.
- `data/processed/history.json`, `calibration.json` and `maturity_profile.json`: replayable official quarterly evidence, a fit with a chronological holdout, and reconciled maturity/repricing bands. Verify all source hashes at the requested project root; joins must agree on bank identity, observation date, opening balances and annual cost flows.
- `configs/research_case.json`: explicit source/scaling choices for the primary case. `prepare_research_inputs` combines them with the preserved aggregate assumptions. A failed holdout must not silently replace the assumed engine beta.

## Engine

`bank_alm.engine.run_analysis(snapshot: dict, assumptions: dict, curve: dict) -> dict` is the application boundary. `bank_alm.engine` owns bank-ledger validation; `bank_alm.swaps` owns dated swap cash flows and value. The implementation uses Python's standard library only. No live network calls occur during a build.

Output contract:

- `schema_version`, `bank` (name, certificate, as_of), `units`.
- `baseline`: modeled 12-month NII, EVE and reported historical NII (different measures, never force-reconciled).
- `scenarios`: list with `id`, `name`, `description`, `rate_shock_bps`, `deposit_runoff_pct`, `eve_usd`, `delta_eve_usd`, `nii_12m_usd`, `delta_nii_usd`, `min_cash_usd`, `peak_wholesale_funding_usd`, `securities_sold_usd`, `realized_sale_pnl_usd`, `status`, `breaches`, `monthly`.
- `monthly`: rows with month, cash_usd, securities_usd, loans_usd, deposits_usd, wholesale_funding_usd, equity_usd, interest_income_usd, interest_expense_usd, nii_usd, asset_sales_usd, sale_pnl_usd, accounting_residual_usd. Extra explanatory columns are allowed.
- `policies`: candidate outcomes under a disclosed set of scenarios; objective and constraints stated. A no-feasible-policy result is valid. No in-sample result is called independently validated.
- Each candidate saves all eight complete scenario ledgers, including `initial_event` and months 1–12. Derivative value is signed; posted collateral, segregated received collateral, its return liability and unpaid payment obligations are separate accounts. `min_cash_usd` preserves the original month-end metric; `minimum_observed_cash_usd` includes the opening event.
- `policy_analysis`: exact saved candidate details with a `selected` or `diagnostic_unselected` status. `hedge_comparison` compares that candidate with the unchanged unhedged reference; it must not attribute prefunding effects entirely to the hedge.
- `reverse_stress`: evaluated shock/runoff grid or path, first observed failing point and search limitations.
- `sensitivity`: deposit beta/behavioral maturity/prepayment assumption ranges with model result differences.
- `checks`: named numerical/accounting/input checks with pass/fail, actual and tolerance where applicable. Failures block a verified report.
- `limitations`, `assumptions`.

## Numerical scope

Use cash, fixed-rate securities, fixed/floating loan pools, noninterest and interest-bearing deposits, wholesale funding and other book accounts. Model asset cash flows, deposit repricing/withdrawals, a 12-month earnings and funding ledger, and economic-value sensitivity under parallel and shaped rate shocks. Model swap hedges only with documented conventions and cash/collateral accounting. Avoid unsupported regulatory ratios or claims of regulatory compliance.

Cash withdrawals must be funded by existing cash, disclosed capped borrowing, or sales whose proceeds and book cost reconcile. An exhausted funding capacity must remain an explicit breach. Do not manufacture balancing cash or hide negative balances. NII flows to equity; actual operating expenses, taxes and credit losses are excluded unless explicitly modeled. Preserve a closed modeled accounting identity every month.

The primary case uses reported asset bands with explicit representative tenor and unknown fixed/floating-share assumptions. Preserve source-band amounts, residual equity/nonaccrual treatment, pro-rata loan allowance and per-band cash flows/inventory. Securities sales exclude pledged and ineligible assets. Track principal from pledged assets as either released cash under the stated base assumption or restricted cash under the conservative challenge. Operating expense reduces equity and becomes a cash payment or explicit payable; credit loss reduces loans and equity without a second cash charge. Neither reported provision nor noninterest income is silently added. Preserve the earlier aggregate, no-cost case as a separate reference.

Freeze the selected policy before unseen scenario evaluation. Save scenario and curve overrides, behavioral/segmentation assumptions, complete results and failures. Alternate proxy-curve tests recalibrate a hypothetical initial par swap; label that distinction. Do not retune policy selection using challenge outcomes.

## Delivery

CLI builds JSON/CSV evidence and a self-contained HTML dashboard/report. The dashboard explains public data versus assumed behavior, compares NII and EVE, shows monthly funding movements, reports policy feasibility and supports an interview walkthrough. Save exact input/code hashes and reproducible source snapshots. Deliver a clear model methodology, validation record, and decision memo based on computed results.

Before publishing a verified local report, independently reconstruct all reference and candidate ledgers without calling engine valuation or ledger helpers. Save that audit in `independent_audit.json`. Export all policy scenarios and events, including time zero, to `policy_scenarios.csv` and `policy_ledgers.csv`. The manifest covers these exports, the comparison and the report. A failed source, runtime or independent audit blocks the new report.

Release schema v3 saves authoritative full JSON as gzip, including every per-band cash flow and inventory. Compact JSON omits only per-band arrays and retains all aggregate candidate ledgers; verify equivalence to the full evidence. Dashboard payloads may omit undisplayed candidate ledgers to keep browser size manageable, with separate full-evidence access. Audit the primary case, aggregate reference and frozen-policy challenges. Guard fingerprints both after computation and after artifact writing so a concurrent implementation edit cannot publish a mixed release.

Deliver an editable Excel case with live formulas, clearly fixed engine imports, source hashes, documented simplifications, tested edits/recalculation and visual inspection of every sheet. Deliver a current decision memo, five-minute walkthrough, limitations/counterargument, honest case study and requirement-by-requirement completion audit. Workbook verification supplements the engine release manifest and checks that imported data matches the current saved release.
