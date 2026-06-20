"""Instrument value-tagging vocabulary (TASK-010, EPIC-02).

Static tag map covering the 19 workbook industry groups and 5 regions.
The only exported function is instrument_tags() — consumed by the tag loader
(TASK-010), fit scorer (TASK-020), and swap engine (TASK-021).

Tag semantics (§11 E5/E6):
  us-tech          — US-domiciled technology companies (Räber exclusion)
  fossil/fossil-fuel — traditional energy sector (Huber exclusion)
  deforestation-risk — materials linked to deforestation (Huber exclusion)
  pharma           — pharmaceutical/healthcare companies (Schneider exclusion)
  neuro-research   — companies with significant CNS/neurology research (Schneider tilt)
  labour-risk      — sectors with documented labour-practice exposure (Ammann exclusion)
  luxury           — premium consumer goods brands (Ammann tilt)
  sustainability   — ESG-aligned instruments (Huber tilt)
"""

INDUSTRY_TAGS: dict[str, list[str]] = {
    "Information Technology":  ["tech"],
    "Communication Services":  ["tech", "media"],
    "Energy":                  ["fossil", "fossil-fuel"],
    "Materials":               ["deforestation-risk", "labour-risk"],
    "Health Care":             ["pharma", "neuro-research"],
    "Consumer Discretionary":  ["luxury", "labour-risk"],
    "Consumer Staples":        ["luxury"],
    "Digital Assets":          ["crypto"],
    "Utilities":               ["sustainability"],
    "Diversified ETF":         ["sustainability", "diversified"],
    "Financials":              [],
    "Government Bonds":        [],
    "Investment Grade":        [],
    "Industrials":             [],
    "Telecommunication":       [],
    "Real Estate (Fund)":      [],
    "Real Estate (REIT)":      [],
    "Precious Metals":         [],
    "Private Markets":         [],
}

# Region-qualified overrides — US-domiciled tech earns the "us-tech" exclusion tag
REGION_EXTRA_TAGS: dict[tuple[str, str], list[str]] = {
    ("Information Technology", "USA"): ["us-tech"],
    ("Communication Services", "USA"): ["us-tech"],
}


def instrument_tags(industry_group: str | None, region: str | None) -> dict:
    """Return the full tag payload for an instrument given its industry group and region.

    Shape: {"sector": str|None, "region": str|None, "value_tags": list[str]}
    Downstream callers use `tags->'value_tags' ? 'fossil'` for exclusion queries.
    """
    base = list(INDUSTRY_TAGS.get(industry_group or "", []))
    extra = list(REGION_EXTRA_TAGS.get((industry_group or "", region or ""), []))
    return {
        "sector": industry_group,
        "region": region,
        "value_tags": base + extra,
    }
