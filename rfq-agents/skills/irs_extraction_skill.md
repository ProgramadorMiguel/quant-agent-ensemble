# Vanilla IRS Extraction Skill

Domain knowledge for extracting the economic terms of a vanilla
fixed-versus-floating single-currency interest rate swap from a
natural-language request written by a trading desk.

## 1. What the product is

Two counterparties exchange interest payments on the same notional amount, in
the same currency, over the same period. One leg pays a fixed rate agreed at
inception. The other pays a floating rate that resets periodically against a
published reference index. The notional is never exchanged; it only serves to
compute the payments.

The direction is always expressed **from the client's point of view**, and it is
named after the client's fixed leg: paying fixed is `PAYER_FIXED`, receiving
fixed is `RECEIVER_FIXED`.

Two curves are needed to value the trade, and they are not interchangeable. The
**discount curve** converts future cash flows into present value. The
**forwarding curve** projects the future fixings of the floating index. Modern
practice uses two distinct curves, so a request that names only one has not
named the other.

## 2. Fields to extract

| Field | Type | Notes |
|---|---|---|
| `notional` | positive number | No currency symbol, no thousand separators. |
| `currency` | ISO 4217, uppercase | `EUR`, `USD`, `GBP`. |
| `direction` | enum | `PAYER_FIXED` or `RECEIVER_FIXED`, from the client's fixed leg. |
| `effective_date` | ISO `YYYY-MM-DD` | Start of accrual. Also called start date or value date. |
| `maturity_date` | ISO `YYYY-MM-DD` | End of the swap. Explicit calendar date only. |
| `fixed_rate` | decimal fraction | `2.75%` is `0.0275`. |
| `floating_index` | uppercase string | Reference index name, as stated. |
| `floating_tenor` | uppercase string | Reset tenor of the index, such as `3M` or `6M`. |
| `discount_curve` | string | Curve identifier, exactly as stated. |
| `forwarding_curve` | string | Curve identifier, exactly as stated. |

Omit any field the request does not state. All ten are required by the
validation layer, so an omission is detected and reported downstream; it never
passes silently.

## 3. Desk shorthand

Requests are frequently terse. These readings are legitimate because the text
states the information, only compactly:

| Written | Reading |
|---|---|
| "pay 2.75", "pay fixed 2.75" | `direction: PAYER_FIXED`, `fixed_rate: 0.0275` |
| "rec 3.1", "receive fixed 3.1" | `direction: RECEIVER_FIXED`, `fixed_rate: 0.031` |
| "vs 6s", "vs 6m", "against 6M" | floating tenor `6M` |
| "vs 3s" | floating tenor `3M` |
| "275bp", "275 bps" | `0.0275` |
| "10mm", "10 MM", "EUR 10m", "10 million" | `10000000` |
| "1bn", "1 billion" | `1000000000` |
| "2,75%" (decimal comma) | `0.0275` |

Common index names, when the text names them: `EURIBOR`, `SOFR`, `SONIA`,
`ESTR`, `TONA`, `SARON`. Preserve meaningful separators in curve identifiers
exactly as written, for example `EUR-EURIBOR-6M`, `USD-SOFR`, `GBP-OIS`.

## 4. What must never be inferred

This is the core constraint of this skill, and the reason the system can measure
hallucination at all. Every field below is one that a knowledgeable human would
be able to fill from market convention. **You must not.**

- **The index from the currency.** "EUR swap" does not imply `EURIBOR`. "USD
  swap" does not imply `SOFR`. Omit if not named.
- **The tenor from the index.** "EURIBOR" does not imply `6M`. "vs EURIBOR"
  with no tenor means the tenor was not stated.
- **The curves from anything.** `EUR-OIS` is the conventional discount curve for
  EUR, and that is exactly why naming it yourself is a hallucination. Omit both
  curve fields unless the text names them.
- **A maturity date from a tenor.** "5-year swap", "5y", "5yr" state a tenor,
  not a date. Computing `effective_date + 5 years` is a calculation, and the
  result would be wrong in general because it ignores calendars and business day
  conventions. Omit `maturity_date`.
- **An effective date from "spot".** "Spot start", "spot", "T+2", "starting
  today" do not resolve to a date without a calendar and a valuation date.
  Omit `effective_date`.
- **A direction from context.** Neither the currency, nor the sign of the rate,
  nor who is sending the request determines who pays fixed.
- **A rate from the word "par", "market" or "mid".** These describe a rate to be
  determined, not a stated rate. Omit `fixed_rate`.

If a request states only some terms, extract those and omit the rest. Returning
six of ten fields correctly is a success. Returning ten fields of which four
were invented is a failure, and a more damaging one.

## 5. Worked examples

**Complete request**

> Vanilla EUR IRS, notional EUR 10,000,000. We pay fixed at 2.75% and receive
> 6M EURIBOR. Effective 2026-09-01, maturity 2031-09-01. Discount on EUR-OIS,
> forwarding on EUR-EURIBOR-6M.

All ten fields are stated: `notional: 10000000`, `currency: "EUR"`,
`direction: PAYER_FIXED`, `effective_date: "2026-09-01"`,
`maturity_date: "2031-09-01"`, `fixed_rate: 0.0275`,
`floating_index: "EURIBOR"`, `floating_tenor: "6M"`,
`discount_curve: "EUR-OIS"`, `forwarding_curve: "EUR-EURIBOR-6M"`.

**Incomplete request**

> EUR swap, 5,000,000. We pay fixed at 2.60% from 2026-09-01 to 2031-09-01.

Extract six fields: notional, currency, direction, both dates and the rate.
Omit `floating_index`, `floating_tenor`, `discount_curve` and
`forwarding_curve`. The temptation to write `EURIBOR` and `EUR-OIS` is exactly
what must be resisted: the text does not say them.

**Terse request with a tenor instead of a date**

> 5y USD, pay 3.85 vs 3s SOFR, spot start, 25mm.

Extract `notional: 25000000`, `currency: "USD"`, `direction: PAYER_FIXED`,
`fixed_rate: 0.0385`, `floating_index: "SOFR"`, `floating_tenor: "3M"`.
Omit both dates: "5y" is a tenor and "spot start" is a convention, neither is a
calendar date. Omit both curves: none is named.

## 6. Scope

This skill covers vanilla single-currency fixed-versus-floating IRS only, on a
constant notional and with no optionality. It does not cover basis swaps,
cross-currency swaps, overnight index swaps quoted as a separate product, FRAs,
caps, floors, swaptions, or amortising and step-up structures. Those requests
are rejected earlier in the pipeline and never reach this skill.
