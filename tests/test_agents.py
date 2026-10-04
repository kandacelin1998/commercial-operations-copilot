from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
from openai import OpenAIError

import src.agents as agents
from src.merchandising import build_decision_queue, calculate_product_metrics


ROOT = Path(__file__).resolve().parents[1]


def _evidence(data: pd.DataFrame, sku: str, fields: list[str]) -> list[dict]:
    row = calculate_product_metrics(data).set_index("sku").loc[sku]
    return [{"field": field, "value": float(row[field])} for field in fields]


def _agent_output(
    name: str,
    action: str,
    data: pd.DataFrame,
    fields: list[str],
    sku: str = "SKU017",
) -> dict:
    row = calculate_product_metrics(data).set_index("sku").loc[sku]
    return {
        "recommendation": action,
        "sku": sku,
        "product_name": row["product_name"],
        "evidence": _evidence(data, sku, fields),
        "trade_off": f"{name} prioritises its objective while recognising the competing commercial pressure.",
        "confidence": "MEDIUM",
    }


class AgentGroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = pd.read_csv(ROOT / "data/fashion/fashion_products.csv")

    def test_specialist_context_contains_objective_and_python_metrics(self):
        focus_product = agents._focus_product(self.products)
        focus = calculate_product_metrics(focus_product).iloc[0]
        self.assertEqual(len(set(agents.SPECIALIST_OBJECTIVES.values())), 3)
        objective_checks = {
            "Demand": ("sell-through", "weekly sales pace"),
            "Inventory": ("weeks of cover", "inventory value"),
            "Pricing": ("gross-margin preservation", "price/cost relationship"),
        }
        for agent_name, objective in agents.SPECIALIST_OBJECTIVES.items():
            with self.subTest(agent=agent_name):
                system_prompt, user_prompt = agents.build_specialist_context(agent_name, focus_product)
                supplied = json.loads(user_prompt)
                product = supplied["focus_product"]
                self.assertIn(objective, system_prompt)
                self.assertEqual(product["sku"], focus["sku"])
                self.assertEqual(product["sell_through_pct"], focus["sell_through_pct"])
                self.assertEqual(product["weeks_of_cover"], focus["weeks_of_cover"])
                self.assertEqual(product["inventory_value"], focus["inventory_value"])
                self.assertIn("Evaluate only the supplied focus product", system_prompt)
                self.assertIn("Do not calculate or invent unsupported metrics", system_prompt)
                for objective_phrase in objective_checks[agent_name]:
                    self.assertIn(objective_phrase, objective)

        pricing_objective = agents.SPECIALIST_OBJECTIVES["Pricing"]
        self.assertIn("can justify KEEP FULL PRICE", pricing_objective)
        self.assertIn("do not automatically adopt those other perspectives", pricing_objective)

    def test_director_context_requires_evidence_based_conflict_resolution(self):
        focus_product = agents._focus_product(self.products)
        focus_sku = focus_product.iloc[0]["sku"]
        specialists = (
            _agent_output("Demand", "MONITOR", self.products, ["sell_through_pct"], focus_sku),
            _agent_output("Inventory", "MARKDOWN", self.products, ["weeks_of_cover"], focus_sku),
            _agent_output("Pricing", "KEEP FULL PRICE", self.products, ["margin_pct"], focus_sku),
        )
        system_prompt, user_prompt = agents.build_director_context(focus_product, *specialists)
        supplied = json.loads(user_prompt)

        self.assertIn("Do not choose a product just because it has the highest sell-through", system_prompt)
        self.assertIn("Do not set confidence by counting votes", system_prompt)
        self.assertIn("Do not decide by majority vote", system_prompt)
        self.assertIn("explain why the chosen action outweighs each competing", system_prompt)
        self.assertEqual(supplied["focus_product"]["sku"], focus_sku)
        self.assertTrue(
            all(
                rec["sku"] == supplied["focus_product"]["sku"]
                for rec in supplied["specialists"].values()
            )
        )
        self.assertEqual(
            supplied["specialists"]["Inventory"]["recommendation"],
            "MARKDOWN",
        )
        self.assertEqual(
            supplied["focus_product"]["weeks_of_cover"],
            calculate_product_metrics(focus_product).iloc[0]["weeks_of_cover"],
        )
        self.assertGreater(
            len({rec["recommendation"] for rec in supplied["specialists"].values()}),
            1,
        )

    def test_specialist_output_rejects_unknown_sku_action_and_metric(self):
        valid = _agent_output("Demand", "MONITOR", self.products, ["sell_through_pct"])
        invalid_sku = {**valid, "sku": "SKU-UNKNOWN"}
        invalid_action = {**valid, "recommendation": "DISCOUNT"}
        invalid_evidence = {
            **valid,
            "evidence": [{"field": "sell_through_pct", "value": 99.9}],
        }

        for result in (invalid_sku, invalid_action, invalid_evidence):
            with self.subTest(result=result):
                with self.assertRaises(agents.AgentError):
                    agents.validate_specialist_output(result, "Demand", self.products)

    def test_responses_api_runs_all_specialists_and_director_with_schema(self):
        focus_sku = build_decision_queue(self.products, top_n=1).iloc[0]["sku"]
        focus_row = calculate_product_metrics(self.products).set_index("sku").loc[focus_sku]
        demand = _agent_output(
            "Demand", "MONITOR", self.products, ["sell_through_pct", "units_sold"], focus_sku
        )
        inventory = _agent_output(
            "Inventory", "MARKDOWN", self.products, ["weeks_of_cover", "inventory_value"], focus_sku
        )
        pricing = _agent_output(
            "Pricing", "KEEP FULL PRICE", self.products, ["margin_pct", "price"], focus_sku
        )
        director = {
            "final_action": "MARKDOWN",
            "sku": focus_sku,
            "product_name": focus_row["product_name"],
            "why": {
                "explanation": "Weak demand and excessive stock outweigh the benefit of protecting margin.",
                "evidence": _evidence(
                    self.products,
                    focus_sku,
                    ["sell_through_pct", "weeks_of_cover", "inventory_value", "margin_pct"],
                ),
            },
            "agent_debate": {
                "recommendations": {
                    "Demand": "MONITOR",
                    "Inventory": "MARKDOWN",
                    "Pricing": "KEEP FULL PRICE",
                },
                "disagreement": True,
                "resolution": "Inventory exposure outweighs the pricing case for protecting margin.",
            },
            "confidence": "MEDIUM",
            "risk": {
                "level": "HIGH",
                "explanation": "Slow demand and prolonged stock cover expose the business to ageing inventory.",
                "evidence": _evidence(
                    self.products,
                    focus_sku,
                    ["sell_through_pct", "weeks_of_cover", "inventory_value"],
                ),
            },
        }
        outputs = [demand, inventory, pricing, director]
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.responses.create.side_effect = [
            SimpleNamespace(output_text=json.dumps(output)) for output in outputs
        ]

        with (
            patch.object(agents, "_get_client", return_value=client),
            patch.object(agents, "DEFAULT_MODEL", "demo-test-model"),
        ):
            result = agents.run_merchandising_panel(self.products)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(client.responses.create.call_count, 4)
        for call in client.responses.create.call_args_list:
            self.assertEqual(call.kwargs["model"], "demo-test-model")
            self.assertEqual(call.kwargs["text"]["format"]["type"], "json_schema")
            self.assertTrue(call.kwargs["text"]["format"]["strict"])
            self.assertNotIn("temperature", call.kwargs)

        specialist_inputs = [
            json.loads(call.kwargs["input"])["focus_product"]
            for call in client.responses.create.call_args_list[:3]
        ]
        director_input = json.loads(client.responses.create.call_args_list[3].kwargs["input"])
        self.assertEqual([product["sku"] for product in specialist_inputs], [focus_sku] * 3)
        self.assertEqual(specialist_inputs[0], specialist_inputs[1])
        self.assertEqual(specialist_inputs[1], specialist_inputs[2])
        self.assertEqual(director_input["focus_product"], specialist_inputs[0])
        self.assertTrue(
            all(
                recommendation["sku"] == focus_sku
                for recommendation in director_input["specialists"].values()
            )
        )

        final_decision = result["final_decision"]
        self.assertEqual(final_decision["final_action"], "MARKDOWN")
        self.assertEqual(final_decision["sku"], focus_sku)
        self.assertEqual(final_decision["product_name"], focus_row["product_name"])
        self.assertTrue(final_decision["agent_debate"]["disagreement"])
        self.assertEqual(final_decision["agent_debate"]["recommendations"]["Inventory"], "MARKDOWN")
        self.assertEqual(final_decision["risk"]["level"], "HIGH")
        self.assertTrue(
            {
                "final_action",
                "sku",
                "product_name",
                "why",
                "agent_debate",
                "confidence",
                "risk",
            }.issubset(final_decision)
        )

    def test_director_rejects_unknown_product_and_untrue_disagreement(self):
        demand = _agent_output("Demand", "MONITOR", self.products, ["sell_through_pct"])
        inventory = _agent_output("Inventory", "MARKDOWN", self.products, ["weeks_of_cover"])
        pricing = _agent_output("Pricing", "KEEP FULL PRICE", self.products, ["margin_pct"])
        valid = {
            "final_action": "MARKDOWN",
            "sku": "SKU017",
            "product_name": "Sequinned Mini Skirt",
            "why": {
                "explanation": "Weak demand and excess inventory outweigh margin protection.",
                "evidence": _evidence(
                    self.products, "SKU017", ["sell_through_pct", "weeks_of_cover"]
                ),
            },
            "agent_debate": {
                "recommendations": {
                    "Demand": "MONITOR",
                    "Inventory": "MARKDOWN",
                    "Pricing": "KEEP FULL PRICE",
                },
                "disagreement": True,
                "resolution": "Inventory risk outweighs the competing recommendation.",
            },
            "confidence": "MEDIUM",
            "risk": {
                "level": "HIGH",
                "explanation": "Weak demand and excessive stock cover increase inventory exposure.",
                "evidence": _evidence(self.products, "SKU017", ["weeks_of_cover"]),
            },
        }
        invalid_sku = {**valid, "sku": "SKU-UNKNOWN"}
        invalid_disagreement = {
            **valid,
            "agent_debate": {**valid["agent_debate"], "disagreement": False},
        }

        majority_opposed = {
            **valid,
            "agent_debate": {
                **valid["agent_debate"],
                "recommendations": {
                    "Demand": "KEEP FULL PRICE",
                    "Inventory": "KEEP FULL PRICE",
                    "Pricing": "MARKDOWN",
                },
                "resolution": "Weak demand and excessive stock cover outweigh preserving the current price.",
            },
        }
        specialist_views = (
            _agent_output("Demand", "KEEP FULL PRICE", self.products, ["margin_pct"]),
            _agent_output("Inventory", "KEEP FULL PRICE", self.products, ["price"]),
            _agent_output("Pricing", "MARKDOWN", self.products, ["weeks_of_cover"]),
        )
        validated_majority_opposed = agents.validate_director_output(
            majority_opposed,
            self.products,
            *specialist_views,
        )
        self.assertEqual(validated_majority_opposed["final_action"], "MARKDOWN")
        self.assertEqual(
            validated_majority_opposed["agent_debate"]["recommendations"]["Demand"],
            "KEEP FULL PRICE",
        )

        for result in (invalid_sku, invalid_disagreement):
            with self.subTest(result=result):
                with self.assertRaises(agents.AgentError):
                    agents.validate_director_output(
                        result,
                        self.products,
                        demand,
                        inventory,
                        pricing,
                    )

    def test_api_errors_propagate_without_a_success_shaped_result(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.responses.create.side_effect = OpenAIError("simulated API failure")

        with patch.object(agents, "_get_client", return_value=client):
            with self.assertRaisesRegex(OpenAIError, "simulated API failure"):
                agents.run_merchandising_panel(self.products)


if __name__ == "__main__":
    unittest.main()
