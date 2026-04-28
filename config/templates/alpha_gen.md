# Alpha Generation Context Template
# 用于Alpha生成的上下文模板

## System Role
{system_role}

## Current Session Info
- Dataset: {dataset_tag}
- Date: {current_date}
- Daily Target: {daily_target_submissions} submissions
- Remaining Budget: {remaining_budget}

## Knowledge Base Stats
```
Total Tested: {kb_stats.total_simulated}
Passed IS: {kb_stats.checks_passed}
Submitted: {kb_stats.submitted}
Pass Rate: {kb_stats.pass_rate}
```

## Best Performing Categories (Top 5)
{best_categories_table}

## Categories to Avoid (Saturated)
Data sources with ≥3 submitted alphas (high self-correlation risk):
{saturated_sources_list}

## Recent Learnings
{recent_learnings_list}

## Top Passing Alphas (for reference)
{top_passing_alphas_table}

## Failure Patterns & Mutation Hints
{failure_patterns_section}

## Dataset Settings
```
{dataset_settings_section}
```

## Instructions
{generation_instructions}

## Output Format
Please generate {batch_size} alpha candidates in JSON format:
```json
[
  {
    "name": "Alpha_Name",
    "expr": "rank(...)",
    "settings": {"decay": 0, "neutralization": "SUBINDUSTRY", ...},
    "category": "category_name",
    "hypothesis": "Why this should work"
  }
]
```