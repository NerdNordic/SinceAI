"""MongoDB access. Tests swap in a mongomock database with set_db()."""

from __future__ import annotations

from functools import lru_cache

from . import config

_db = None


def set_db(db) -> None:
    global _db
    _db = db
    lookups.cache_clear()


def get_db():
    global _db
    if _db is None:
        from pymongo import MongoClient

        if not config.MONGODB_URI:
            raise RuntimeError("Set MONGODB_URI")
        _db = MongoClient(config.MONGODB_URI, appname="since-ai-bot",
                          serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                          socketTimeoutMS=15000)[config.MONGODB_DB]
    return _db


@lru_cache(maxsize=1)
def lookups() -> dict:
    """Small reference tables used everywhere: names and the product x market -> plant map."""
    db = get_db()
    products = {d["product_id"]: d["product_name"] for d in db.products.find({}, {"product_id": 1, "product_name": 1})}
    markets = {d["market_id"]: d["market_name"] for d in db.markets.find({}, {"market_id": 1, "market_name": 1})}
    plant = {(d["product_id"], d["market_id"]): d["supply_source"]
             for d in db.supply_operations.find({}, {"product_id": 1, "market_id": 1, "supply_source": 1})}
    kpis = {d["kpi_id"]: d for d in db.kpi_catalog.find({}, {"embedding": 0})}
    return {"products": products, "markets": markets, "plant": plant, "kpis": kpis,
            "plants": sorted(set(plant.values()))}
