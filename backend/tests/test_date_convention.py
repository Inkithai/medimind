"""Regression tests: one record, one day/month convention, everywhere.

The extraction layer produces ambiguous slash dates ("03/11/2025"). The
risk-window engine inferred the record's convention (day-first when nothing
disambiguates) while the timeline merge, lab trends, change detection and
record integrity each used dateutil's month-first default — so the same
string was read as 11 March by one feature and 3 November by another, ON THE
SAME RECORD. That flips chronological order ("10/12/2025" < "12/11/2025" in
one reading) and can invert a lab trend's direction.

date_convention.py is now the single parser for every module; these tests
pin the agreement.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# medical_extractor refuses to import without a provider key.
os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

from change_detection import _date as change_detection_date
from date_convention import infer_dayfirst, parse_mixed_date, parse_mixed_datetime
from lab_trends import _parse_date as lab_trends_date
from medical_extractor import _parse_timeline_date
from record_integrity import _canonical_date
from risk_timeline import parse_date as risk_timeline_date


def test_all_modules_read_an_ambiguous_slash_date_identically():
    # Day-first reading (the record default): 3 November 2025.
    assert lab_trends_date("03/11/2025").date().isoformat() == "2025-11-03"
    assert change_detection_date("03/11/2025").date().isoformat() == "2025-11-03"
    assert _parse_timeline_date("03/11/2025").date().isoformat() == "2025-11-03"
    assert risk_timeline_date("03/11/2025").isoformat() == "2025-11-03"
    assert _canonical_date("03/11/2025") == "2025-11-03"


def test_a_month_first_marker_in_the_record_flips_everything_together():
    # "10/14/2023" can only be month-first: the whole record must follow.
    dayfirst = infer_dayfirst(["11/03/2025", "10/14/2023"])
    assert dayfirst is False
    assert parse_mixed_date("11/03/2025", dayfirst=dayfirst).isoformat() == "2025-11-03"
    assert lab_trends_date("11/03/2025", dayfirst=dayfirst).date().isoformat() == "2025-11-03"


def test_iso_dates_are_never_dayfirst_mangled_anywhere():
    for parse in (lab_trends_date, change_detection_date, _parse_timeline_date):
        assert parse("2025-11-09").date().isoformat() == "2025-11-09"
    assert risk_timeline_date("2025-11-09").isoformat() == "2025-11-09"
    assert parse_mixed_date("2025-11-09").isoformat() == "2025-11-09"
    # With an ISO marker present, slash dates in the same record still get
    # the (default day-first) record convention.
    dayfirst = infer_dayfirst(["2025-11-09", "03/11/2025"])
    assert lab_trends_date("03/11/2025", dayfirst=dayfirst).date().isoformat() == "2025-11-03"


def test_unparseable_stays_none_instead_of_being_invented():
    assert parse_mixed_datetime("not a date") is None
    assert parse_mixed_date(None) is None
    assert parse_mixed_date("") is None


def test_iso_timestamps_keep_their_time_component():
    parsed = parse_mixed_datetime("2026-01-05 13:40")
    assert (parsed.hour, parsed.minute) == (13, 40)
    assert parse_mixed_datetime("2026-01-05T13:40:00").date().isoformat() == "2026-01-05"


def test_trend_direction_agrees_with_treatment_windows():
    # The flip case: 12/11/2025 (12 Nov, low) -> 10/12/2025 (10 Dec, high).
    # month-first parsers used to order these Dec 11 then Oct 12 — a
    # DECREASING trend from the same numbers.
    from lab_trends import track_lab_trends
    from medical_extractor import build_patient_timeline
    from risk_timeline import build_treatment_windows

    docs = [
        {
            "date": "12/11/2025",
            "document_type": "lab_report",
            "allergies_noted": [],
            "lab_results": [
                {
                    "test_name": "Hb",
                    "value": "10",
                    "unit": "g/dL",
                    "flag": "low",
                    "reference_range": "12-15",
                }
            ],
            "medications": [
                {
                    "name": "DrugA",
                    "ingredients": ["druga"],
                    "dosage_value": 10,
                    "dosage_unit": "mg",
                    "frequency_per_day": 1,
                    "duration": "14 days",
                }
            ],
            "_source": {"file": "nov.pdf"},
        },
        {
            "date": "10/12/2025",
            "document_type": "lab_report",
            "allergies_noted": [],
            "lab_results": [
                {
                    "test_name": "Hb",
                    "value": "20",
                    "unit": "g/dL",
                    "flag": "high",
                    "reference_range": "12-15",
                }
            ],
            "medications": [
                {
                    "name": "DrugB",
                    "ingredients": ["drugb"],
                    "dosage_value": 10,
                    "dosage_unit": "mg",
                    "frequency_per_day": 1,
                    "duration": "14 days",
                }
            ],
            "_source": {"file": "dec.pdf"},
        },
    ]
    timeline = build_patient_timeline(docs)
    assert [v["date"] for v in timeline["visits"]] == ["12/11/2025", "10/12/2025"]

    trend = track_lab_trends(timeline)["trends"][0]
    assert trend["direction"] == "increasing"
    assert trend["flag_sequence"] == "low → high"

    windows = build_treatment_windows(timeline)
    assert [str(w["start"]) for w in windows] == ["2025-11-12", "2025-12-10"]

    # Change detection must compare the same consecutive pair.
    from change_detection import detect_record_changes

    latest = detect_record_changes(timeline)["latest"]
    assert latest["from_date"] == "12/11/2025"
    assert latest["to_date"] == "10/12/2025"


def test_same_date_grouping_uses_the_same_reading():
    # Two documents both dated "03/11/2025" (3 Nov, day-first) must group
    # together for same-date discrepancy checks.
    from record_integrity import check_record_integrity

    timeline = {
        "visits": [
            {
                "date": "03/11/2025",
                "patient_name": "John",
                "lab_results": [{"test_name": "Hb", "value": "10", "unit": "g/dL"}],
                "medications": [],
                "allergies_noted": [],
            },
            {
                "date": "03/11/2025",
                "patient_name": "John",
                "lab_results": [{"test_name": "Hb", "value": "14", "unit": "g/dL"}],
                "medications": [],
                "allergies_noted": [],
            },
        ]
    }
    report = check_record_integrity(timeline)
    assert any("Same-date Hb" in issue["title"] for issue in report["issues"])
