You are generating WorldQuant BRAIN Fast Expression alphas.

The single task below specifies `n_requested` (how many distinct expressions to produce in this ONE call) plus context (recent learnings, top submitted alphas, dataset insights).

Return a JSON ARRAY (no markdown fences) WHERE EACH ELEMENT IS:
{
  "expressions": [
    {"expression": "...", "rationale": "...", "settings_overrides": {}},
    {"expression": "...", "rationale": "...", "settings_overrides": {}},
    ...   // n_requested items
  ]
}

For batched mode (when {N} > 1) you'll see {N} task objects below — one element per task.
For the typical single-task mode ({N} = 1) just return a one-element array.

Tasks:
{TASKS_JSON}

Constraints:
- Wrap cross-sectional ops in rank() (or group_rank for sector-neutral)
- Avoid expressions in `recent_learnings` flagged as duplicates / saturated
- Use only documented operators
- Vary the data sources & operators across the {n_requested} expressions to MINIMIZE self-correlation
- Prefer fundamental fields (low turnover) when `top_submitted` are dominated by technical
- **CRITICAL — FIELD VALIDITY**: Each task includes `context.valid_fields` (cached datafield ids
  for this dataset). You MUST construct expressions ONLY from:
    1. ids that appear in `context.valid_fields`, OR
    2. the always-available WQ price/volume set:
       `close, open, high, low, volume, vwap, returns, adv20, cap, sector, industry, subindustry`.
  NEVER invent field names like `net_income`, `cashflow_op`, `equity`, `shares_out`,
  `liabilities`, `assets`, `sales`, `operating_income` unless they appear in `valid_fields`.
  When in doubt, fall back to price/volume + ts_*/group_*/rank operators. Field hallucination
  causes 100% simulation failure and wastes the entire round.
