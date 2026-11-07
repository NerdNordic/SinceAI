"""Loading and validating the sheets the replenishment model needs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ACTUAL = "actual_like_synthetic"
FORECAST = "forecast_like_synthetic"

REQUIRED_COLUMNS = {
    "Product_Market_Monthly": [
        "product_id", "market_id", "month", "units_shipped_syn",
        "inventory_weeks_syn", "otif_pct_syn", "value_type",
    ],
    "Supply_Operations": [
        "product_id", "market_id", "supply_source", "primary_mode",
        "otif_pct_syn", "inventory_weeks_syn", "forecast_accuracy_pct_syn", "risk_status",
    ],
    "Products": ["product_id", "product_name", "therapeutic_area"],
    "Markets": ["market_id", "market_name", "region"],
    "KPI_Catalog": ["kpi_id", "kpi_name", "canonical_metric", "definition_status", "approval_status", "unit"],
}


@dataclass
class DataPack:
    monthly: pd.DataFrame
    supply: pd.DataFrame
    products: pd.DataFrame
    markets: pd.DataFrame
    kpis: pd.DataFrame
    source_file: str

    @property
    def latest_month(self) -> pd.Timestamp:
        return self.monthly["month"].max()


def load_data_pack(path: str | Path) -> DataPack:
    path = Path(path)
    sheets = pd.read_excel(path, sheet_name=list(REQUIRED_COLUMNS))
    for name, cols in REQUIRED_COLUMNS.items():
        missing = [c for c in cols if c not in sheets[name].columns]
        if missing:
            raise ValueError(f"Sheet {name} is missing columns: {missing}")

    monthly = sheets["Product_Market_Monthly"].copy()
    monthly["month"] = pd.to_datetime(monthly["month"])
    monthly = monthly.sort_values(["product_id", "market_id", "month"]).reset_index(drop=True)

    supply = sheets["Supply_Operations"].copy()
    dupes = supply.duplicated(["product_id", "market_id"]).sum()
    if dupes:
        raise ValueError(f"Supply_Operations has {dupes} duplicate product x market rows")

    return DataPack(
        monthly=monthly,
        supply=supply,
        products=sheets["Products"],
        markets=sheets["Markets"],
        kpis=sheets["KPI_Catalog"],
        source_file=path.name,
    )
