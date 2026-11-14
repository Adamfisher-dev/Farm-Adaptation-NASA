"""Tests for the farm-question rules in pipeline.candidates() (no weather or downloads needed)."""

import pytest

from fieldshift import pipeline as P

CS = ["corn", "soybean"]


def _crops(rot):
    return {c for year in rot.plan for entry in year for c in entry.split("+")}


@pytest.mark.parametrize("want_cover", [True, False])
def test_not_open_never_leaves_fewer_than_three(want_cover):
    cands, removed = P.candidates(open_to_new=False, current_crops=["Corn", "Soybean"],
                                  want_cover=want_cover, existing_rotation=CS)
    assert len(cands) >= P.MIN_COMPARED
    assert cands[0].is_existing
    added = [r for r in cands[1:] if not _crops(r) <= {"corn", "soybean", "cereal_rye", "red_clover"}]
    assert all(any("not looking" in f for f in r.flags) for r in added)      # topped-up ones are flagged
    assert all(r["reason"] for r in removed)


def test_red_clover_is_not_a_new_crop_for_an_oat_grower():
    cands, _ = P.candidates(open_to_new=False, current_crops=["Corn", "Soybean", "Oats"],
                            want_cover=False, hay_buyer=False, existing_rotation=CS)
    assert any(_crops(r) == {"corn", "soybean", "oats", "red_clover"} for r in cands)


def test_hard_constraints_still_remove():
    cands, removed = P.candidates(hay_buyer=False, existing_rotation=CS)
    assert not any("alfalfa" in _crops(r) for r in cands)
    assert any("hay" in r["reason"].lower() for r in removed)
