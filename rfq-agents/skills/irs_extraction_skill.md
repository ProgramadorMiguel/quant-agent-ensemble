# Vanilla IRS Extraction Skill

Extract the following terms from a natural-language vanilla fixed-versus-floating
interest rate swap description:

- `notional`: positive decimal amount, without currency symbols or separators.
- `currency`: ISO 4217 uppercase code.
- `direction`: `PAYER_FIXED` when the client pays fixed, or `RECEIVER_FIXED`
  when the client receives fixed.
- `effective_date`: ISO `YYYY-MM-DD`.
- `maturity_date`: ISO `YYYY-MM-DD`. Convert an explicit maturity date only;
  do not calculate it from a tenor.
- `fixed_rate`: decimal rate (for example 2.75% becomes `0.0275`).
- `floating_index`: uppercase market index name, preserving meaningful
  separators (for example `EURIBOR`).
- `floating_tenor`: uppercase tenor such as `3M` or `6M`.
- `discount_curve`: curve identifier exactly as stated.
- `forwarding_curve`: curve identifier exactly as stated.

Use `null` for every missing value. Do not infer dates, curves, index, tenor,
direction, or rate from market convention. This MVP supports vanilla IRS only.

