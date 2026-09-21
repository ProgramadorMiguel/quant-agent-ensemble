# Vanilla IRS Extraction Skill

## The product

A vanilla fixed-for-floating interest rate swap: two counterparties exchange
interest flows on the same notional, in the same currency, over the same period.
One stream pays a fixed rate; the other pays a floating rate. The notional itself
is never exchanged.

Each stream is a **leg**, and each leg carries its own day count basis, its own
payment frequency and its own payment schedule. The two legs are not symmetric
and must never be filled in from one another.

Valuation uses **two curves**: a discount curve, which present-values the flows of
both legs, and a forecast curve, which projects the floating fixings. The discount
curve sits at the top level; the forecast curve sits **inside the floating leg**,
because it concerns that leg only.

### Two kinds of floating leg

`floating_leg.rate_type` is not decoration. It separates two different product
structures, and getting it wrong describes an instrument that does not trade.

| `rate_type` | Meaning | `tenor` |
|---|---|---|
| `IBOR` | A term index fixed once per period: EURIBOR | **Required** |
| `OVERNIGHT_COMPOUNDED` | An overnight rate compounded over the period: SOFR, ESTR, SONIA | **Must be absent** |

A compounded overnight rate has no fixing tenor. Writing `tenor: "3M"` next to
`rate_type: OVERNIGHT_COMPOUNDED` is a contradiction: there is no three-month
fixing of an overnight rate.

Since USD LIBOR ceased in June 2023, **a vanilla USD swap is an overnight
compounded swap against SOFR.** A fixed-versus-`SOFR 3M` swap does not exist.

## Scope

**Currencies: EUR and USD only.** Any other currency is out of scope.

**Maturities of one year or more.** Below a year the instrument follows money
market conventions — a single period, no intermediate coupons — and is out of
scope.

## Mandatory terms

These seven cannot be derived from anything. If the request does not state a
term, **omit it**: the system will report it and ask. Never invent one.

| Field | Meaning |
|---|---|
| `notional` | Positive amount, digits only, no separators or currency symbol |
| `currency` | `EUR` or `USD` |
| `is_fixed_rate_receiver` | `false` when the client **pays** fixed, `true` when the client **receives** fixed |
| `valuation_date` | Date the swap is valued at, ISO `YYYY-MM-DD` |
| `effective_date` | Start date, ISO `YYYY-MM-DD` |
| `maturity_date` | End date, ISO `YYYY-MM-DD` |
| `fixed_leg.rate` | Decimal fraction: `2.75%` becomes `0.0275`. The same rate applies to every period |

## Derived terms

Everything else follows from the currency and the maturity: derive it from the
tables below.

**The convention is mandatory, not a default.** The system supports
standard-convention swaps only. If the request states a term that contradicts the
convention for its currency and maturity — a five-year EUR swap against EURIBOR
3M, say — emit the conventional value anyway. Such a trade exists in the market,
but it is out of scope here, and validation will reject anything else.

When the request restates a term that agrees with the convention, nothing changes:
emit the same value.

### EUR, maturity of exactly one year

| Field | Value |
|---|---|
| `discount_curve` | `EUR-ESTR` |
| `fixed_leg.day_count` | `30U/360` |
| `fixed_leg.payment_frequency` | `1Y` |
| `floating_leg.rate_type` | `IBOR` |
| `floating_leg.index` | `EURIBOR` |
| `floating_leg.tenor` | `3M` |
| `floating_leg.day_count` | `ACT/360` |
| `floating_leg.payment_frequency` | `3M` |
| `floating_leg.forecast_curve` | `EUR-EURIBOR-3M` |

### EUR, maturity above one year

| Field | Value |
|---|---|
| `discount_curve` | `EUR-ESTR` |
| `fixed_leg.day_count` | `30U/360` |
| `fixed_leg.payment_frequency` | `1Y` |
| `floating_leg.rate_type` | `IBOR` |
| `floating_leg.index` | `EURIBOR` |
| `floating_leg.tenor` | `6M` |
| `floating_leg.day_count` | `ACT/360` |
| `floating_leg.payment_frequency` | `6M` |
| `floating_leg.forecast_curve` | `EUR-EURIBOR-6M` |

### USD, any maturity of one year or more

| Field | Value |
|---|---|
| `discount_curve` | `USD-SOFR` |
| `fixed_leg.day_count` | `ACT/360` |
| `fixed_leg.payment_frequency` | `1Y` |
| `floating_leg.rate_type` | `OVERNIGHT_COMPOUNDED` |
| `floating_leg.index` | `SOFR` |
| `floating_leg.tenor` | *omit the field* |
| `floating_leg.day_count` | `ACT/360` |
| `floating_leg.payment_frequency` | `1Y` |
| `floating_leg.forecast_curve` | `USD-SOFR` |

In EUR the floating payment frequency equals the index tenor. **In USD it does
not**, because there is no tenor.

### The spread

An unstated `spread` is zero on a vanilla swap. Omit the field; the system
treats it as zero. A stated spread is extracted: `+25bp` becomes `0.0025`.

## Calculating the payment schedules

Both legs carry an explicit `payment_dates` vector, and **you produce it**.

A payment date is the **end** of a period, never its start. So the schedule never
contains `effective_date`, and always ends exactly on `maturity_date`.

Build it by stepping forward from `effective_date` in increments of that leg's
`payment_frequency` until you reach `maturity_date`:

- **Fixed leg, `1Y`, 2026-09-01 to 2031-09-01** → 5 dates: 2027-09-01,
  2028-09-01, 2029-09-01, 2030-09-01, 2031-09-01
- **Floating leg, `6M`, same period** → 10 dates: 2027-03-01, 2027-09-01,
  2028-03-01, 2028-09-01, 2029-03-01, 2029-09-01, 2030-03-01, 2030-09-01,
  2031-03-01, 2031-09-01

Do not adjust for weekends or holidays: no holiday calendar is modelled.

### Broken periods

When the maturity does not fall on a regular step, the **last period is shorter**.
That is a broken period and it is legitimate. Keep the regular steps and let the
final date be the maturity.

**Fixed leg, `1Y`, 2026-09-01 to 2030-03-01** → 2027-09-01, 2028-09-01,
2029-09-01, **2030-03-01**. The last period is six months instead of twelve.

Never extend the schedule past the maturity to keep the periods even, and never
drop the maturity date to keep them even either.

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
| `30/360`, `30U/360`, `30E/360` | `day_count` of `30U/360` |
| `A/360`, `act/360` | `day_count` of `ACT/360` |

A tenor such as `5y` describes the length of the swap. It is **not** a maturity
date: never convert it into one.

## Worked examples

### Minimal EUR request, everything derived

> Value as of 2026-09-01 a vanilla EUR interest rate swap with notional
> EUR 10,000,000, effective 2026-09-01 and maturing 2031-09-01. We pay fixed at
> 2.75%.

```
notional: 10000000
currency: "EUR"
is_fixed_rate_receiver: false
valuation_date: "2026-09-01"
effective_date: "2026-09-01"
maturity_date: "2031-09-01"
discount_curve: "EUR-ESTR"
fixed_leg {
  rate: 0.0275
  day_count: "30U/360"
  payment_frequency: "1Y"
  payment_dates: "2027-09-01"
  payment_dates: "2028-09-01"
  payment_dates: "2029-09-01"
  payment_dates: "2030-09-01"
  payment_dates: "2031-09-01"
}
floating_leg {
  rate_type: IBOR
  index: "EURIBOR"
  tenor: "6M"
  day_count: "ACT/360"
  payment_frequency: "6M"
  forecast_curve: "EUR-EURIBOR-6M"
  payment_dates: "2027-03-01"
  payment_dates: "2027-09-01"
  payment_dates: "2028-03-01"
  payment_dates: "2028-09-01"
  payment_dates: "2029-03-01"
  payment_dates: "2029-09-01"
  payment_dates: "2030-03-01"
  payment_dates: "2030-09-01"
  payment_dates: "2031-03-01"
  payment_dates: "2031-09-01"
}
```

### Minimal USD request: an overnight compounded swap

> Value as of 2026-09-01 a USD interest rate swap, notional USD 50,000,000,
> effective 2026-09-01, maturing 2029-09-01. The client receives fixed at 3.85%.

```
notional: 50000000
currency: "USD"
is_fixed_rate_receiver: true
valuation_date: "2026-09-01"
effective_date: "2026-09-01"
maturity_date: "2029-09-01"
discount_curve: "USD-SOFR"
fixed_leg {
  rate: 0.0385
  day_count: "ACT/360"
  payment_frequency: "1Y"
  payment_dates: "2027-09-01"
  payment_dates: "2028-09-01"
  payment_dates: "2029-09-01"
}
floating_leg {
  rate_type: OVERNIGHT_COMPOUNDED
  index: "SOFR"
  day_count: "ACT/360"
  payment_frequency: "1Y"
  forecast_curve: "USD-SOFR"
  payment_dates: "2027-09-01"
  payment_dates: "2028-09-01"
  payment_dates: "2029-09-01"
}
```

No `tenor`, and both legs annual.

### Incomplete request

> Value as of 2026-09-01 an EUR swap, notional EUR 5,000,000, from 2026-09-01 to
> 2031-09-01. We pay fixed.

The rate is missing and cannot be derived from anything. Extract what is there,
derive the conventions, and **leave `fixed_leg.rate` absent**. The system will
report that the rate has to be specified.

## Output

Exactly one `pricing.InterestRateSwap` protobuf text-format message. No Markdown
fences, no commentary. Enum values such as `IBOR` are bare identifiers, never
quoted strings.
