# Validation record

Date: October 2, 2026 (America/New_York); release verification continued into October 3 UTC. Scope: version 1.0, the Regions Bank December 2025 public research case, its aggregate reference, historical calibration, challenge scenarios and editable Excel case. Technical checks establish source consistency and implementation behavior; they do not establish a bank forecast or customer-behavior model.

## Source controls

- Four pinned official FDIC response/definition records reproduce the opening snapshot exactly. Seven accounting identities have zero-dollar residuals. Consolidated equity includes the reported $60m noncontrolling interest.
- The pinned Federal Reserve archive, acquisition manifest and selected observation pass hashes. Reconstructed Svensson rates differ from 30 published zero yields by at most 0.004950 bp, below the 0.006 bp tolerance. Sub-one-year extrapolation remains disclosed and challenged.
- Eight pinned historical/definition/availability records support 44 quarters. All 264 historical accounting checks reconcile. YTD-to-quarter conversion handles year boundaries and agrees with the quarterly deposit-expense field. Missing observations fail rather than being filled.
- Training uses 36 quarters through 2023; eight 2024–2025 quarters are held out. Tests confirm holdout targets cannot affect fitting. The lag model's 41.46 bp holdout RMSE is worse than persistence at 19.15 bp; the fitted beta is not promoted. The exercise uses realized rates and later source vintages, with an endpoint-average deposit denominator and unknown publication timestamps.
- Two pinned FDIC maturity/definition records provide 26 bands. Three dollar bridges reconcile securities and gross/net loans. Pledge allocation, fixed shares, representative tenors and floating contractual lives remain assumptions.
- Source joins verify bank identity/date, ending balances and annual cost flows. Processed-data drift, raw-byte tampering and wrong copied-project roots fail verification.

## Numerical and failure tests

`python -m unittest discover -s tests -v`: **86 tests passed**.

Coverage includes analytical bond/swap prices, dated accruals and locked fixing, terminal settlement, principal conservation, deposit withdrawals, exhausted funding, prefunding, sale PNL, rate floors, input rejection and unchanged inputs. The original eight zero-hedge results match the unchanged v1 fixture within $0.0001 for monetary fields; other fields remain exact. Implicit and explicit zero-hedge dispatch remain exactly equal on the same host.

Linux publication checks exposed last-bit differences from Windows in native exponential calculations. Curve replay allows absolute roundoff of at most 1e-14 in decimal zero rates and 1e-10 bp in the derived published-yield error. Source hashes, metadata, fitted parameters and tenors remain exact, and replay never rewrites pinned inputs. Dedicated tests accept one-ULP differences while rejecting changes beyond these bounds, material rate changes, altered metadata, invalid types and nonfinite values. Release input and artifact hashes still require byte-for-byte equality.

The extended tests cover cash operating expenses versus noncash credit losses, unpaid expense liabilities, reset-versus-maturity behavior, per-band principal/loss/sale conservation, pledge inventory, prohibited encumbered sales and retained principal as unspendable restricted cash. Full-to-compact gzip roundtrips preserve all aggregate accounts and authoritative per-band detail. Frozen-policy challenge tests preserve selection, retain failures and reject altered cash paths. Calibration tests cover constrained estimates, rank deficiency, missing observations, chronology and denominator/day-count scope.

The main case has **20 runtime controls**; the preserved aggregate case has **16**. Both require every control to pass before a report can be published. Checks include initial events and months 1–12, plus grid and sensitivity runs.

The independent saved-ledger audit reconstructs cash, collateral, derivative marks, coupon and closeout identities, costs, credit losses, equity, unpaid obligations and policy summaries without calling engine valuation or ledger helpers. It also verifies per-band cash/inventory and restricted pledged-principal transfers.

| Audit | Paths | Monetary comparisons | Maximum residual, USD |
| --- | ---: | ---: | ---: |
| Primary: eight unhedged scenarios and 30 × eight candidate scenarios | 248 | 1,637,045 | 0.00006104 |
| Aggregate reference: same grid | 248 | 123,111 | 0.00006104 |
| Primary challenges: 34 cases, each with policy/reference and baselines | 136 | Reported as path audit | 0.00006104 |
| Reference challenges: 30 cases, each with policy/reference and baselines | 120 | Reported as path audit | 0.00009156 |

Monetary tolerance is $1; date fractions and interval-return checks use a separate 1e-12 tolerance. Audit artifacts are `independent_audit.json`, `reference_audit.json` and `robustness_audit.json`.

Meaningful tampering tests alter balances, derivative marks, collateral, coupons, interest, payables, terminal settlement and per-band flows. A passing runtime-control list cannot override an independent audit failure. Fingerprint guards run both after calculation and after artifact writing; a detected parallel workbook-source edit required a clean rebuild. Both reports show a blocked page during a build or after a failure. Old evidence cannot establish that a later attempt succeeded.

## Release and dashboard

The final `python -S scripts/build_report.py` and `python -S scripts/verify_release.py` both passed. Build start: **2026-10-03 02:39:31 UTC**. Manifest SHA-256: `96dbdd26a26dacd5af25440cb5e6286d125cebccea1097ebea635c13d24f6d8c`. The CLI checks current input/code hashes, artifact hashes, source replay, full/compact equivalence, selected-policy consistency, saved research summaries and all four audit groups.

`node scripts/check_report.cjs` passed for both primary and reference reports. It covers escaping, selection, chart and ledger rendering, data-download logic and fail-closed output. Chrome verification of the final v3 report confirmed selected/reference switching while preserving the falling-rate scenario, $4.31bn versus $4.76bn bank NII, $1.80bn required/posted collateral, negative $1.74bn modeled earnings, 13 opening/monthly events with 31 displayed account columns, and updated cost/restricted-cash labels. The downloaded combined-case CSV contains 13 events and 69 fields; 884 numeric cells exactly match the saved scenario within 1e-5 USD. The browser download-event listener timed out, but the actual downloaded file was found and independently validated.

The source/calibration cards, eight holdout predictions, encumbrance bridge, cost drivers and expanded failed-challenge table rendered correctly. The original-case link opened its separately labeled 22/30, 6%/5% report. No browser warning/error logs were reported. The blocked-build page was observed while the final build ran. Desktop browser coverage does not establish mobile or assistive-technology coverage.

## Excel

The separate live case does not run the full engine. Fixed engine imports include all 248 aggregate paths / 3,224 opening-and-monthly events; per-band details remain in the authoritative external gzip. The builder tests case selection, representative edits, blank versus zero, invalid assumptions, recalculation and formula errors. The read-only XLSX checker independently reconstructs prices and cash/loan-book rollforwards, verifies source/import hashes and native chart bindings. Deposit expense was corrected to opening balances consistent with month-end withdrawals, and shared input bounds now propagate unavailable values. The authoring gate was observed rejecting both an edited source fingerprint and an in-progress engine build before export.

The final production workbook passed rebuild/recalculation, input edits/restoration, **102 independent numeric comparisons**, all **2,103 cached formulas** without errors, seven-sheet coverage and one native-chart binding check. Twelve current preview ranges covering every tab were visually inspected. The final independent XML check was rerun successfully against the saved XLSX. Artifact Tool recalculation was tested; native Microsoft Excel application behavior was not separately exercised.

Workbook SHA-256: `90a391872aea7e6e0759e5c5b2f32132a3856ab023bec5036964e09d59258d64`. Imported analysis SHA-256: `8d63dec2804b5a9b681979d84317906723a9bf464e764e181a8f7ff9594b682a`. Both align with the final manifest above. The adjacent `workbook_previews/independent_validation.json` records those hashes and checks; `validation.json` records edit/recalculation outcomes. Obsolete previews and the exporter inspection sidecar were removed.

## Interpretation

The primary grid has 14/30 feasible candidates and selects 6% prefunding with a 10% payer hedge. The earnings objective includes explicit costs and excludes noninterest income; its worst selection-scenario result is negative. Feasibility has no positive-earnings floor. The frozen policy passes 25/34 additional challenges. Failures include high runoff, prepayment/deposit assumptions and a +25 bp proxy-curve change; they are retained without reselection. The aggregate reference has 22/30 feasible candidates, selects 6%/5%, and passes 24/30 challenges. These are hypothetical model results, not empirical future performance or regulatory validation.
