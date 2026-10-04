from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from src.merchandising import calculate_product_metrics
from src.simulator import recommend_collection_actions


ROOT = Path(__file__).resolve().parents[1]


class ProductMetricsTests(unittest.TestCase):
    def test_calculates_commercial_metrics_deterministically(self):
        products = pd.DataFrame(
            [
                {
                    "sku": "SKU-TEST",
                    "product_name": "Test Product",
                    "price": 100.0,
                    "cost": 40.0,
                    "units_sold": 120,
                    "units_available": 60,
                    "return_rate": 0.05,
                }
            ]
        )

        product = calculate_product_metrics(products).iloc[0]

        self.assertEqual(product["margin_pct"], 60.0)
        self.assertEqual(product["inventory_value"], 2400.0)
        self.assertEqual(product["sell_through_pct"], 66.7)
        self.assertEqual(product["weekly_units_sold"], 10.0)
        self.assertEqual(product["weeks_of_cover"], 6.0)


class CollectionSimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collection = pd.read_csv(ROOT / "data/fashion/proposed_collection.csv")

    def test_requested_budget_and_margin_scenarios(self):
        scenarios = (
            (500000, 68, {"KEEP": 9, "REPRICE": 6}),
            (400000, 68, {"CUT": 3, "KEEP": 6, "REPRICE": 6}),
            (500000, 72, {"REPRICE": 14, "KEEP": 1}),
        )
        for budget, target_margin, expected in scenarios:
            with self.subTest(budget=budget, target_margin=target_margin):
                result = recommend_collection_actions(self.collection, budget, target_margin)
                actions = pd.Series(
                    [recommendation["action"] for recommendation in result["recommendations"]]
                ).value_counts().to_dict()
                self.assertEqual(actions, expected)

    def test_keep_explanation_distinguishes_product_action_from_budget_status(self):
        result = recommend_collection_actions(self.collection, 400000, 68)
        keep_recommendations = [
            recommendation
            for recommendation in result["recommendations"]
            if recommendation["action"] == "KEEP"
        ]

        self.assertTrue(keep_recommendations)
        for recommendation in keep_recommendations:
            self.assertIn("product-level cut threshold", recommendation["reason"])
            self.assertIn("over budget", recommendation["reason"])
            self.assertNotIn("investment remains within the budget envelope", recommendation["reason"])


if __name__ == "__main__":
    unittest.main()
