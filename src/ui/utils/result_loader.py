"""
result_loader.py — Load and flatten all alpha results from results/ directory.

Cache strategy: keyed by MD5 of all file names + sizes, so adding a new result
file or changing an existing one automatically invalidates the cache.
"""
import hashlib
import json
import pandas as pd
import streamlit as st
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent.parent.parent / "results"


def _results_cache_key() -> str:
    """Hash of all result file names + file sizes. Changes whenever files are added/modified."""
    parts = sorted(
        f"{p.name}:{p.stat().st_size}"
        for p in RESULTS_DIR.glob("*.json")
    )
    return hashlib.md5("|".join(parts).encode()).hexdigest()


@st.cache_data
def _load_results_cached(cache_key: str) -> pd.DataFrame:  # noqa: ARG001
    """Inner cached loader. cache_key forces re-execution when files change."""
    records = []
    for fpath in sorted(RESULTS_DIR.glob("*.json")):
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    record = _parse_record(item, fpath.name)
                    if record:
                        records.append(record)
        except Exception:
            pass
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records).drop_duplicates(subset=["alpha_id"])
    df = df[df["sharpe"].notna() & df["fitness"].notna()]
    return df.reset_index(drop=True)


def load_all_results() -> pd.DataFrame:
    """Load all JSON result files, auto-refreshing when new files are added."""
    return _load_results_cached(_results_cache_key())



def _parse_record(item: dict, source_file: str) -> dict | None:
    alpha = item.get("alpha", {})
    if not alpha or not isinstance(alpha, dict):
        return None
    is_data = alpha.get("is")
    if not is_data:
        return None

    checks = {}
    for c in is_data.get("checks", []):
        checks[c["name"]] = c.get("result", "PENDING")

    # All required checks must PASS (ignore PENDING for SELF_CORRELATION)
    all_pass = all(
        v == "PASS"
        for k, v in checks.items()
        if v != "PENDING"
    )

    alpha_settings = alpha.get("settings", {})
    item_settings = item.get("settings", {})

    def get_setting(key):
        if key in item_settings:
            return item_settings[key]
        return alpha_settings.get(key, "")

    return {
        "name": item.get("name", ""),
        "expr": item.get("expr") or alpha.get("regular", {}).get("code", ""),
        "category": item.get("category", ""),
        "hypothesis": item.get("hypothesis", ""),
        "alpha_id": alpha.get("id", ""),
        "sharpe": is_data.get("sharpe"),
        "fitness": is_data.get("fitness"),
        "turnover": is_data.get("turnover"),
        "returns": is_data.get("returns"),
        "drawdown": is_data.get("drawdown"),
        "margin": is_data.get("margin"),
        "long_count": is_data.get("longCount"),
        "short_count": is_data.get("shortCount"),
        "pnl": is_data.get("pnl"),
        "all_pass": all_pass,
        "checks_json": json.dumps(checks),
        "neutralization": get_setting("neutralization"),
        "decay": get_setting("decay"),
        "truncation": get_setting("truncation"),
        "universe": get_setting("universe") or "TOP3000",
        "source_file": source_file,
    }
