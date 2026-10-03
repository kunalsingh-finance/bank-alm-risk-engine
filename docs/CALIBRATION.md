# Historical deposit-cost calibration

The constrained lag model estimates a total deposit-cost beta of **0.34154**, but loses to the persistence benchmark on the fixed 2024–2025 holdout. It is a descriptive challenge sensitivity. The primary engine retains its separately disclosed assumed beta of 0.5. No fitted coefficient is automatically applied to the engine.

## Source and denominator

`data/processed/history.json` contains 44 quarters from March 2015 through December 2025 for **Regions Bank, FDIC certificate 12368, RSSD 233031**. It represents the consolidated insured bank entity, not Regions Financial Corporation. The December 2014 balance is retained as the first denominator's opening observation. Monetary source values are USD thousands and normalized values are USD.

The target is:

```text
quarterly domestic deposit interest expense
  / ((prior quarter-end DEPIDOM + current quarter-end DEPIDOM) / 2)
  * 365 / actual calendar days in quarter
```

`EDEPDOM` supplies domestic deposit interest expense; `DEPIDOM` supplies domestic interest-bearing deposits. `EDEP = EDEPDOM + EDEPFOR` and `DEPI = DEPIDOM + DEPIFOR` must reconcile. Foreign and noninterest-bearing balances do not enter this denominator. Field definitions are pinned from the [official FDIC dictionary](https://api.fdic.gov/banks/docs/risview_properties.yaml).

Q1 expense equals Q1 year-to-date expense; Q2–Q4 expense subtracts the preceding quarter's year-to-date amount. Six separately published quarterly fields give **264 exact reconciliations** across deposit expense, foreign deposit expense, NII, noninterest income, noninterest expense and net chargeoffs. This follows the FDIC's [Call Report income derivation guidance](https://banks.data.fdic.gov/bankfind-suite/help?helpTopic=disclaimers-and-methodologies). The ACT/365F annualization used here is an explicit research convention, not a claim to reproduce a UBPR ratio.

The denominator is an **endpoint-average proxy**, not an observed daily or weekly deposit average. The pinned [March 2017 RC-K instructions](https://www.fdic.gov/system/files/2024-08/2017-03-rc-k.pdf) identify quarterly averages of interest-bearing transaction accounts, savings/time deposits and foreign deposits separately. Those instructions establish the desired scope, but do not supply Regions' historical observations. The public bulk page was inspected; actual RC-K bank records were not retrieved in this implementation. Public Call Report downloads may support that enhancement, so the data are not claimed to be unavailable in principle.

The policy input is the [Federal Reserve Board's daily effective federal funds rate, DFF, distributed by FRED](https://fred.stlouisfed.org/series/DFF). Every calendar day in 2014–2025 must be present. Quarterly means use the supplied daily values with no interpolation or forward/backward filling. Percent source rates become decimals.

## Fit, benchmarks and uncertainty

The model is `cost_t = intercept + b0*policy_t + b1*policy_(t-1) + b2*policy_(t-2)`. Intercept and betas are nonnegative; total beta is capped at one. A deterministic active-set enumeration solves bounded least squares with standard-library arithmetic. Bounds are assumptions, not empirical discoveries. Singular active sets are skipped and the design rank is reported.

Training uses 36 quarters through December 2023. The eight 2024–2025 quarters are untouched by fitting, lag selection or refitting. The conditional analysis uses realized contemporaneous policy rates and later-vintage bank data, so this is **not an ex-ante forecast or a point-in-time historical backtest**.

| Model | Holdout RMSE, bps | Interpretation |
|---|---:|---|
| Train-end persistence | 19.15 | Hold December 2023 deposit cost constant |
| Assumed 0.5 beta | 28.97 | Anchor cost and policy rate at December 2023 |
| Constrained three-period lag model | 41.46 | Fit coefficients only on 2015–2023 |
| Constrained contemporaneous model | 77.01 | Same training split, no lag terms |
| Training mean | 166.73 | Constant training-average cost |

The lag coefficients are 0.09901, 0.03086 and 0.21167, with a 1.835 basis-point intercept. The model underpredicts holdout costs by 40.57 bps on average. Policy-lag correlations reach 0.959 and training residual lag-one correlation is 0.720. Expanding-window total betas range from 0.186 to 0.342. These diagnostics indicate dependence and unstable attribution across lags. The full design has rank four, but that does not resolve economic identification.

No confidence interval is asserted: eight holdout observations, serial dependence, denominator measurement error and constraints make naive unconstrained OLS intervals unsuitable. Deposit mix, mergers, decay and customer retention are not separately identified. Training errors for the train-end anchored benchmarks are retrospective descriptive comparisons, not sequential training-period forecasts.

## Availability and revision limits

Every bank-quarter `publication_date` and `submission_datetime` is null. The FDIC response omits the requested `DATEUPDT`; its dataset-index creation timestamp does not establish an individual filing's publication time.

The [FFIEC web-service documentation](https://cdr.ffiec.gov/public/HelpFiles/PWSInfo.htm) identifies `RetrieveFilersSubmissionDateTime` and requires a registered account and security token. No credentials were supplied or requested. The captured [public bulk page](https://cdr.ffiec.gov/public/PWS/DownloadBulkData.aspx) does not expose actual individual submission times in its HTML. This explains the access limitation without equating missing FDIC fields with universal unavailability.

The [FFIEC FAQ](https://cdr.ffiec.gov/public/HelpFiles/FAQ.htm) describes next-day availability for validated individual UBPR data and subsequent revisions. That general procedure is not a Regions-specific observed release date, nor does it establish the original Call Report publication time. No quarter-end-plus-lag dates are invented, and no as-filed revision history is claimed.

## Operating-cost and credit evidence

The verified 2025 annual flows are $4.166 billion noninterest expense (`NONIX`), $2.441 billion noninterest income (`NONII`), $470 million provision for credit losses (`ELNATR`) and $513 million net loan chargeoffs (`NTLNLS`). Noninterest income includes more than fees. Provision expense and chargeoffs are different measures; applying both as the same credit loss would double count. CECL and other reporting changes limit direct comparison of provision histories.

Annual evidence includes explicitly calculated, day-weighted quarter-end asset and gross-loan average proxies. `AVASSET` is retained for inspection only: the pinned dictionary does not establish whether its period is quarterly or year-to-date. The day-weighted combination of AVASSET is **not used as a denominator**. The primary engine separately scales annual operating expense by opening assets and annual chargeoffs by opening net loans; those are disclosed modeling scale proxies, not regulatory ratios.

December 2025's deposit-cost proxy is **1.81994%**. Using it as a model opening cost remains an approximation to aggregate expense, not an observed contractual deposit rate.

## Reproduction and checks

```powershell
python scripts/fetch_history.py --offline
python scripts/fetch_history.py --verify
python -m unittest tests.test_calibration -v
```

`--refresh` alone makes network requests. The source bundle pins eight exact source payloads with URL, UTC retrieval timestamp, SHA-256 and relative path. Offline replay verifies all hashes before rebuilding normalized data and deterministic calibration. These hashes detect accidental changes; they are not a digital signature or independent guarantee of source authenticity.

Use `load_verified_history(root=...)` or `load_verified_calibration(root=...)` from `scripts.fetch_history` to validate a copied checkout. Both use the requested root, fail on changed raw bytes, and compare all normalized outputs. `bank_alm.calibration.calibrate(history)` exposes the deterministic calculation independently.

Thirteen tests cover analytical constrained fits, rank deficiency, actual-day annualization, within-year expense derivation, deposit scope, missing-rate rejection, chronological training separation, explicit failed holdout evidence and copied-root raw/output tampering.
