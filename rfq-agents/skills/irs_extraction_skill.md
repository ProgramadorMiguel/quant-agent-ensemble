# Vanilla IRS Extraction Skill

## The product

A vanilla fixed-for-floating interest rate swap: two counterparties exchange
interest flows on the same notional, in the same currency, over the same period.
One stream pays a fixed rate; the other pays a floating rate linked to a
published reference index. The notional itself is never exchanged.

Each stream is a **leg**, and each leg carries its own conventions: its own day
count basis and its own payment frequency. The two legs are not symmetric and
must never be filled in from one another.

Valuation uses **two separate curves**: a discount curve for present-valuing the
flows, and a forecast curve for projecting the floating fixings. They are
different pieces of information and neither can be derived from the other.

## What to extract

### Common terms

| Field | Meaning |
|---|---|
| `notional` | Positive amount, digits only, no separators or currency symbol |
| `currency` | ISO 4217 uppercase code |
| `is_fixed_rate_receiver` | `false` when the client **pays** fixed, `true` when the client **receives** fixed |
| `valuation_date` | Date the swap is valued at, ISO `YYYY-MM-DD` |
| `effective_date` | Start date, ISO `YYYY-MM-DD` |
| `maturity_date` | End date, ISO `YYYY-MM-DD` |
| `discount_curve` | Curve identifier, exactly as stated |
| `forecast_curve` | Curve identifier, exactly as stated |

### Fixed leg (`fixed_leg`)

| Field | Meaning |
|---|---|
| `rate` | Decimal rate: `2.75%` becomes `0.0275` |
| `day_count` | One of `ACT/360`, `ACT/365`, `ACT/365.25`, `30/360` |
| `payment_frequency` | One of `1M`, `2M`, `3M`, `4M`, `6M`, `1Y` |

### Floating leg (`floating_leg`)

| Field | Meaning |
|---|---|
| `index` | Uppercase index name: `EURIBOR`, `SOFR`, `SONIA`, `ESTR` |
| `tenor` | Fixing tenor of the index: `3M`, `6M` |
| `spread` | Decimal spread over the index. `25bp` becomes `0.0025`. Omit when not mentioned |
| `day_count` | Same list as the fixed leg |
| `payment_frequency` | Same list as the fixed leg |

## What NOT to extract

**Payment schedules.** Do not produce lists of payment dates. They are derived
deterministically from the start date, the maturity date and the payment
frequency by code that runs after you. A request never states them.

## Never infer

Extract only what the request states or unambiguously implies. Omit anything
else. Omitting a term is correct behaviour; the system will ask for it. Filling
it in with the usual market convention produces a request that prices cleanly
and is wrong, which is far worse than an explicit rejection.

| Never infer | Even though |
|---|---|
| `day_count` of either leg | ACT/360 is the usual EUR floating convention |
| `payment_frequency` of either leg | Annual fixed against semiannual floating is typical |
| `discount_curve` | ESTR discounting is standard for EUR |
| `forecast_curve` | It is not implied by the index name |
| `tenor` | It is not implied by the payment frequency |
| `index` | It is not implied by the currency |
| `valuation_date` | It is not today's date unless the request says so |
| `maturity_date` | Never compute it from a tenor such as "5 years" |
| `effective_date` | "Spot start" is not a date |
| `is_fixed_rate_receiver` | Absent a stated direction, omit it |

One exception, and only this one: an unstated `spread` on a vanilla swap is zero.
Omit the field and the system will treat it as zero.

## Reading trading desk shorthand

| Written | Means |
|---|---|
| `10mm`, `10MM` | notional `10000000` |
| `250k` | notional `250000` |
| `EUR 10,000,000` | notional `10000000`, currency `EUR` |
| `2,75%` | `0.0275` (comma is a decimal separator) |
| `275bp`, `275 bps` | `0.0275` |
| `+25bp` over an index | `spread` of `0.0025` |
| `vs 6s`, `vs 6m` | floating `tenor` of `6M` |
| `we pay fixed`, `pay fixed`, `payer` | `is_fixed_rate_receiver: false` |
| `we receive fixed`, `rec fixed`, `receiver` | `is_fixed_rate_receiver: true` |
| `ann`, `annual` | `payment_frequency` of `1Y` |
| `s/a`, `semi` | `payment_frequency` of `6M` |
| `qtr`, `quarterly` | `payment_frequency` of `3M` |
| `30/360`, `30E/360` | `day_count` of `30/360` |
| `A/360`, `act/360` | `day_count` of `ACT/360` |

A tenor such as `5y` describes the length of the swap. It is **not** a maturity
date: do not convert it into one.

## Worked examples

### Complete request

> Value as of 2026-09-01 a vanilla EUR interest rate swap, notional
> EUR 10,000,000, effective 2026-09-01, maturing 2031-09-01. We pay fixed at
> 2.75% annually on a 30/360 basis and receive 6M EURIBOR semiannually on
> ACT/360. Discount on EUR-ESTR, forecast on EUR-EURIBOR-6M.

```
notional: 10000000
currency: "EUR"
is_fixed_rate_receiver: false
valuation_date: "2026-09-01"
effective_date: "2026-09-01"
maturity_date: "2031-09-01"
discount_curve: "EUR-ESTR"
forecast_curve: "EUR-EURIBOR-6M"
fixed_leg {
  rate: 0.0275
  day_count: "30/360"
  payment_frequency: "1Y"
}
floating_leg {
  index: "EURIBOR"
  tenor: "6M"
  day_count: "ACT/360"
  payment_frequency: "6M"
}
```

### Incomplete request

> Value as of 2026-09-01 a EUR swap, notional 5,000,000, from 2026-09-01 to
> 2031-09-01. We receive fixed at 2.60% annually. Floating is 3M EURIBOR
> quarterly.

```
notional: 5000000
currency: "EUR"
is_fixed_rate_receiver: true
valuation_date: "2026-09-01"
effective_date: "2026-09-01"
maturity_date: "2031-09-01"
fixed_leg {
  rate: 0.026
  payment_frequency: "1Y"
}
floating_leg {
  index: "EURIBOR"
  tenor: "3M"
  payment_frequency: "3M"
}
```

Both day count bases and both curves are missing from the request, so they are
absent from the output. Do not supply them.

### Desk shorthand

> val 2026-09-01, 10mm USD 5y from 2026-09-01 to 2031-09-01, pay 3,25% ann
> 30/360 vs SOFR 3m qtr A/360 +15bp, disc USD-SOFR, fwd USD-SOFR-3M

```
notional: 10000000
currency: "USD"
is_fixed_rate_receiver: false
valuation_date: "2026-09-01"
effective_date: "2026-09-01"
maturity_date: "2031-09-01"
discount_curve: "USD-SOFR"
forecast_curve: "USD-SOFR-3M"
fixed_leg {
  rate: 0.0325
  day_count: "30/360"
  payment_frequency: "1Y"
}
floating_leg {
  index: "SOFR"
  tenor: "3M"
  spread: 0.0015
  day_count: "ACT/360"
  payment_frequency: "3M"
}
```

## Output

Exactly one `pricing.InterestRateSwap` protobuf text-format message. No Markdown
fences, no commentary. Omit any field the request does not state.
