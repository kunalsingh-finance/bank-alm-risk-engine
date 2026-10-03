# Sourced asset coverage and remaining assumptions

The extended case replaces aggregate security and loan tenors with official Regions Bank reporting bands at **December 31, 2025**, FDIC certificate **12368**. These are the insured bank and its consolidated subsidiaries, not Regions Financial Corporation. Reported bands constrain exposure amounts and horizon ranges. They do not identify actual securities, loan contracts, coupons, fixed/floating shares or individual pledged assets.

The source amounts come from the [FDIC Financials API](https://api.fdic.gov/banks/docs) and its [field definitions](https://api.fdic.gov/banks/docs/risview_properties.yaml). The [December 2025 FFIEC 031/041 instructions](https://www.ffiec.gov/sites/default/files/data/reporting-forms/FFIEC031_FFIEC041_202512_i.pdf), RC-B Memorandum 2 and RC-C Part I Memorandum 2, define the maturity/repricing scope. Raw FDIC response and definition bytes, full retrieval URLs, SHA-256 hashes and retrieval timestamps are under `data/raw/maturity/`; `maturity_profile.json` is replayed from those bytes. The instruction PDF was readable through web research but direct byte retrieval returned HTTP 403. The manifest records that limitation; there is no claimed PDF hash. Numerical replay depends on saved FDIC bytes only.

## Exact reporting bridges

All values below are USD billions; source API amounts in USD thousands are multiplied by 1,000.

| Bridge | Amount |
|---|---:|
| Debt securities in the reported bands | 33.147 |
| Equity securities outside the debt schedule | 0.747 |
| Nonaccrual debt securities outside the schedule | 0.000 |
| Total securities book, matching the bank snapshot | **33.894** |
| Accruing gross loans in reported bands | 95.425 |
| Nonaccrual gross loans outside the schedule | 0.698 |
| Gross loans | **96.123** |
| Allowance deducted from gross loans | (1.556) |
| Net loans, matching the bank snapshot | **94.567** |
| Reported pledged securities | 20.926 |
| Aggregate securities less reported pledges | 12.968 |

The securities definition combines held-to-maturity amortized cost with available-for-sale fair value. The loan schedule includes loans held for investment and sale. Neither schedule includes its nonaccrual exclusions. `LNATRES` is the gross-to-net allowance bridge for this observation; unearned income is zero. All three source reconciliations are exact. A future observation with a nonzero unmatched residual fails the current builder and requires a reviewed scope bridge.

The net loan amount assigned to each segment equals its reported gross band amount times **94.567 / 96.123**. The same scale applies to the separately identified nonaccrual balance. This proportionately allocates the allowance for modeling; it is not a disclosed segment allowance. The extended credit-loss overlay represents additional hypothetical future loss on beginning net book, including nonaccrual net book. It does not subtract the opening allowance again.

## Maturity is distinct from repricing

`SCNM*`, `SCPT*`, `LNRS*` and `LNOT*` each report six bands. For fixed-rate instruments they describe remaining maturity; for floating instruments they describe the next repricing interval. The model splits each source band into assumed fixed and floating subsegments. A floating reset changes its coupon; it never causes a principal redemption solely because the reset horizon arrives.

| Reported maturity or next-reset band | Assumed representative horizon |
|---|---:|
| Three months or less | 2 months |
| Over three months through one year | 8 months |
| Over one through three years | 24 months |
| Over three through five years | 48 months |
| Over five through fifteen years | 120 months |
| Over fifteen years | 240 months |

Assumed fixed shares are 90% for other debt securities (`SCNM`), 90% for first-lien residential mortgage pass-throughs (`SCPT`), 80% for closed-end first-lien residential loans (`LNRS`), and 20% for other loans and leases (`LNOT`). Floating subsegments mature at the later of 60 months and 12 months after their representative next reset. These allocations, especially the fixed share in the large near-reset other-loan band, can materially change cash generation and EVE. They remain visible configuration choices and are not estimates of the bank's actual contract mix.

Other MBS (`SCO3YLES`, `SCOOV3Y`) report expected weighted average life, not final contractual maturity. The model uses fixed-rate bullet proxies at 24 and 60 months respectively. This preserves a transparent representative timing assumption rather than claiming to recover an actual MBS amortization schedule.

The separately reported `SC1LES` contractual security maturity of **$603 million** is retained as evidence. It is not added to the mixed bands or used as a second amount: doing so would double count. The model's first-year principal includes assumed amortization and prepayment as well as maturity, so it need not equal that contractual-maturity disclosure.

## Cash flows, repricing and valuation

Fixed subsegments retain the configured coupon. Floating subsegments retain their initial coupon through the assumed reset month, then shift by the scenario change in the short zero-rate proxy, floored at zero. Coupons are assumed from the original research configuration; the source reports no segment coupon.

Loans and first-lien mortgage pass-throughs amortize equal original principal installments over their separate assumed contractual horizons, with scenario-sensitive CPR on the remaining balance. The same disclosed CPR proxy is used for both categories; it is not an independently calibrated MBS prepayment model. Fixed other debt and other-MBS proxies pay bullet principal. Each segment collects its final balance at its maturity, and subsequent interest and principal are zero. Securities maturing within 12 months therefore release actual modeled principal into the cash ledger.

Each month, interest is earned on beginning book. The credit-loss overlay reduces loan book and equity next, followed by scheduled principal and prepayment. Principal becomes cash. No new loan or security originations replace runoff. A sale proportionately reduces the sold segment's remaining scheduled installments. Prepayment and credit loss can shorten the remaining runoff; cash-flow reconstruction does not create negative principal.

The EVE reconstruction and prospective ledger share these security and loan schedules. EVE discounts the modeled flows using the supplied zero curve plus the stated loan discount spread. Equity securities and nonaccrual residuals stay at net book, with zero modeled coupon or principal recovery. Those residual values are deliberate approximations, not fair-value measurements. EVE is measured at the opening shock; later reactive borrowing, security sales and the earnings-only operating/credit-cost overlays are outside that opening valuation. Deposits retain the separately documented EVE behavioral-runoff versus ledger stable-balance convention.

## Pledged inventory and security sales

The source reports aggregate securities pledges of **$20.926 billion**. Their specific allocation is unavailable. The model applies the same opening pledged fraction, 20.926 / 33.894, to each security segment and excludes equity securities from forced sales. This leaves **$12.682194371 billion** of modeled opening unpledged debt eligible for sale, below both the $12.968 billion aggregate unpledged figure and the original 80%-of-book sale cap. New borrowing availability remains separately assumed; the model does not claim a source-verified collateral borrowing base.

A sale draws proportionately from remaining unpledged eligible debt. Each segment is priced at its shocked remaining-flow PV divided by its unshocked remaining-flow PV, times book sold. Its base and stressed PV use the same current inventory state, with their respective disclosed CPR assumptions. The reported aggregate sale ratio is proceeds divided by book sold, allowing the accounting sale gain or loss to be independently reconciled. No security-level bid/ask or execution depth is inferred.

Sales reduce only unpledged inventory. Principal runoff reduces pledged and unpledged remaining book proportionately. Consequently selling part of a segment cannot release or resell its pledged balance. The opening cumulative cap and the changing per-segment availability both apply, in addition to all existing cash, borrowing, EVE and collateral constraints.

The ledger makes an additional collateral-release assumption: all collected security principal becomes free cash, including principal from the modeled pledged portion. This assumes maturity proceeds can be released without collateral substitution or a continuing restriction on the proceeds. Aggregate reporting does not establish those legal terms. The source-based sale restriction therefore improves inventory coverage but does not establish unrestricted liquidity from every pledged cash flow.

The separate `retain_cash_collateral` challenge removes that release assumption. Each month's collected security principal is split using the segment's beginning pledged share. The pledged portion moves into a separate `pledged_cash_usd` asset, earns no interest under this conservative challenge, cannot fund withdrawals, operating payments or swap margin, and remains restricted through month 12. The transfer changes neither equity nor total assets. Lower free cash can subsequently reduce interest income or require funding and sales. `pledged_principal_cash_flow_usd` records the transfer; no terminal release is invented. Opening EVE remains a contractual cash-flow valuation and does not add an illiquidity haircut for this retention rule. The default `release_on_payment` preserves the primary case.

## Reproducibility and interfaces

`python scripts/fetch_maturity_data.py` rebuilds the profile offline. `--fetch` explicitly retrieves later source vintages. `load_verified_profile(root)` checks each saved raw hash and byte length, rebuilds the profile, and rejects disagreement with saved processed JSON without writing any file. A supplied project root is honored, including copied validation fixtures.

`build_asset_segments(profile, assumptions, overrides=None)` is pure: it returns the optional `assumptions.asset_segments` object, including source records, reported totals, segment assumptions and `permitted_security_sale_book_usd`. `run_analysis` selects the segmented ledger only when this object is enabled. The original aggregate configuration and its exact numerical regression remain available separately.

Each opening/month-end ledger saves `asset_segment_flows`, `asset_segment_sales` and `asset_segment_inventory`. Flow rows identify beginning book, interest, credit loss, principal, remaining book before sales, contractual horizon and reset horizon. Sale rows identify book sold, proceeds and price ratio. Inventory rows retain original/ending book, remaining pledged book, sale eligibility and cumulative principal, credit loss and sold book. Independent audit can therefore verify, by segment:

**Original book = ending book + principal collected + new credit loss + book sold.**

Tests check source replay and tamper rejection, exact reporting scope, a reset without principal repayment, a short maturity paid once, encumbrance conservation, sale-price invariance to position scale after amortization, and full named-scenario accounting with costs and a hedge. Technical integrity checks do not imply a policy is economically feasible or establish a real bank's risk outcome.
