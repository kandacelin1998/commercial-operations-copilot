# Merchandising Decision Lab

[🚀 Live Demo](https://commercial-operations-copilot-26htkka7p9vmycaahbj3xm.streamlit.app/)

Merchandising Decision Lab — an AI commercial decision system for fashion merchandising.ing.

## Problem

Fashion teams have dashboards and spreadsheets, but still need to decide what to reorder, markdown, keep at full price, monitor, or investigate. This prototype turns product-level commercial data into a structured decision and rationale.

## Architecture

```text
Data
  ↓
Deterministic commercial metrics
  ↓
Demand Analyst
Inventory Analyst
Pricing Analyst
  ↓
Merchandising Director
  ↓
Commercial Decision
```

Pandas calculates the commercial metrics and deterministic rules handle measurable thresholds and actions. Keeping these calculations separate from LLM reasoning makes numeric evidence and rule-based outcomes reproducible; model reasoning can focus on interpreting evidence and articulating trade-offs rather than recomputing metrics.

The Demand, Inventory, and Pricing specialists evaluate the same metrics from different commercial perspectives. The Merchandising Director compares their recommendations, resolves conflicts against the commercial evidence, and presents a final decision with its rationale, confidence, and risk.

## Collection Simulator

The simulator evaluates a proposed collection against a budget and target gross margin. Changing the budget affects whether investment must be cut; changing the target margin affects which products need repricing. Recommendations and their rationale update with these inputs.

## Technology

- Python
- Pandas for commercial data and metrics
- Streamlit for the interactive application
- OpenAI Responses API for the model integration

The included fashion product and proposed collection data are synthetic. This is a technical prototype for demonstrating multi-agent orchestration, not a production system.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Set the API key and model used by the OpenAI integration:

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="your-model-name"
```

Run the application:

```bash
streamlit run app.py
```

## What I learned

The main design lesson was to keep financial calculations outside the LLM. Deterministic metrics provide a stable, reproducible evidence layer, while agents interpret that evidence and reason about commercial trade-offs.

Specialist agents are more useful when they have distinct objectives rather than being prompted to produce the same generic recommendation. Demand, Inventory, and Pricing can therefore disagree meaningfully, while the Merchandising Director resolves their trade-offs.

## Technical takeaway

The interesting part is not asking an LLM to produce a recommendation. It is separating deterministic commercial logic from probabilistic reasoning, giving specialist agents competing objectives, and using a Director agent to resolve the trade-offs.
