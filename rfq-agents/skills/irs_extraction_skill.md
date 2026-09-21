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

## What the request is for: `purpose`

A desk uses an RFQ for two different things, and **the fixed rate is what tells
them apart.**

| `purpose` | The client... | `fixed_leg.rate` |
|---|---|---|
| `PAR_RATE_QUOTE` | asks what rate you would quote | **absent** |
| `VALUATION` | supplies the rate they traded at and asks what the swap is worth | **present** |

`PAR_RATE_QUOTE` is the ordinary case. *"Cotízame"*, *"please provide fixed
rate"*, *"necesito precio"*, *"¿cómo cotiza"*, *"pasanos precio"* are all quote
requests: the pricing engine reads the curve and solves for the rate that makes
the net present value zero. **Never invent a rate to fill the gap** — omitting it
is the correct answer.

`VALUATION` applies when the request states a rate: *"valórame un IRS 5Y EUR 10M
al 2.85% fijo"*. Then extract that rate.

Set `purpose` on every message. The two must agree: a quote request never carries
a rate, and a valuation always does.

## Mandatory terms

Without these there is no swap, and nothing derives them. If the request does not
state one and it cannot be resolved from the reference date, **omit it**: the
system will report it and ask.

| Field | Meaning |
|---|---|
| `notional` | Positive amount, digits only, no separators or currency symbol |
| `currency` | `EUR` or `USD` |
| `is_fixed_rate_receiver` | `false` when the client **pays** fixed, `true` when the client **receives** fixed |
| `valuation_date` | Date the swap is valued at, ISO `YYYY-MM-DD` |
| `effective_date` | Start date, ISO `YYYY-MM-DD` |
| `maturity_date` | End date, ISO `YYYY-MM-DD` |

## Resolving dates

Every request arrives with a **reference date**, stated before the request itself.
It is today's date on the desk. Use it to resolve anything expressed relative to
now.

| Written | Resolve to |
|---|---|
| `spot`, `spot start`, `empezando spot`, `T+2` | reference date + 2 business days |
| nothing said about the start | same as spot: reference date + 2 business days |
| `next Monday`, `el próximo lunes` | the first Monday after the reference date |
| `24-Sep-2026`, `2026-09-24` | that date |

**`valuation_date` is the reference date** unless the request names another one. A
desk values a quote as of today.

### Tenor into maturity

A tenor states the length of the swap, and the maturity follows from it once the
effective date is known. **Derive it.**

- `5Y` or `a 5 años`, effective 2026-09-23 → maturity **2031-09-23**
- `10Y`, effective 2026-09-24 → maturity **2036-09-24**
- `3Y`, effective 2026-09-28 → maturity **2029-09-28**

This is arithmetic on information the request gives you, not invention.

### Forward starting swaps

`2Y1Y` means the swap starts in two years and runs for one: *two years forward,
one year long*. Read it against the reference date.

- Reference 2026-09-21, `2Y1Y` → effective **2028-09-23** (spot in two years),
  maturity **2029-09-23**
- `1Y5Y` → starts in one year, runs five

The same holds for `5Y forward 1Y` and `1Y into 5Y`.

## Currency from the index

The index names the currency, so a request that says `EURIBOR6M` without naming
EUR still states its currency.

| Index mentioned | `currency` |
|---|---|
| EURIBOR, ESTR | `EUR` |
| SOFR | `USD` |

This works in one direction only. If the request names a currency **and** an index
that belongs to another one — a EUR swap against SOFR — that is not a vanilla swap
in either currency: it is a two-currency product. Extract what the text says and
let validation reject it.

## Direction from intent

The direction is usually explicit: *"pagamos fijo"*, *"recibo fijo"*, *"pay
fixed"*, *"rec fixed"*, *"payer"*, *"receiver"*.

When the request only describes an intent, read the economics. **Hedging against
rising rates means paying fixed** — the client locks a cost and receives the
floating leg: `is_fixed_rate_receiver: false`. *"Cobertura de tipo fijo"*,
*"quiero fijar mi coste"*, *"protegerme de subidas"* all read the same way.

If the intent is genuinely ambiguous, omit the field rather than guess.

## Derived terms

Everything else follows from the currency and the maturity: derive it from the
tables below **when the request is silent**.

**A term the request states always wins over the convention.** A five-year EUR
swap against EURIBOR 3M paid quarterly is not standard, but it trades, and it is
supported: extract 3M because that is what was asked for. Only fill in from the
table what the request does not mention.

Two terms are the exception, because they follow from the currency rather than
being a matter of convention: `floating_leg.rate_type` and `floating_leg.index`.
EUR means an `IBOR` leg against EURIBOR; USD means an `OVERNIGHT_COMPOUNDED` leg
against SOFR. A EUR swap against SOFR would be a two-currency product, which is
out of scope.

When a stated frequency differs from the table, **the payment schedule follows the
stated frequency**: quarterly payments on a five-year swap mean twenty dates, not
ten.

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
| `we pay fixed`, `pay fixed`, `payer`, `pagamos fijo` | `is_fixed_rate_receiver: false` |
| `we receive fixed`, `rec fixed`, `receiver`, `recibo fijo` | `is_fixed_rate_receiver: true` |
| `Pay 5y 50m EURIBOR6M spot` | pays fixed, 5Y tenor, notional 50000000, EUR, spot start |
| `100m`, `50M`, `25M` | notional in millions |
| `2.50%`, `2,50 pct` | `0.025` |
| `ann`, `annual` | `payment_frequency` of `1Y` |
| `s/a`, `semi` | `payment_frequency` of `6M` |
| `qtr`, `quarterly` | `payment_frequency` of `3M` |
| `30/360`, `30U/360`, `30E/360` | `day_count` of `30U/360` |
| `A/360`, `act/360` | `day_count` of `ACT/360` |

A tenor such as `5y` describes the length of the swap. Combined with the effective
date it gives the maturity, as described under **Tenor into maturity** above.

## Worked examples

### A quote request in Spanish, with a tenor and a spot start

> Reference date: 2026-09-21 (Monday).
>
> Cotízame un IRS en EUR por 50M nocional a 5 años empezando spot, pagamos fijo
> y recibimos EURIBOR 6M.

Spot is the reference date plus two business days, 2026-09-23. The 5Y tenor puts
the maturity five years later, 2031-09-23. There is no rate because the client is
asking for it.

```
purpose: PAR_RATE_QUOTE
notional: 50000000
currency: "EUR"
is_fixed_rate_receiver: false
valuation_date: "2026-09-21"
effective_date: "2026-09-23"
maturity_date: "2031-09-23"
discount_curve: "EUR-ESTR"
fixed_leg {
  day_count: "30U/360"
  payment_frequency: "1Y"
  payment_dates: "2027-09-23"
  payment_dates: "2028-09-23"
  payment_dates: "2029-09-23"
  payment_dates: "2030-09-23"
  payment_dates: "2031-09-23"
}
floating_leg {
  rate_type: IBOR
  index: "EURIBOR"
  tenor: "6M"
  day_count: "ACT/360"
  payment_frequency: "6M"
  forecast_curve: "EUR-EURIBOR-6M"
  payment_dates: "2027-03-23"
  payment_dates: "2027-09-23"
  payment_dates: "2028-03-23"
  payment_dates: "2028-09-23"
  payment_dates: "2029-03-23"
  payment_dates: "2029-09-23"
  payment_dates: "2030-03-23"
  payment_dates: "2030-09-23"
  payment_dates: "2031-03-23"
  payment_dates: "2031-09-23"
}
```

No `fixed_leg.rate`. That is the point of the request.

### Desk shorthand with no currency stated

> Reference date: 2026-09-21 (Monday).
>
> Pay 5y 50m EURIBOR6M spot

`EURIBOR6M` names the currency: EUR. `Pay` is the fixed leg. Same output as
above.

### A valuation of an existing swap

> Valórame un IRS 5Y EUR 10M al 2.85% fijo, inicio 2026-09-23.

```
purpose: VALUATION
fixed_leg {
  rate: 0.0285
  ...
}
```

The rate is stated, so this is a valuation, and the rate is extracted.

### Minimal EUR valuation, everything else derived

> Value as of 2026-09-01 a vanilla EUR interest rate swap with notional
> EUR 10,000,000, effective 2026-09-01 and maturing 2031-09-01. We pay fixed at
> 2.75%.

```
purpose: VALUATION
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
purpose: VALUATION
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

> Reference date: 2026-09-21 (Monday).
>
> Cotízame un swap EUR a 5 años, pagamos fijo.

The notional is missing and nothing derives it. Everything else resolves: spot
start, 5Y maturity, EUR conventions, and `purpose: PAR_RATE_QUOTE` because no rate
is given. **Leave `notional` absent** and the system will report it.

An absent rate is not a gap here: it is what makes this a quote request.

## Output

Exactly one `pricing.InterestRateSwap` protobuf text-format message. No Markdown
fences, no commentary. Enum values such as `IBOR` are bare identifiers, never
quoted strings.
