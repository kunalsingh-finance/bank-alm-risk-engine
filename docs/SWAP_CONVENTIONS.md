# Dated swap pricing conventions

`bank_alm/swaps.py` supplies a payer-fixed, receiver-floating interest-rate swap research proxy. Positive cash flows and values belong to the bank. Notional is nonnegative, with no principal exchanged. The default contract is five years and is liquidated after the twelfth monthly coupon.

This is a **Treasury single-curve model**, using the project's fitted Treasury zero curve for both projection and discounting. It is not an observed dealer swap quote or a production SOFR model. Actual market conventions differ. The [CME pricing article](https://www.cmegroup.com/articles/2025/price-and-hedging-usd-sofr-interest-swaps-with-sofr-futures.html), reviewed October 2, 2026, explains the fixed/floating leg exchange, par pricing by equal discounted legs, and the importance of payment dates and day-count conventions. Our monthly ACT/365F terms are explicit research choices rather than claimed USD market conventions.

## Calendar and trade timing

The trade is entered on the bank snapshot date immediately before the rate shock. Each period ends one calendar month later. If inception is a month-end, every payment is month-end. Otherwise payments retain the original day where available and clip only that month's short date. For example, January 30, 2024 produces February 29 and March 30. Dates are unadjusted for weekends and holidays; there is no payment lag or stub period.

Both legs use actual elapsed calendar days divided by 365, including leap-year days. A year containing February 29 can therefore accrue 366/365. This differs from the earlier bank-book ledger's equal 1/12-year accrual periods; swap and collateral calculations use their own recorded actual day fractions.

At inception, the fixed coupon is calibrated on the base curve and the first floating fixing is locked on that same curve. The shock happens after this first fixing. The first floating payment remains identical across scenarios; later floating payments follow the shocked time-zero forward curve. This is a term-fixing proxy, not an overnight-in-arrears SOFR contract.

## Projection and value

Let `D_s(t)` be the scenario discount factor at ACT/365F time `t`, `alpha_i` the accrual fraction, `N` notional, and `K` the fixed coupon. We use continuous zero yields:

```text
D_s(t) = exp(-(z_base(t) + shock_s(t)) * t)
K      = (1 - D_base(T)) / sum_i(alpha_i * D_base(t_i))
L_1    = (1 / D_base(t_1) - 1) / alpha_1
L_i    = (D_s(t_(i-1)) / D_s(t_i) - 1) / alpha_i, for i > 1
fixed_payment_i   = N * K   * alpha_i
floating_receipt_i = N * L_i * alpha_i
net_coupon_i     = floating_receipt_i - fixed_payment_i
```

Gross leg directions describe positive-rate cash flows; a negative coupon reverses the corresponding payment. Negative finite rates are supported in this pricing module. Every source curve, scenario, notional and schedule argument must pass numerical validation.

The model keeps the original scenario projection as time passes. The conditional discount factor from time `u` to `t` is `D_s(t) / D_s(u)`. It does not apply the original yield at a shortened tenor and does not re-enter a new par swap each month.

```text
V(u), after the coupon at u = sum_(t_i > u)(net_coupon_i * D_s(t_i) / D_s(u))
V(t_(i-1)) * D_s(t_(i-1)) / D_s(t_i) = net_coupon_i + V(t_i)
```

The floating coupons telescope to `N * (1 - D_s(T))` only when every coupon uses scenario forwards. With the locked first fixing, add the correction:

```text
N * alpha_1 * (L_base,1 - L_s,1) * D_s(t_1)
```

That identity does not create a principal payment. The module explicitly reports zero principal exchange for every period.

## Horizon closeout and collateral interface

At the final modeled month, the regular coupon is paid first. The remaining swap value is then exchanged as a separate closeout payment. The final derivative balance becomes zero. Closeout is not additional profit on top of an unchanged derivative asset: the calling ledger must remove that asset or liability.

`swap_path(curve, scenario, valuation_date, notional, tenor_months=60, horizon_months=12)` returns:

- `terms`: dates, fixed coupon, locked first fixing, notional and conventions.
- `inception_value_usd`: base-curve par value before the shock, numerically zero.
- `opening_value_usd`: signed value after the scenario shock.
- `monthly`: dated gross legs, net coupon, ex-coupon `swap_value_usd`, `closeout_cashflow_usd`, and `ending_swap_value_usd` after closeout.
- `terminal_closeout_usd`: the final month’s separate remaining-value payment.

Each monthly row includes `collateral_rate = (D_s(t_(i-1)) / D_s(t_i) - 1) / alpha_i`, an annualized interval-implied remuneration proxy. The first row's rate applies from inception to the first payment. The pricing module does not calculate margin requirements, collateral movements, funding draws or settlement backlogs; those belong to the bank ledger.

The intended ledger convention is a **bilateral collateralized-to-market proxy**: collateral and the derivative remain separate positions until cash settlement and closeout. It must not be described as settled-to-market clearing, where qualifying variation payments settle exposure. The [Federal Reserve's explanation of the distinction](https://www.federalreserve.gov/frrs/guidance/regulatory-capital-treatment-of-certain-centrally-cleared-derivative-contracts-under-regulatory-capital-rules.htm), reviewed October 2, 2026, describes how the legal treatment depends on governing agreements. The model does not make a legal or regulatory-capital determination.

## Independent numerical checks

`tests/test_swaps.py` checks par pricing against a flat-curve closed form, positive payer-fixed response to a rate increase, the locked first coupon, the corrected floating-leg telescoping identity, ex-coupon conditional value, discounted coupons plus closeout equaling opening value, zero remaining value at contractual maturity, zero notional, invalid arguments, negative-rate consistency, and calendar/leap-year cases. Tolerances are much smaller than one dollar at a $1 billion test notional.

The public helpers `schedule`, `discount_factor`, `par_swap_rate`, `projected_cashflows` and `value_remaining` expose intermediate quantities for an independent verifier. These are arithmetic and convention checks. They do not validate market calibration, counterparty credit, collateral terms, liquidity access or execution prices.
