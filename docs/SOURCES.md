# Public data and bank identity

The opening balance sheet belongs to **Regions Bank**, FDIC certificate **12368**, Federal Reserve RSSD **233031**, as of **December 31, 2025**. It covers the insured bank and its consolidated subsidiaries. The parent is **Regions Financial Corp**; holding-company financial statements and sensitivities must not be substituted for bank-level values.

The FDIC identity response names Regions Bank in Birmingham, Alabama, and identifies its parent separately. Identity data was retrieved on October 2, 2026, so current status is not a historical status observation. Financial data was also retrieved on October 2, 2026 from FDIC index `risview_20260819185831`, created August 19, 2026. This is a pinned, potentially revised vintage, not an as-filed snapshot available at the 2025 measurement date.

## Reproduce and verify

From the repository root:

```console
python scripts/fetch_bank_data.py --offline
python scripts/fetch_bank_data.py --verify
```

The first command verifies raw hashes and rebuilds `data/processed/bank_snapshot.json`. The second verifies the existing normalized file without writing. Both work offline with the standard library. A release builder can call `validate_snapshot(snapshot, root=project_root)` from `scripts.fetch_bank_data`; this compares every normalized field against a fresh reconstruction from hash-verified bytes.

To capture a fresh FDIC response explicitly:

```console
python scripts/fetch_bank_data.py --refresh
```

Refresh makes four small requests: bank identity, one bank-quarter, and two official field-definition files. New raw content is saved under a hash-suffixed filename. `data/raw/fdic_source_bundle.json` identifies the active source set. Every source record contains the exact query URL, retrieval time in UTC, HTTP status, content type, byte count and full SHA-256 hash. Historical raw bytes remain available when the response changes.

Official entry points:

- [FDIC BankFind API documentation](https://api.fdic.gov/banks/docs)
- [FDIC financial field definitions](https://api.fdic.gov/banks/docs/risview_properties.yaml)
- [FDIC institution field definitions](https://api.fdic.gov/banks/docs/institution_properties.yaml)
- [Regions Bank in BankFind](https://banks.data.fdic.gov/bankfind-suite/bankfind/details/12368)
- [FFIEC explanation of Call Report dollar units and income periods](https://cdr.ffiec.gov/public/HelpFiles/FAQ.htm)

The source response is stored exactly as received, including its FDIC index metadata. The normalized snapshot also preserves exact official YAML blocks for selected financial fields. Fields without detailed descriptions retain the official short title; no missing description is presented as an FDIC definition.

## Opening balances

FDIC dollar fields are in thousands of USD. The converter multiplies by 1,000; model inputs use whole USD. All balances below are USD billions.

| Model bucket | Amount | FDIC field or explicit derivation |
|---|---:|---|
| Cash and due from depository institutions | 11.845 | `CHBAL` |
| Securities | 33.894 | `SC` |
| Net loans and leases | 94.567 | `LNLSNET` |
| Other assets, model residual | 17.106 | `ASSET - CHBAL - SC - LNLSNET` |
| **Total assets** | **157.412** | `ASSET` |
| Noninterest deposits | 39.635 | `DEPNI` |
| Interest-bearing deposits | 92.352 | `DEPI` |
| Wholesale funding, defined model group | 3.915 | `FREPP + OTHBOR + SUBND` |
| Other liabilities, model residual | 3.379 | `LIAB - DEP - FREPP - OTHBOR - SUBND` |
| Total consolidated equity | 18.131 | `EQTOT` |
| **Total liabilities and equity** | **157.412** | `LIAB + EQTOT` |

Reported bank equity `EQ` is $18.071 billion. Reported noncontrolling equity in consolidated subsidiaries `EQCONSUB` is $0.060 billion. Their sum equals reported `EQTOT` of $18.131 billion. The model uses this reported consolidated total; equity is not calculated as an unexplained balancing residual.

Other assets is a model grouping, broader than the source's `OA` field. Other liabilities is also a model grouping. These residuals are defined against reported totals and separately disclosed; they do not imply detailed product classification.

Federal funds and repurchase agreements **purchased** (`FREPP`) are borrowed funding. Federal funds and repurchase agreements **sold** (`FREPO`) are assets. Both are zero for this bank-quarter. Other borrowing `OTHBOR` is $3.418 billion, including $1.750 billion of FHLB borrowing (`OTHBFHLB`); the latter is not added twice. Subordinated notes (`SUBND`) are $0.497 billion. Brokered deposits, if present, remain within the reported deposit buckets and have not been reclassified into wholesale funding.

Gross loans `LNLSGR` are $96.123 billion; the engine starts from the $94.567 billion net carrying amount. Interest-bearing cash `CHBALI` is $7.607 billion within total cash of $11.845 billion. These supplemental values are preserved in `totals_usd` for later asset segmentation.

## Earnings period

| Reported measure | USD billions | Period |
|---|---:|---|
| Interest income `INTINC` | 7.057 | January 1–December 31, 2025 |
| Interest expense `EINTEXP` | 1.998 | January 1–December 31, 2025 |
| Net interest income `NIM` | 5.059 | January 1–December 31, 2025 |
| Net interest income `NIMQ` | 1.293 | October 1–December 31, 2025 |

Income fields without the quarterly suffix are year-to-date; at December 31 they cover the full calendar year. Quarterly NII is retained separately and is not multiplied by four. The historical $5.059 billion annual NII is a comparison point, not a fitted target for modeled coupons or deposit costs.

## Reconciliation controls and limits

The converter requires every requested financial field, finite monetary values, matching certificate/date/name, nonnegative opening model buckets, and seven exact dollar identities. These include assets against liabilities plus reported total equity, total equity against bank equity plus noncontrolling interests, both deposit splits, and interest income minus interest expense against NII. Missing fields fail rather than becoming zero.

The opening snapshot alone does not identify contract-level maturities, repricing dates, deposit beta, deposit decay, prepayments or available collateral. The additional sources below provide historical observations, reported maturity/repricing bands and aggregate pledged securities. Contract-level cash flows, pledge allocation and collateral-release terms remain assumptions. The dataset supports a transparent research model, not a reconstruction of Regions' internal ALM system or a regulatory-compliance claim. Any later comparison with Regions Financial Corporation's published ALM sensitivities must document the legal-entity difference.

## Historical and asset-coverage extensions

The primary case also verifies eight pinned historical/definition/availability payloads through `scripts/fetch_history.py`, and two FDIC maturity/definition payloads through `scripts/fetch_maturity_data.py`. Replayed inputs must match the saved processed data at the requested project root. The build checks that their bank/date, ending balances and annual cost flows agree with the opening snapshot.

[Calibration](CALIBRATION.md) documents 44 quarterly observations, YTD flow conversion, the domestic interest-bearing deposit denominator, policy-rate aggregation, training/holdout separation, weak holdout results and exact publication dates remaining unobserved. [Cash-flow coverage](CASH_FLOW_COVERAGE.md) documents the 26 reported bands, gross-to-net bridge, pledged securities and assumptions needed to construct 52 modeled segments. The FFIEC maturity instructions were verified through web research; the direct PDF download returned an error, recorded in source limitations. No downloaded-file hash is claimed for that unavailable payload.
