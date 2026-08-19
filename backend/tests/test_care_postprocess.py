"""Tests for server-side radius enforcement and deduplication."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.models import Facility  # noqa: E402
from care.postprocess import dedupe, finalize  # noqa: E402

# Point Pedro, Sri Lanka — the location from the reported bug.
ORIGIN = (9.8166, 80.2333)


def _facility(id, name, lat, lon, distance_km=None, **extra):
    return Facility(
        id=id,
        name=name,
        kind=extra.pop("kind", "clinic"),
        latitude=lat,
        longitude=lon,
        distance_km=distance_km,
        source="OpenStreetMap",
        **extra,
    )


def test_radius_5km_excludes_everything_farther():
    facilities = [
        _facility("a", "Near Clinic", 9.8180, 80.2340),  # ~0.2 km
        _facility("b", "Mid Clinic", 9.85, 80.25),  # ~4 km
        _facility("c", "Far Hospital", 9.66, 80.02),  # ~29 km
        _facility("d", "Very Far Lab", 9.30, 80.40),  # ~60 km
    ]
    result = finalize(facilities, radius_km=5, latitude=ORIGIN[0], longitude=ORIGIN[1])
    names = [f.name for f in result]
    assert names == ["Near Clinic", "Mid Clinic"]
    assert all(f.distance_km is not None and f.distance_km <= 5 for f in result)


def test_radius_20km_excludes_results_beyond_20km():
    facilities = [
        _facility("a", "Near Clinic", 9.8180, 80.2340),
        _facility("c", "Far Hospital", 9.66, 80.02),  # ~29 km
    ]
    result = finalize(facilities, radius_km=20, latitude=ORIGIN[0], longitude=ORIGIN[1])
    assert [f.name for f in result] == ["Near Clinic"]
    assert all(f.distance_km <= 20 for f in result)


def test_radius_50km_keeps_29km_result():
    facilities = [_facility("c", "Far Hospital", 9.66, 80.02)]
    result = finalize(facilities, radius_km=50, latitude=ORIGIN[0], longitude=ORIGIN[1])
    assert len(result) == 1
    assert result[0].distance_km <= 50


def test_finalize_sorts_by_distance():
    facilities = [
        _facility("far", "B Clinic", 9.85, 80.25),
        _facility("near", "A Clinic", 9.8168, 80.2334),
    ]
    result = finalize(facilities, radius_km=50, latitude=ORIGIN[0], longitude=ORIGIN[1])
    assert [f.id for f in result] == ["near", "far"]


def test_provider_distances_are_recomputed_when_missing():
    facilities = [_facility("a", "Clinic", 9.8180, 80.2340, distance_km=None)]
    result = finalize(facilities, radius_km=5, latitude=ORIGIN[0], longitude=ORIGIN[1])
    assert result[0].distance_km is not None


# -- Deduplication ------------------------------------------------------------


def test_same_source_id_is_deduplicated():
    facilities = [
        _facility("osm:node/1", "Sivasakthi Clinic", 9.8180, 80.2340),
        _facility("osm:node/1", "Sivasakthi Clinic", 9.8180, 80.2340),
    ]
    assert len(dedupe(facilities)) == 1


def test_same_name_at_same_place_is_deduplicated():
    # Same facility mapped twice (node + way) gets two OSM ids.
    facilities = [
        _facility("osm:node/1", "Sivasakthi Clinic", 9.81800, 80.23400),
        _facility("osm:way/2", "Sivasakthi  Clinic", 9.81805, 80.23404),
    ]
    assert len(dedupe(facilities)) == 1


def test_dedupe_keeps_the_richer_listing():
    facilities = [
        _facility("osm:node/1", "CeyMed Lab", 9.8180, 80.2340),
        _facility(
            "osm:way/2",
            "CeyMed Lab",
            9.8180,
            80.2341,
            address="Main St, Point Pedro",
            phone="+94 21 000 0000",
        ),
    ]
    result = dedupe(facilities)
    assert len(result) == 1
    assert result[0].address == "Main St, Point Pedro"


def test_requested_kind_is_enforced_server_side():
    facilities = [
        _facility("a", "Base Hospital", 9.8180, 80.2340, kind="hospital"),
        _facility("b", "CeyMed Lab", 9.8181, 80.2341, kind="laboratory"),
        _facility("c", "Town Clinic", 9.8182, 80.2342, kind="clinic"),
    ]
    result = finalize(
        facilities, radius_km=5, latitude=ORIGIN[0], longitude=ORIGIN[1], kind="hospital"
    )
    assert [f.name for f in result] == ["Base Hospital"]
    # "any" keeps every category, including Other.
    result_any = finalize(
        facilities, radius_km=5, latitude=ORIGIN[0], longitude=ORIGIN[1], kind="any"
    )
    assert len(result_any) == 3


def test_lab_alias_is_enforced_as_laboratory():
    facilities = [
        _facility("a", "CeyMed Lab", 9.8181, 80.2341, kind="laboratory"),
        _facility("b", "Town Clinic", 9.8182, 80.2342, kind="clinic"),
    ]
    result = finalize(facilities, radius_km=5, latitude=ORIGIN[0], longitude=ORIGIN[1], kind="lab")
    assert [f.kind for f in result] == ["laboratory"]


def test_same_name_far_apart_is_kept_as_two_facilities():
    # Two genuinely different places legitimately sharing a name.
    facilities = [
        _facility("osm:node/1", "Appollo Clinic", 9.8180, 80.2340),
        _facility("osm:node/2", "Appollo Clinic", 9.6600, 80.0200),
    ]
    assert len(dedupe(facilities)) == 2


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
