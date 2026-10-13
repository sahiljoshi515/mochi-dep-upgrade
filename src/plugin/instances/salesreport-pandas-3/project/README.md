# salesreport

Sales reports from the warehouse's whitespace-separated exports.

- `salesreport.loading`: `load_sales(text)` reads `date region product units
  unit_price notes` rows (`-` is missing) and adds `revenue`; `load_prices(text)`
  reads a `date,price` CSV into a Series.
- `salesreport.cleaning`: `clean(frame)` carries the last unit price forward,
  fills missing notes with `""`, strips and title-cases every text column, and
  recomputes revenue; `round_prices` rounds every float.
- `salesreport.metrics`: monthly revenue (month ends), top products, the first
  week of orders, each region's share of revenue, units by product.
- `salesreport.segments`: large-order flags, one region's rows, rush orders.
- `salesreport.reporting`: pivot, region table, records and a summary.
- `salesreport.formatting`: money strings and a printable table.

Functions never change the frame they are given; they return new frames.

```bash
uv sync
uv run pytest
```
