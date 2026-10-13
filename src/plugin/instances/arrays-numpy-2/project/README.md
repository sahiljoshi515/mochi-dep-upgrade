# arrays

Small numeric helpers on NumPy for the lab's measurement scripts.

- `arrays.loading`: `as_array` (float64 arrays from lists or arrays, no copy
  for arrays), `from_records`, `parse_matrix`, `column`.
- `arrays.stats`: `describe` (count, mean, std, min, max, product, all_positive),
  `zscore`, `summary_text` (plain numbers, e.g. `n=3 mean=2.0 std=0.816`),
  `fill_missing`, `running_product`, `has_missing`.
- `arrays.smoothing`: `moving_average`, `area_under` (trapezoids), `stack_rows`,
  `detrend`, `rescale`.
- `arrays.binning`: `histogram`, `bin_labels`, `mask_members`, `count_in_bins`, `quantiles`.
- `arrays.geometry`: `turn_direction`, `polygon_area`, `reduce_axis` (an
  `ArrayError` for a bad axis), `bounding_box`, `centroid`.
- `arrays.export`: `to_csv_lines`, `labels_array`, `is_text`, `to_bytes_rows`.

```bash
uv sync
uv run pytest
```
