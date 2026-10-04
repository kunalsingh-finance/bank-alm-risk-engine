# Project completion requirements

Scope: the Bank ALM & Liquidity Risk Engine described in `ROADMAP.md` and `BUILD_CONTRACT.md`, including its research evidence and analytical documentation. This file records requirements; completion evidence is in the linked audit.

| Requirement | Evidence required before completion |
| --- | --- |
| Reproducible public inputs | Pinned official legal-entity balances, curve and new historical/maturity sources; definitions, units, observation dates, capture dates, publication-date evidence or an explicit evidenced availability limitation; offline source replay and tamper rejection. |
| Deposit calibration | Consistent quarterly interest expense and appropriate deposit denominator; correct YTD-to-quarter conversion; lagged model fitted on an earlier interval; chronological holdout predictions, benchmark errors and uncertainty; no future data in fitting. |
| Sourced cash-flow bands | Actual maturity/repricing categories with reconciled coverage and exclusions; explicit representative-tenor assumptions; engine uses the sourced segments in an inspectable extended case while preserving the original aggregate case as a labeled regression reference. |
| Broader earnings costs | Separate operating-cost and credit-loss assumptions, linked to observed ratios when definitions permit; reconciled impact on earnings, cash, assets and equity; no presentation as forecast net income. |
| Model-risk and unseen scenarios | Policy fixed before unseen rate/runoff tests; behavioral uncertainty; alternate proxy curves and short-end extrapolation tests; failures retained and no retuning to test outcomes. |
| Dashboard and exports | Inspectable source/calibration/segmentation/robustness results, distinct reference and extended cases, complete scenario/ledger exports, local offline report and fail-closed verification. |
| Editable Excel case | One documented workbook with useful live formulas and editable assumptions; fixed engine imports explicitly identified; recalculation and representative edits tested; all sheets visually inspected and saved without formula errors. |
| Research documentation | Current decision memo, limitations and counterargument, technical case study and reproducible launch instructions. |
| Release verification | Meaningful unit and integration checks; independent saved-ledger audit; source/artifact hashes; CLI and browser checks; final workbook verification; requirement-by-requirement completion record against current artifacts. |

Actual bank internal forecasts, customer-level withdrawal data, executable dealer quotes and regulatory approval cannot be inferred from this public research project. Any source or estimation limitation must remain visible in the final research conclusions.

Completion review: the research requirements above were checked against the final local release on October 2, 2026. See [COMPLETION_AUDIT.md](COMPLETION_AUDIT.md) for requirement-by-requirement results and [VALIDATION.md](VALIDATION.md) for the observed verification evidence.
