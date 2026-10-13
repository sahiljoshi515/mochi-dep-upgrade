"""arrays: small numeric helpers on NumPy."""

from arrays.binning import bin_labels, count_in_bins, histogram, mask_members, quantiles
from arrays.errors import ArrayError
from arrays.export import is_text, labels_array, to_bytes_rows, to_csv_lines
from arrays.geometry import bounding_box, centroid, polygon_area, reduce_axis, turn_direction
from arrays.loading import as_array, column, from_records, parse_matrix
from arrays.smoothing import area_under, detrend, moving_average, rescale, stack_rows
from arrays.stats import describe, fill_missing, has_missing, running_product, summary_text, zscore

__all__ = [
    "ArrayError",
    "area_under",
    "as_array",
    "bin_labels",
    "bounding_box",
    "centroid",
    "column",
    "count_in_bins",
    "describe",
    "detrend",
    "fill_missing",
    "from_records",
    "has_missing",
    "histogram",
    "is_text",
    "labels_array",
    "mask_members",
    "moving_average",
    "parse_matrix",
    "polygon_area",
    "quantiles",
    "reduce_axis",
    "rescale",
    "running_product",
    "stack_rows",
    "summary_text",
    "to_bytes_rows",
    "to_csv_lines",
    "turn_direction",
    "zscore",
]
