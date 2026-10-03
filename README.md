# Bank ALM & Liquidity Risk Engine

A reproducible research application for bank earnings, economic value and liquidity under interest-rate and deposit-withdrawal stress. Version 1.0 uses **Regions Bank, FDIC certificate 12368, at December 31, 2025**. It combines official public data, dated swap and collateral cash flows, constrained policy selection, historical deposit-cost estimation and separate challenge scenarios.

**[Explore the live dashboard](https://kunalsingh-finance.github.io/bank-alm-risk-engine/)** · **[Download the editable Excel case](https://kunalsingh-finance.github.io/bank-alm-risk-engine/Bank_ALM_Case.xlsx)** · [Read the decision memo](docs/DECISION_MEMO.md)

The main case selects **6% prefunding with a 10%-of-assets payer-fixed hedge**. Fourteen of 30 policies meet the eight selection scenarios. The selected policy passes 25 of 34 additional challenges and fails nine; it can also produce negative modeled earnings while meeting the selection constraints. These are decisions inside a disclosed reconstruction, not findings about Regions Bank's internal risk position.

## Open or rebuild

Open [the saved dashboard](output/report.html), or double-click `Launch ALM Report.cmd` to rebuild, verify and open it. Python 3.11 or later is required for the engine; it has no third-party runtime dependencies.

```powershell
python -S scripts/build_report.py
python -S scripts/verify_release.py
```

Builds replay pinned official inputs offline. The dashboard is self-contained; keep the `output` folder together to use its separate full-evidence download. [The aggregate reference report](output/reference_report.html) preserves the earlier model for comparison.

```powershell
python -m unittest discover -s tests -v
node scripts/check_report.cjs output/report.html
python -S tests/check_workbook.py
```

## What is delivered

- A reconciled public bank balance sheet and Federal Reserve fitted Treasury curve, with source bytes, field definitions, capture dates and checksums.
- Forty-four quarterly observations, correct YTD-to-quarter flows, a constrained distributed-lag deposit-cost fit and a chronological holdout against simple benchmarks. The fitted beta performs poorly on holdout and is not promoted to the engine default.
- Twenty-six official maturity/repricing bands feeding 52 modeled asset segments, with gross-to-net loan reconciliation, explicit tenor/fixed-share assumptions and an unpledged securities-sale constraint.
- Twelve-month cash, funding, collateral, loan-loss, operating-expense and equity ledgers. Requested withdrawals and unpaid obligations remain visible when capacity is exhausted.
- Dated pay-fixed/receive-floating swaps, locked first fixing, market value, segregated received collateral and a month-12 unwind.
- Thirty joint hedge/funding candidates under common limits; an unchanged reference case; reverse stress; behavioral sensitivities; 34 additional primary-case challenges with the policy fixed before evaluation.
- An [editable Excel case](outputs/01a0fce5-927e-7883-9b51-671e6a527eaa/Bank_ALM_Case.xlsx) with live simplified earnings, cash and swap formulas, alongside explicitly fixed engine imports. Read its [formula scope and rebuild instructions](docs/EXCEL_CASE.md).
- A [decision memo](docs/DECISION_MEMO.md), [five-minute walkthrough](docs/INTERVIEW_WALKTHROUGH.md), [project case study](docs/PROJECT_CASE_STUDY.md) and [release validation record](docs/VALIDATION.md).

## Evidence and exports

`output/analysis.json` retains every candidate's aggregate scenario/event ledger. `analysis_full.json.gz` also retains each asset band's cash flows and inventory. The same compact/full pairing exists for the reference case and robustness runs. CSV exports cover scenarios, candidate comparisons and all candidate ledger events. Calibration, maturity coverage, historical observations, independent audits and source provenance are saved separately. `manifest.json` binds the release to exact input, implementation and artifact hashes.

The build requires both engine controls and an independent saved-ledger audit before publishing the local report. Source changes, tampered artifacts or interrupted builds invalidate verification. A failed or in-progress build displays a blocked page; old files cannot establish success for the new attempt.

Source replay commands:

```powershell
python scripts/fetch_bank_data.py --offline
python scripts/prepare_curve.py --as-of 2025-12-31
python scripts/fetch_history.py --offline
python scripts/fetch_maturity_data.py --offline
```

Intentional source refreshes can retrieve revised historical records and require a new build. See [sources](docs/SOURCES.md), [calibration](docs/CALIBRATION.md), [cash-flow coverage](docs/CASH_FLOW_COVERAGE.md), [methodology](docs/METHODOLOGY.md) and [swap conventions](docs/SWAP_CONVENTIONS.md).

## Research boundaries

Opening assets are $157.412bn, deposits $131.987bn and consolidated equity $18.131bn, including $60m of noncontrolling interests. Reported 2025 NII is $5.059bn. The legal entity is the insured bank and its consolidated subsidiaries, not Regions Financial Corporation. Sources were captured in October 2026; exact historical filing/publication dates were not obtained. The holdout conditions on realized policy rates and is a conditional hindcast, not a tradable historical forecast.

The main case includes operating-expense and credit-loss proxies scaled from reported annual flows. It excludes noninterest income, taxes, new business, distributions and OCI, so modeled earnings are not forecast net income. Economic value does not capitalize those future cost proxies. The original aggregate reference excludes these added costs.

Treasury-based swap projection and discounting, monthly ACT/365F payments, collateral terms, funding access, customer behavior, representative asset tenors, unknown fixed/floating shares and treatment of principal from pledged assets are research assumptions. Actual SOFR curves, dealer quotes, customer-level data and contractual encumbrance-release terms are unavailable. Regulatory LCR/NSFR, internal model validation and regulatory approval are outside scope. Technical checks establish source and calculation consistency, not forecast accuracy.

AI assistance contributed to implementation and documentation. Present this as a personal research project, and use only calculations and decisions you understand and can defend. [The completion audit](docs/COMPLETION_AUDIT.md) maps the agreed scope to its evidence.

## Publishing

GitHub Pages serves the saved, verified report and Excel workbook. On a push to `main`, the publishing workflow checks release fingerprints, independently audits the saved ledgers, runs the 80-test suite, checks both report renderers and verifies the workbook imports before deployment. It publishes the same saved report bytes at `index.html` and `report.html`, preserving the reference report and evidence downloads. Financial results are not refreshed automatically. After changing model inputs or code, rebuild and verify the release and workbook locally before pushing. See [GitHub's custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
