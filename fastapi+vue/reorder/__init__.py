"""Finished-goods replenishment forecast for the Bayer x Since AI 2026 builder data pack.

Answers two questions per product x market:
  * How long does the current inventory last?          (runout date)
  * By when must replenishment be ordered at the latest? (reorder-by date)

Every number comes with a receipt: the source rows, the assumptions and the formula
steps used to compute it.
"""

from .data import DataPack, load_data_pack
from .model import Assumptions, compute_all, plant_summary, metric_definition

__all__ = [
    "DataPack",
    "load_data_pack",
    "Assumptions",
    "compute_all",
    "plant_summary",
    "metric_definition",
]
