"""Gemini embeddings + MongoDB Atlas Vector Search helpers.

Import these from the backend:

    from backend.vector_store import search_kpis, search_charts, register_chart

Environment:
    GEMINI_API_KEY        Google AI Studio key
    GEMINI_EMBED_MODEL    default gemini-embedding-001
    EMBED_DIM             default 768 (must match the vector index numDimensions)
"""

from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))

KPI_INDEX = "kpi_vector"
ASSET_INDEX = "asset_vector"
CHART_INDEX = "chart_vector"

_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai  # imported lazily so dry runs need no key
        from google.genai import types

        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Set GEMINI_API_KEY")
        # a hung connection must fail (and be retried), never block a request or an evaluation run forever
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60_000))
    return _client


def _normalize(v: list[float]) -> list[float]:
    # Reduced-dimension Gemini embeddings are not unit length; normalise for cosine similarity.
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# Gemini free tier counts every text as one request: 100 embed requests per minute.
EMBED_RPM = int(os.environ.get("EMBED_RPM", "90"))
_sent: list[float] = []


def _throttle(n: int) -> None:
    """Keep the number of texts sent in any 60 s window under EMBED_RPM."""
    while True:
        now = time.time()
        while _sent and now - _sent[0] > 60:
            _sent.pop(0)
        if len(_sent) + n <= EMBED_RPM:
            _sent.extend([now] * n)
            return
        wait = 60 - (now - _sent[0]) + 1
        print(f"  pacing for Gemini rate limit: waiting {wait:.0f}s")
        time.sleep(wait)


def _retry_delay(exc: Exception) -> float | None:
    m = re.search(r"retry in ([\d.]+)s", str(exc)) or re.search(r"retryDelay'?: '?(\d+)s", str(exc))
    return float(m.group(1)) + 2 if m else None


def embed(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT", batch: int = 50, retries: int = 8) -> list[list[float]]:
    """Embed texts in batches, paced under the rate limit and retrying on 429 / transient errors."""
    from google.genai import types

    batch = min(batch, EMBED_RPM)
    client = _gemini()  # missing key fails immediately, without retries
    out: list[list[float]] = []
    total = len(texts)
    for i in range(0, total, batch):
        chunk = texts[i:i + batch]
        for attempt in range(retries):
            _throttle(len(chunk))
            try:
                res = client.models.embed_content(
                    model=EMBED_MODEL,
                    contents=chunk,
                    config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=EMBED_DIM),
                )
                out.extend(_normalize(list(e.values)) for e in res.embeddings)
                if total > batch:
                    print(f"  embedded {min(i + batch, total)}/{total}")
                break
            except Exception as exc:  # noqa: BLE001 - surface after retries
                if attempt == retries - 1:
                    raise
                limited = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
                wait = _retry_delay(exc) or (61 if limited else 2 ** attempt * 2)
                print(f"  {'rate limited' if limited else exc.__class__.__name__}: retrying in {wait:.0f}s")
                time.sleep(wait)
    return out


def embed_query(text: str) -> list[float]:
    return embed([text], task_type="RETRIEVAL_QUERY")[0]


def vector_search(coll, index: str, text: str, limit: int = 5, filter: dict | None = None) -> list[dict[str, Any]]:
    stage: dict[str, Any] = {
        "index": index,
        "path": "embedding",
        "queryVector": embed_query(text),
        "numCandidates": max(100, limit * 20),
        "limit": limit,
    }
    if filter:
        stage["filter"] = filter
    pipeline = [
        {"$vectorSearch": stage},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]
    return list(coll.aggregate(pipeline))


def search_kpis(db, text: str, canonical_only: bool = True, limit: int = 5) -> list[dict[str, Any]]:
    """Map a user phrase ('toimitusvarmuus') to KPIs. Similarity only suggests:
    always resolve the hit to its canonical_metric before using it."""
    flt = {"definition_status": "canonical"} if canonical_only else None
    return vector_search(db.kpi_catalog, KPI_INDEX, text, limit, flt)


def search_assets(db, text: str, filter: dict | None = None, limit: int = 5) -> list[dict[str, Any]]:
    return vector_search(db.analytics_assets, ASSET_INDEX, text, limit, filter)


def search_charts(db, text: str, filter: dict | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """Candidate charts that look similar. The exact fingerprint decides REUSE; this only finds near-misses."""
    return vector_search(db.chart_registry, CHART_INDEX, text, limit, filter)


def register_chart(db, chart: dict[str, Any]) -> str:
    """Upsert a chart into the registry by its fingerprint and embed its description.

    Required keys: fingerprint, title, description, role, plant, kpi_ids, spec, owner.
    """
    missing = [k for k in ("fingerprint", "title", "description", "role", "plant", "kpi_ids", "spec", "owner") if k not in chart]
    if missing:
        raise ValueError(f"chart is missing {missing}")
    now = datetime.now(timezone.utc)
    doc = {
        **chart,
        "status": chart.get("status", "active"),
        "embedding_text": f"{chart['title']}. {chart['description']}",
        "embedding": embed([f"{chart['title']}. {chart['description']}"])[0],
        "embedding_model": EMBED_MODEL,
        "updated_at": now,
    }
    db.chart_registry.update_one(
        {"fingerprint": chart["fingerprint"]},
        {"$set": doc, "$setOnInsert": {"created_at": now, "use_count": 0}},
        upsert=True,
    )
    return chart["fingerprint"]
