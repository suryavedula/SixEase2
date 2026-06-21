"""Unit tests for backend/app/loaders/simulate_client.py (TASK-064).

The repo's test harness mocks the DB (see test_tasks.py) rather than running a real
Postgres, so the full seed→DNA→baseline→personalised path is exercised manually via
POST /admin/seed/simulate-client (and live_smoke for the LLM). These tests cover the
genuinely new, pure logic: the canned onboarding data is well-formed, and the
weight-neutrality assertion (the mandate-neutral proof) catches a slot that drifts.
"""

from app.loaders.dna import VALID_TAGS
from app.loaders.simulate_client import _SIM_CLIENT, find_weight_neutrality_violations
from app.models.enums import Mandate


# ---------------------------------------------------------------------------
# Canned onboarding data — well-formedness
# ---------------------------------------------------------------------------


def test_sim_client_has_simulated_prefix():
    # Namespacing keeps it from colliding with personas / Sample / [SYNTHETIC] clients.
    assert _SIM_CLIENT["name"].startswith("[SIMULATED]")


def test_sim_client_mandate_is_valid():
    assert isinstance(_SIM_CLIENT["mandate"], Mandate)


def test_sim_client_notes_present_and_nonempty():
    notes = _SIM_CLIENT["notes"]
    assert len(notes) >= 1
    for note in notes:
        assert note["note"].strip(), "every canned note must carry source text for DNA"
        assert note["date"] is not None
        assert note["medium"]


def test_sim_client_notes_chronological():
    dates = [n["date"] for n in _SIM_CLIENT["notes"]]
    assert dates == sorted(dates), "notes should read as a chronological narrative"


def test_sim_client_notes_express_a_known_tag_theme():
    # The demo only lands if the notes describe an exclusion/tilt the engine can act on.
    # We don't assert the LLM output, just that the narrative names a real vocabulary
    # theme (fossil fuels / sustainability) the Sample Balanced book triggers.
    blob = " ".join(n["note"].lower() for n in _SIM_CLIENT["notes"])
    assert "fossil" in blob or "oil" in blob or "coal" in blob
    assert "sustainab" in blob or "clean" in blob or "renewable" in blob
    # The themes map onto the shared tag vocabulary used by fit/swap.
    assert {"fossil", "fossil-fuel", "sustainability"} & VALID_TAGS


# ---------------------------------------------------------------------------
# find_weight_neutrality_violations — pure mandate-neutral proof
# ---------------------------------------------------------------------------


def test_no_violations_when_slots_match():
    pairs = [
        ("Equities", "Energy", "Equities", "Energy"),
        ("Equities", "Health Care", "Equities", "Health Care"),
    ]
    assert find_weight_neutrality_violations(pairs) == []


def test_empty_pairs_is_neutral():
    assert find_weight_neutrality_violations([]) == []


def test_sub_asset_class_change_is_flagged():
    pairs = [("Equities", "Energy", "Domestic Bonds (CHF)", "Energy")]
    violations = find_weight_neutrality_violations(pairs)
    assert len(violations) == 1
    assert violations[0]["candidate_sub_asset_class"] == "Domestic Bonds (CHF)"


def test_industry_group_change_is_flagged():
    pairs = [("Equities", "Energy", "Equities", "Information Technology")]
    violations = find_weight_neutrality_violations(pairs)
    assert len(violations) == 1
    assert violations[0]["holding_industry_group"] == "Energy"


def test_only_offending_pairs_returned():
    pairs = [
        ("Equities", "Energy", "Equities", "Energy"),           # ok
        ("Equities", "Energy", "Equities", "Materials"),         # bad
        ("Equities", "Health Care", "Equities", "Health Care"),  # ok
    ]
    violations = find_weight_neutrality_violations(pairs)
    assert len(violations) == 1
    assert violations[0]["candidate_industry_group"] == "Materials"
