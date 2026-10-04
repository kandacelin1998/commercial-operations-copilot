from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class CommercialDecision:
    sku: str
    product_name: str
    action: str
    reason: str
    confidence: str
    sell_through_pct: float | None = None
    weeks_of_cover: float | None = None
    margin_pct: float | None = None
    inventory_value: float | None = None


@dataclass
class CollectionSimulation:
    budget: float
    investment: float
    average_margin: float
    within_budget: bool
    over_budget: float = 0.0
    target_margin: float = 0.0
    recommendations: List[CommercialDecision] = field(default_factory=list)
