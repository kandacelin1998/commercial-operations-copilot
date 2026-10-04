from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from typing import Any

import pandas as pd
from openai import OpenAI

from src.merchandising import build_decision_queue, calculate_product_metrics


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
ALLOWED_ACTIONS = ("REORDER", "MARKDOWN", "KEEP FULL PRICE", "MONITOR", "INVESTIGATE")
CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")
RISK_LEVELS = ("HIGH", "MEDIUM", "LOW")
METRIC_FIELDS = (
    "price",
    "cost",
    "units_sold",
    "units_available",
    "return_rate",
    "margin_pct",
    "inventory_value",
    "sell_through_pct",
    "weekly_units_sold",
    "weeks_of_cover",
)
PRODUCT_FIELDS = ("sku", "product_name", *METRIC_FIELDS)
AGENT_NAMES = ("Demand", "Inventory", "Pricing")

SPECIALIST_OBJECTIVES = {
    "Demand": (
        "Optimize for demand performance: assess demand momentum only through the supplied demand measures, including "
        "sell-through, units sold, weekly sales pace, and available stock; do not infer an unsupported time trend. "
        "Use those signals to judge whether the current sales pace can absorb supply; weak sell-through or sales pace "
        "can support markdown, while strong demand can support replenishment or holding price."
    ),
    "Inventory": (
        "Optimize for inventory health: assess weeks of cover, inventory value, units available, and stock-out risk. "
        "Judge the cost and exposure of excess stock against the risk of reducing availability; unusually high cover "
        "or exposure can support markdown, while tight cover can support reorder or protecting availability."
    ),
    "Pricing": (
        "Optimize for price integrity and gross-margin preservation: assess margin_pct and the price/cost relationship "
        "before recommending a price action. Strong supported margin can justify KEEP FULL PRICE even when demand or "
        "inventory signals point toward markdown; do not automatically adopt those other perspectives. A markdown "
        "may still be appropriate when the pricing evidence supports sacrificing margin to improve commercial outcomes."
    ),
}

SPECIALIST_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
        "sku": {"type": "string"},
        "product_name": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(METRIC_FIELDS)},
                    "value": {"type": "number"},
                },
                "required": ["field", "value"],
                "additionalProperties": False,
            },
        },
        "trade_off": {"type": "string"},
        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
    },
    "required": [
        "recommendation",
        "sku",
        "product_name",
        "evidence",
        "trade_off",
        "confidence",
    ],
    "additionalProperties": False,
}

DIRECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "final_action": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
        "sku": {"type": "string"},
        "product_name": {"type": "string"},
        "why": {
            "type": "object",
            "properties": {
                "explanation": {"type": "string"},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": list(METRIC_FIELDS)},
                            "value": {"type": "number"},
                        },
                        "required": ["field", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["explanation", "evidence"],
            "additionalProperties": False,
        },
        "agent_debate": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "object",
                    "properties": {
                        "Demand": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
                        "Inventory": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
                        "Pricing": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
                    },
                    "required": list(AGENT_NAMES),
                    "additionalProperties": False,
                },
                "disagreement": {"type": "boolean"},
                "resolution": {"type": "string"},
            },
            "required": ["recommendations", "disagreement", "resolution"],
            "additionalProperties": False,
        },
        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
        "risk": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": list(RISK_LEVELS)},
                "explanation": {"type": "string"},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": list(METRIC_FIELDS)},
                            "value": {"type": "number"},
                        },
                        "required": ["field", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["level", "explanation", "evidence"],
            "additionalProperties": False,
        },
    },
    "required": [
        "final_action",
        "sku",
        "product_name",
        "why",
        "agent_debate",
        "confidence",
        "risk",
    ],
    "additionalProperties": False,
}


class AgentError(RuntimeError):
    """Raised when AI agent configuration or output is invalid."""


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AgentError(
            "The deterministic simulator works without an API key. "
            "The AI Merchandising Panel requires OPENAI_API_KEY."
        )
    return OpenAI(api_key=api_key, timeout=45.0, max_retries=1)


def _metric_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    metrics = calculate_product_metrics(df)
    if metrics.empty:
        raise AgentError("AI analysis requires at least one product.")
    missing = [field for field in PRODUCT_FIELDS if field not in metrics.columns]
    if missing:
        raise AgentError(f"Product metrics are missing required fields: {missing}")
    return json.loads(metrics.loc[:, PRODUCT_FIELDS].to_json(orient="records"))


def _focus_product(df: pd.DataFrame) -> pd.DataFrame:
    metrics = calculate_product_metrics(df)
    queue = build_decision_queue(metrics, top_n=1)
    if queue.empty:
        raise AgentError("AI analysis requires at least one product in the decision queue.")
    focus_sku = queue.iloc[0]["sku"]
    focus_product = metrics.loc[metrics["sku"] == focus_sku].copy()
    if len(focus_product) != 1:
        raise AgentError(f"The decision queue focus SKU {focus_sku!r} is not unique.")
    return focus_product.reset_index(drop=True)


def build_specialist_context(agent_name: str, df: pd.DataFrame) -> tuple[str, str]:
    """Build instructions and data context for one grounded specialist."""
    if agent_name not in SPECIALIST_OBJECTIVES:
        raise ValueError(f"Unknown specialist agent: {agent_name}")
    records = _metric_records(df)
    if len(records) != 1:
        raise AgentError("A specialist must receive exactly one focus product.")
    system_prompt = (
        f"You are the {agent_name} Analyst. {SPECIALIST_OBJECTIVES[agent_name]} "
        "Evaluate only the supplied focus product. Only use numerical values present in its metrics. "
        "Do not calculate or invent unsupported metrics. Your recommendation must refer to a product "
        "and SKU in the input and must be one of REORDER, MARKDOWN, KEEP FULL PRICE, MONITOR, or INVESTIGATE. "
        "Make an independent recommendation from your stated specialist objective; do not imitate or anticipate "
        "another specialist's view. Weigh your objective's relevant evidence rather than applying a fixed rule. "
        "The evidence must cite actual numeric fields and exact values from that product's supplied metrics. "
        "Return evidence as field/value pairs. Keep trade_off qualitative: no numbers, SKUs, or product names. "
        "Set confidence from how clearly the cited evidence supports your recommendation, not from other agents' votes. "
        "Return only the requested structured output."
    )
    user_prompt = json.dumps(
        {
            "objective": SPECIALIST_OBJECTIVES[agent_name],
            "focus_product": records[0],
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return system_prompt, user_prompt


def build_director_context(
    df: pd.DataFrame,
    demand_rec: Mapping[str, Any],
    inventory_rec: Mapping[str, Any],
    pricing_rec: Mapping[str, Any],
) -> tuple[str, str]:
    """Build a Director prompt with calculated metrics and validated specialist outputs."""
    records = _metric_records(df)
    if len(records) != 1:
        raise AgentError("The Director must receive exactly one focus product.")
    focus_sku = records[0]["sku"]
    for agent_name, recommendation in (
        ("Demand", demand_rec),
        ("Inventory", inventory_rec),
        ("Pricing", pricing_rec),
    ):
        if recommendation.get("sku") != focus_sku:
            raise AgentError(f"The {agent_name} recommendation does not match the focus product.")
    system_prompt = (
        "You are the Merchandising Director. Compare all three specialist recommendations, their cited evidence, "
        "and the underlying Python-calculated metrics for the same focus product. Explicitly identify whether they disagree. "
        "Select one action for the supplied focus product and do not change its SKU. Do not choose a product just because it has the highest "
        "sell-through: weigh demand and sales pace, excessive cover, inventory value, margin, and stock-out risk. "
        "Do not decide by majority vote or by counting recommendations. Resolve conflicts by judging which cited "
        "commercial evidence is most material, and explicitly explain why the chosen action outweighs each competing "
        "recommendation's strongest case. Use only products and numerical values in the supplied data. Do not calculate or invent metrics. "
        "Every numeric citation must be an exact field/value pair from the chosen product's metrics. "
        "The explanation, debate resolution, and risk explanation must be qualitative, without numbers, SKUs, "
        "or product names; cite figures using their structured evidence fields. Confidence must be evidence-based: "
        "HIGH only when multiple independent indicators support the decision without material contradiction, "
        "MEDIUM when evidence favours one action but trade-offs remain, and LOW when evidence is weak or conflicting. "
        "Do not set confidence by counting votes. Risk must reflect the selected product's cited commercial evidence. "
        "Return only the requested structured output."
    )
    user_prompt = json.dumps(
        {
            "focus_product": records[0],
            "specialists": {
                "Demand": demand_rec,
                "Inventory": inventory_rec,
                "Pricing": pricing_rec,
            },
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return system_prompt, user_prompt


def _json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "schema": schema,
            "strict": True,
        }
    }


def _call_responses(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    response = client.responses.create(
        model=DEFAULT_MODEL,
        instructions=system_prompt,
        input=user_prompt,
        text=_json_schema_format(schema_name, schema),
        max_output_tokens=1200,
    )
    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise AgentError(f"The {schema_name} returned no structured output.")
    try:
        result = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise AgentError(f"The {schema_name} returned invalid JSON: {error.msg}.") from error
    if not isinstance(result, dict):
        raise AgentError(f"The {schema_name} output must be a JSON object.")
    return result


def _validate_text(value: Any, label: str, records: list[dict[str, Any]]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentError(f"{label} must be a non-empty string.")
    if re.search(r"\d", value):
        raise AgentError(f"{label} must not contain uncited numbers.")
    for record in records:
        if record["product_name"].casefold() in value.casefold():
            raise AgentError(f"{label} must not refer to an unstructured product name.")
    return value.strip()


def _validate_evidence(
    evidence: Any,
    record: Mapping[str, Any],
    label: str,
    minimum_items: int = 1,
) -> list[dict[str, Any]]:
    if not isinstance(evidence, list) or len(evidence) < minimum_items:
        raise AgentError(f"{label} must contain at least {minimum_items} evidence citation(s).")
    validated = []
    seen_fields = set()
    for citation in evidence:
        if not isinstance(citation, dict) or set(citation) != {"field", "value"}:
            raise AgentError(f"{label} citations must contain only field and value.")
        field = citation["field"]
        value = citation["value"]
        if field not in METRIC_FIELDS or field in seen_fields:
            raise AgentError(f"{label} cites an unsupported or duplicated metric field: {field!r}.")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise AgentError(f"{label} citation for {field} must be a finite number.")
        actual = record.get(field)
        if not isinstance(actual, (int, float)) or not math.isclose(value, actual, rel_tol=0, abs_tol=1e-9):
            raise AgentError(f"{label} cites {field}={value}, which does not match the supplied product metrics.")
        validated.append({"field": field, "value": actual})
        seen_fields.add(field)
    return validated


def validate_specialist_output(
    result: Mapping[str, Any],
    agent_name: str,
    df: pd.DataFrame,
) -> dict[str, Any]:
    required = {"recommendation", "sku", "product_name", "evidence", "trade_off", "confidence"}
    if not isinstance(result, Mapping) or set(result) != required:
        raise AgentError(f"{agent_name} output must contain exactly: {', '.join(sorted(required))}.")
    records = _metric_records(df)
    record_by_sku = {record["sku"]: record for record in records}
    if not isinstance(result["recommendation"], str) or result["recommendation"] not in ALLOWED_ACTIONS:
        raise AgentError(f"{agent_name} returned an unsupported recommendation.")
    if not isinstance(result["sku"], str):
        raise AgentError(f"{agent_name} must select an SKU from the supplied data.")
    record = record_by_sku.get(result["sku"])
    if record is None or result["product_name"] != record["product_name"]:
        raise AgentError(f"{agent_name} selected a product or SKU not present in the supplied data.")
    if not isinstance(result["confidence"], str) or result["confidence"] not in CONFIDENCE_LEVELS:
        raise AgentError(f"{agent_name} returned an unsupported confidence level.")
    return {
        **result,
        "evidence": _validate_evidence(result["evidence"], record, f"{agent_name} evidence"),
        "trade_off": _validate_text(result["trade_off"], f"{agent_name} trade-off", records),
    }


def _run_specialist(agent_name: str, df: pd.DataFrame, client: OpenAI) -> dict[str, Any]:
    system_prompt, user_prompt = build_specialist_context(agent_name, df)
    result = _call_responses(
        client,
        system_prompt,
        user_prompt,
        f"{agent_name.lower()}_analysis",
        SPECIALIST_SCHEMA,
    )
    return validate_specialist_output(result, agent_name, df)


def demand_analyst(df: pd.DataFrame, client: OpenAI | None = None) -> dict[str, Any]:
    return _run_specialist("Demand", df, client or _get_client())


def inventory_analyst(df: pd.DataFrame, client: OpenAI | None = None) -> dict[str, Any]:
    return _run_specialist("Inventory", df, client or _get_client())


def pricing_analyst(df: pd.DataFrame, client: OpenAI | None = None) -> dict[str, Any]:
    return _run_specialist("Pricing", df, client or _get_client())


def validate_director_output(
    result: Mapping[str, Any],
    df: pd.DataFrame,
    demand_rec: Mapping[str, Any],
    inventory_rec: Mapping[str, Any],
    pricing_rec: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "final_action",
        "sku",
        "product_name",
        "why",
        "agent_debate",
        "confidence",
        "risk",
    }
    if not isinstance(result, Mapping) or set(result) != required:
        raise AgentError(f"Director output must contain exactly: {', '.join(sorted(required))}.")
    records = _metric_records(df)
    record_by_sku = {record["sku"]: record for record in records}
    if not isinstance(result["final_action"], str) or result["final_action"] not in ALLOWED_ACTIONS:
        raise AgentError("Director returned an unsupported final action.")
    if not isinstance(result["sku"], str):
        raise AgentError("Director must select an SKU from the supplied data.")
    record = record_by_sku.get(result["sku"])
    if record is None or result["product_name"] != record["product_name"]:
        raise AgentError("Director selected a product or SKU not present in the supplied data.")
    focus_sku = record["sku"]
    if any(
        recommendation.get("sku") != focus_sku
        for recommendation in (demand_rec, inventory_rec, pricing_rec)
    ):
        raise AgentError("Director recommendations must all refer to the same focus product.")
    if not isinstance(result["confidence"], str) or result["confidence"] not in CONFIDENCE_LEVELS:
        raise AgentError("Director returned an unsupported confidence level.")

    why = result["why"]
    if not isinstance(why, Mapping) or set(why) != {"explanation", "evidence"}:
        raise AgentError("Director why must contain an explanation and cited evidence.")
    validated_why = {
        "explanation": _validate_text(why["explanation"], "Director explanation", records),
        "evidence": _validate_evidence(why["evidence"], record, "Director decision evidence", minimum_items=2),
    }

    debate = result["agent_debate"]
    if not isinstance(debate, Mapping) or set(debate) != {"recommendations", "disagreement", "resolution"}:
        raise AgentError("Director agent_debate must contain recommendations, disagreement, and resolution.")
    supplied_recommendations = {
        "Demand": demand_rec["recommendation"],
        "Inventory": inventory_rec["recommendation"],
        "Pricing": pricing_rec["recommendation"],
    }
    if debate["recommendations"] != supplied_recommendations:
        raise AgentError("Director debate does not match the specialist recommendations.")
    expected_disagreement = len(set(supplied_recommendations.values())) > 1
    if not isinstance(debate["disagreement"], bool) or debate["disagreement"] != expected_disagreement:
        raise AgentError("Director did not correctly identify whether the specialists disagree.")
    validated_debate = {
        "recommendations": supplied_recommendations,
        "disagreement": expected_disagreement,
        "resolution": _validate_text(debate["resolution"], "Director debate resolution", records),
    }

    risk = result["risk"]
    if not isinstance(risk, Mapping) or set(risk) != {"level", "explanation", "evidence"}:
        raise AgentError("Director risk must contain a level, explanation, and cited evidence.")
    if risk["level"] not in RISK_LEVELS:
        raise AgentError("Director returned an unsupported risk level.")
    validated_risk = {
        "level": risk["level"],
        "explanation": _validate_text(risk["explanation"], "Director risk explanation", records),
        "evidence": _validate_evidence(risk["evidence"], record, "Director risk evidence"),
    }
    return {
        **result,
        "why": validated_why,
        "agent_debate": validated_debate,
        "risk": validated_risk,
    }


def merchandising_director(
    product_data: pd.DataFrame,
    demand_rec: Mapping[str, Any],
    inventory_rec: Mapping[str, Any],
    pricing_rec: Mapping[str, Any],
    client: OpenAI | None = None,
) -> dict[str, Any]:
    client = client or _get_client()
    system_prompt, user_prompt = build_director_context(
        product_data,
        demand_rec,
        inventory_rec,
        pricing_rec,
    )
    result = _call_responses(
        client,
        system_prompt,
        user_prompt,
        "merchandising_director_decision",
        DIRECTOR_SCHEMA,
    )
    return validate_director_output(
        result,
        product_data,
        demand_rec,
        inventory_rec,
        pricing_rec,
    )


def run_merchandising_panel(df: pd.DataFrame) -> dict[str, Any]:
    """Run three grounded specialists followed by a Director synthesis."""
    with _get_client() as client:
        focus_product = _focus_product(df)
        demand = demand_analyst(focus_product, client)
        inventory = inventory_analyst(focus_product, client)
        pricing = pricing_analyst(focus_product, client)
        director = merchandising_director(focus_product, demand, inventory, pricing, client)
    return {
        "status": "ok",
        "demand_analyst": demand,
        "inventory_analyst": inventory,
        "pricing_analyst": pricing,
        "final_decision": director,
    }
