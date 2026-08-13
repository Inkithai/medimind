"""
Find Care — specialty suggestion + clinic directory
===================================================
Turns a patient's extracted timeline into a suggested medical specialty,
then searches real healthcare facilities near a city the user types.

Stack (no paid Google billing):

  1. Geoapify  — geocoding + Places  (if GEOAPIFY_API_KEY is set)
  2. OpenStreetMap — Nominatim + Overpass  (automatic fallback, no key)

Leaflet still draws the map with OSM tiles either way. The UI names the
directory that actually produced the list — never "X failed, so Y".

This is a public directory lookup, not a referral, booking system, or diagnosis.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("care_finder")

NOMINATIM_URL = os.environ.get(
    "NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"
).rstrip("/")
OVERPASS_URL = os.environ.get(
    "OVERPASS_URL", "https://overpass-api.de/api/interpreter"
).rstrip("/")
OSM_USER_AGENT = os.environ.get(
    "OSM_USER_AGENT",
    "MediMind/1.0 (healthcare record assistant; https://github.com/Inkithai/medimind)",
)
GEOAPIFY_GEOCODE_URL = os.environ.get(
    "GEOAPIFY_GEOCODE_URL", "https://api.geoapify.com/v1/geocode/search"
).rstrip("/")
GEOAPIFY_PLACES_URL = os.environ.get(
    "GEOAPIFY_PLACES_URL", "https://api.geoapify.com/v2/places"
).rstrip("/")
_PLACEHOLDER_KEY = re.compile(r"^(your[-_].+|change.?me|xxx+|placeholder.*|todo.*)$", re.I)

DEFAULT_RADIUS_M = 8000
MAX_RADIUS_M = 50000
HTTP_TIMEOUT_SECONDS = 20

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_INDEX = {name: i for i, name in enumerate(DAYS)}
OSM_DAY = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}

TIME_WINDOWS = {
    "morning": (6 * 60, 12 * 60),
    "afternoon": (12 * 60, 17 * 60),
    "evening": (17 * 60, 21 * 60),
    "any": (0, 24 * 60),
}

DISCLAIMER = (
    "This is a public directory lookup, not a medical referral and not a "
    "diagnosis. Listings may be incomplete or out of date. Always confirm "
    "details with the clinic and consult a licensed clinician before acting "
    "on anything in your records."
)

SOURCE_GEOAPIFY = {
    "name": "Geoapify",
    "geocoder": "Geoapify Geocoding",
    "directory": "Geoapify Places API",
    "license": "Geoapify Terms",
    "attribution": "© Geoapify",
    "url": "https://www.geoapify.com/",
}

SOURCE_OSM = {
    "name": "OpenStreetMap",
    "geocoder": "Nominatim",
    "directory": "Overpass API",
    "license": "ODbL",
    "attribution": "© OpenStreetMap contributors",
    "url": "https://www.openstreetmap.org/copyright",
}

# Backward-compatible alias — injected OSM tests and older callers.
SOURCE = SOURCE_OSM

# Geoapify healthcare categories per specialty. Always include the parent
# clinic + hospital so a sparse specialty still returns nearby care.
GEOAPIFY_CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "general_practice": (
        "healthcare.clinic_or_praxis.general",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "endocrinology": (
        "healthcare.clinic_or_praxis.endocrinology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "cardiology": (
        "healthcare.clinic_or_praxis.cardiology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "pulmonology": (
        "healthcare.clinic_or_praxis.pulmonology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "gastroenterology": (
        "healthcare.clinic_or_praxis.gastroenterology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "nephrology": ("healthcare.clinic_or_praxis", "healthcare.hospital"),
    "neurology": ("healthcare.clinic_or_praxis", "healthcare.hospital"),
    "psychiatry": (
        "healthcare.clinic_or_praxis.psychiatry",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "dermatology": (
        "healthcare.clinic_or_praxis.dermatology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "rheumatology": (
        "healthcare.clinic_or_praxis.rheumatology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "orthopedics": (
        "healthcare.clinic_or_praxis.orthopaedics",
        "healthcare.clinic_or_praxis.trauma",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "allergy_immunology": (
        "healthcare.clinic_or_praxis.allergology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "ophthalmology": (
        "healthcare.clinic_or_praxis.ophthalmology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "otolaryngology": (
        "healthcare.clinic_or_praxis.otolaryngology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "urology": (
        "healthcare.clinic_or_praxis.urology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "gynecology": (
        "healthcare.clinic_or_praxis.gynaecology",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "oncology": ("healthcare.hospital", "healthcare.clinic_or_praxis"),
    "pediatrics": (
        "healthcare.clinic_or_praxis.paediatrics",
        "healthcare.clinic_or_praxis",
        "healthcare.hospital",
    ),
    "infectious_disease": ("healthcare.hospital", "healthcare.clinic_or_praxis"),
}


class CareFinderError(RuntimeError):
    """Base error for the find-care pipeline."""

    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class CityNotFoundError(CareFinderError):
    def __init__(self, city: str) -> None:
        super().__init__(
            f"We couldn't find “{city}” on the map. Try a city name, neighbourhood, or postcode.",
            code="city_not_found",
            retryable=False,
        )


class DirectoryUnavailableError(CareFinderError):
    def __init__(self, detail: str = "The map directory is temporarily unavailable.") -> None:
        super().__init__(detail, code="directory_unavailable", retryable=True)


def geoapify_key() -> Optional[str]:
    """Return a real Geoapify key, or None for missing / placeholder values."""
    raw = (os.environ.get("GEOAPIFY_API_KEY") or "").strip()
    if not raw or _PLACEHOLDER_KEY.match(raw) or raw.lower().startswith("your-"):
        return None
    return raw


def geoapify_configured() -> bool:
    return bool(geoapify_key())


# ---------------------------------------------------------------------------
# Specialty catalogue — deterministic, explainable, no extra LLM call
# ---------------------------------------------------------------------------

SPECIALTIES: Dict[str, Dict[str, Any]] = {
    "general_practice": {
        "label": "General practice",
        "osm": ("general", "general_practice", "family", "internal", "gp"),
        "keywords": ("family medicine", "general practitioner", "primary care"),
        "medications": (),
        "labs": (),
    },
    "endocrinology": {
        "label": "Endocrinology / diabetes",
        "osm": ("endocrinology", "diabetes", "diabetology"),
        "keywords": ("diabetes", "thyroid", "insulin", "hba1c"),
        "medications": (
            "metformin", "insulin", "glipizide", "gliclazide", "glimepiride",
            "sitagliptin", "empagliflozin", "dapagliflozin", "liraglutide",
            "semaglutide", "levothyroxine", "carbimazole",
        ),
        "labs": ("hba1c", "glucose", "fasting glucose", "tsh", "free t4", "free t3"),
    },
    "cardiology": {
        "label": "Cardiology",
        "osm": ("cardiology", "cardiac"),
        "keywords": ("heart", "cardiac", "hypertension", "blood pressure", "cholesterol"),
        "medications": (
            "amlodipine", "lisinopril", "enalapril", "ramipril", "losartan",
            "atenolol", "metoprolol", "bisoprolol", "atorvastatin", "rosuvastatin",
            "simvastatin", "clopidogrel", "aspirin", "warfarin", "apixaban",
            "furosemide", "spironolactone",
        ),
        "labs": ("ldl", "hdl", "cholesterol", "triglyceride", "troponin", "bnp", "nt-probnp"),
    },
    "pulmonology": {
        "label": "Pulmonology / chest",
        "osm": ("pulmonology", "respiratory", "chest"),
        "keywords": ("asthma", "copd", "inhaler", "wheeze"),
        "medications": (
            "salbutamol", "albuterol", "budesonide", "fluticasone", "montelukast",
            "tiotropium", "formoterol", "ipratropium",
        ),
        "labs": ("spo2", "oxygen saturation"),
    },
    "gastroenterology": {
        "label": "Gastroenterology / liver",
        "osm": ("gastroenterology", "hepatology"),
        "keywords": ("liver", "hepatitis", "stomach", "reflux", "ulcer"),
        "medications": ("omeprazole", "pantoprazole", "esomeprazole", "ranitidine", "mesalazine"),
        "labs": ("alt", "ast", "alp", "bilirubin", "ggt", "hepatitis"),
    },
    "nephrology": {
        "label": "Nephrology / kidney",
        "osm": ("nephrology", "renal"),
        "keywords": ("kidney", "renal", "dialysis"),
        "medications": (),
        "labs": ("creatinine", "egfr", "urea", "bun", "potassium"),
    },
    "neurology": {
        "label": "Neurology",
        "osm": ("neurology",),
        "keywords": ("seizure", "migraine", "stroke", "neuropathy", "parkinson"),
        "medications": ("levetiracetam", "valproate", "carbamazepine", "gabapentin", "pregabalin", "sumatriptan"),
        "labs": (),
    },
    "psychiatry": {
        "label": "Psychiatry / mental health",
        "osm": ("psychiatry", "mental_health"),
        "keywords": ("depression", "anxiety", "psychiatric"),
        "medications": (
            "sertraline", "fluoxetine", "escitalopram", "citalopram", "venlafaxine",
            "amitriptyline", "mirtazapine", "olanzapine", "quetiapine", "risperidone",
        ),
        "labs": (),
    },
    "dermatology": {
        "label": "Dermatology",
        "osm": ("dermatology",),
        "keywords": ("rash", "eczema", "psoriasis", "skin"),
        "medications": ("hydrocortisone", "betamethasone", "clotrimazole", "isotretinoin"),
        "labs": (),
    },
    "rheumatology": {
        "label": "Rheumatology / joints",
        "osm": ("rheumatology",),
        "keywords": ("arthritis", "joint", "rheumatoid", "gout"),
        "medications": ("methotrexate", "allopurinol", "hydroxychloroquine", "sulfasalazine"),
        "labs": ("esr", "crp", "rheumatoid factor", "anti-ccp", "uric acid"),
    },
    "orthopedics": {
        "label": "Orthopedics",
        "osm": ("orthopaedics", "orthopedics", "trauma"),
        "keywords": ("fracture", "orthopedic", "bone", "knee", "hip"),
        "medications": (),
        "labs": (),
    },
    "allergy_immunology": {
        "label": "Allergy / immunology",
        "osm": ("allergology", "allergy", "immunology"),
        "keywords": ("allergy", "anaphylaxis", "allergic"),
        "medications": ("cetirizine", "loratadine", "fexofenadine", "epinephrine", "adrenaline"),
        "labs": ("ige",),
    },
    "ophthalmology": {
        "label": "Ophthalmology / eyes",
        "osm": ("ophthalmology",),
        "keywords": ("eye", "vision", "cataract", "glaucoma"),
        "medications": ("latanoprost", "timolol"),
        "labs": (),
    },
    "otolaryngology": {
        "label": "ENT",
        "osm": ("otolaryngology", "ent"),
        "keywords": ("ear", "sinus", "throat", "tonsil"),
        "medications": (),
        "labs": (),
    },
    "urology": {
        "label": "Urology",
        "osm": ("urology",),
        "keywords": ("prostate", "urinary", "kidney stone"),
        "medications": ("tamsulosin", "finasteride"),
        "labs": ("psa",),
    },
    "gynecology": {
        "label": "Gynecology / obstetrics",
        "osm": ("gynaecology", "gynecology", "obstetrics"),
        "keywords": ("pregnancy", "obstetric", "gynecol", "antenatal"),
        "medications": (),
        "labs": ("hcg", "beta-hcg"),
    },
    "oncology": {
        "label": "Oncology",
        "osm": ("oncology",),
        "keywords": ("cancer", "chemotherapy", "tumour", "tumor", "oncolog"),
        "medications": ("tamoxifen", "imatinib"),
        "labs": (),
    },
    "pediatrics": {
        "label": "Pediatrics",
        "osm": ("paediatrics", "pediatrics"),
        "keywords": ("child", "pediatric", "paediatric", "infant"),
        "medications": (),
        "labs": (),
    },
    "infectious_disease": {
        "label": "Infectious disease",
        "osm": ("infectious_diseases", "infectiology"),
        "keywords": ("infection", "hiv", "tuberculosis", "malaria"),
        "medications": ("rifampicin", "isoniazid", "efavirenz", "dolutegravir"),
        "labs": ("hiv", "cd4", "viral load"),
    },
}


def list_specialties() -> List[Dict[str, str]]:
    return [{"id": key, "label": spec["label"]} for key, spec in SPECIALTIES.items()]


def _blob(value: Any) -> str:
    return str(value or "").strip().lower()


def suggest_specialties(timeline: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Score specialties from medications, labs, allergies, and notes.

    Always includes general practice as a safe default. Reasons cite the
    actual record fields so the UI can show *why* a specialty was picked.
    """
    scores: Dict[str, Dict[str, Any]] = {
        key: {"id": key, "label": spec["label"], "score": 0, "reasons": []}
        for key, spec in SPECIALTIES.items()
    }

    if not timeline:
        scores["general_practice"]["score"] = 1
        scores["general_practice"]["reasons"].append(
            "No records uploaded yet — general practice is a safe starting point."
        )
        return _pack_suggestion(scores, has_records=False)

    meds = timeline.get("medications_timeline") or []
    labs = timeline.get("lab_results_timeline") or []
    allergies = timeline.get("known_allergies") or []
    visits = timeline.get("visits") or []

    for med in meds:
        hay = " ".join([_blob(med.get("name")), " ".join(_blob(i) for i in (med.get("ingredients") or []))])
        for key, spec in SPECIALTIES.items():
            for token in spec["medications"]:
                if token and token in hay:
                    scores[key]["score"] += 3
                    label = med.get("name") or token
                    reason = f"Medicine on your record: {label}"
                    if reason not in scores[key]["reasons"]:
                        scores[key]["reasons"].append(reason)

    for lab in labs:
        name = _blob(lab.get("test_name"))
        flag = _blob(lab.get("flag"))
        for key, spec in SPECIALTIES.items():
            for token in spec["labs"]:
                if token and token in name:
                    bump = 4 if flag in {"high", "low"} else 2
                    scores[key]["score"] += bump
                    shown = lab.get("test_name") or token
                    extra = f" ({flag})" if flag in {"high", "low"} else ""
                    reason = f"Lab result: {shown}{extra}"
                    if reason not in scores[key]["reasons"]:
                        scores[key]["reasons"].append(reason)

    if allergies:
        scores["allergy_immunology"]["score"] += 3 * len(allergies)
        scores["allergy_immunology"]["reasons"].append(
            "Documented allerg" + ("ies" if len(allergies) != 1 else "y") + ": " + ", ".join(str(a) for a in allergies[:4])
        )

    notes = " ".join(_blob(v.get("clinical_notes")) for v in visits)
    for key, spec in SPECIALTIES.items():
        for token in spec["keywords"]:
            if token and token in notes:
                scores[key]["score"] += 2
                reason = f"Mentioned in clinical notes: “{token}”"
                if reason not in scores[key]["reasons"]:
                    scores[key]["reasons"].append(reason)

    # Always keep GP available; give it a floor so an empty-ish record still works.
    if scores["general_practice"]["score"] == 0:
        scores["general_practice"]["score"] = 1
        scores["general_practice"]["reasons"].append(
            "General practice can review your full record and refer if needed."
        )

    return _pack_suggestion(scores, has_records=True)


def _pack_suggestion(scores: Dict[str, Dict[str, Any]], *, has_records: bool) -> Dict[str, Any]:
    ranked = sorted(
        (item for item in scores.values() if item["score"] > 0),
        key=lambda item: (-item["score"], item["label"]),
    )
    primary = ranked[0] if ranked else scores["general_practice"]
    return {
        "suggested": {
            "id": primary["id"],
            "label": primary["label"],
            "reasons": primary["reasons"][:4],
        },
        "alternatives": [
            {"id": item["id"], "label": item["label"], "reasons": item["reasons"][:3]}
            for item in ranked[1:5]
        ],
        "all": list_specialties(),
        "has_records": has_records,
    }


# ---------------------------------------------------------------------------
# Opening-hours / availability
# ---------------------------------------------------------------------------

def _minutes(hhmm: str) -> Optional[int]:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 24 or minute > 59:
        return None
    return hour * 60 + minute


def _expand_days(token: str) -> List[int]:
    token = token.strip().lower()
    if not token:
        return []
    if "-" in token:
        left, right = token.split("-", 1)
        if left in OSM_DAY and right in OSM_DAY:
            start, end = OSM_DAY[left], OSM_DAY[right]
            if start <= end:
                return list(range(start, end + 1))
            return list(range(start, 7)) + list(range(0, end + 1))
    if token in OSM_DAY:
        return [OSM_DAY[token]]
    return []


def parse_opening_intervals(opening_hours: Optional[str]) -> Optional[Dict[int, List[Tuple[int, int]]]]:
    """Best-effort OSM opening_hours → {weekday: [(start_min, end_min), ...]}.

    Returns None when the string is missing or too exotic to trust.
    """
    if not opening_hours or not isinstance(opening_hours, str):
        return None
    text = opening_hours.strip()
    if not text:
        return None
    if text.lower() in {"24/7", "24 hours", "open 24/7"}:
        return {i: [(0, 24 * 60)] for i in range(7)}

    intervals: Dict[int, List[Tuple[int, int]]] = {i: [] for i in range(7)}
    understood = False
    for raw_rule in text.split(";"):
        rule = raw_rule.strip()
        if not rule or rule.lower() in {"off", "closed"}:
            continue
        if rule.lower() == "24/7":
            for i in range(7):
                intervals[i] = [(0, 24 * 60)]
            understood = True
            continue
        match = re.match(
            r"^([A-Za-z][a-z]?(?:-[A-Za-z][a-z]?)?(?:,[A-Za-z][a-z]?(?:-[A-Za-z][a-z]?)?)*)\s+(.+)$",
            rule,
        )
        if not match:
            continue
        day_part, hours_part = match.group(1), match.group(2)
        days: List[int] = []
        for piece in day_part.split(","):
            days.extend(_expand_days(piece))
        if not days:
            continue
        if hours_part.strip().lower() in {"off", "closed"}:
            understood = True
            continue
        for span in hours_part.split(","):
            span = span.strip()
            if "-" not in span:
                continue
            start_s, end_s = span.split("-", 1)
            start, end = _minutes(start_s), _minutes(end_s)
            if start is None or end is None:
                continue
            if end == 0:
                end = 24 * 60
            understood = True
            for day in days:
                intervals[day].append((start, end))
    if not understood:
        return None
    return intervals


def availability_status(
    opening_hours: Optional[str],
    days: Sequence[str],
    time_of_day: str,
) -> str:
    """Return 'open', 'closed', or 'unknown' for the requested window."""
    window = TIME_WINDOWS.get((time_of_day or "any").lower(), TIME_WINDOWS["any"])
    wanted_days = [DAY_INDEX[d] for d in days if d in DAY_INDEX]
    if not wanted_days:
        wanted_days = list(range(5))  # weekdays
    parsed = parse_opening_intervals(opening_hours)
    if parsed is None:
        return "unknown"

    win_start, win_end = window
    matched = False
    for day in wanted_days:
        for start, end in parsed.get(day, []):
            if start < win_end and end > win_start:
                matched = True
                break
        if matched:
            break
    return "open" if matched else "closed"


# ---------------------------------------------------------------------------
# HTTP + Nominatim + Overpass
# ---------------------------------------------------------------------------

def _request_json(
    url: str,
    *,
    data: Optional[bytes] = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> Any:
    headers = {
        "User-Agent": OSM_USER_AGENT,
        "Accept": "application/json",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        logger.warning("OSM HTTP %s for %s: %s", exc.code, url, exc)
        raise DirectoryUnavailableError() from exc
    except urllib.error.URLError as exc:
        logger.warning("OSM network error for %s: %s", url, exc)
        raise DirectoryUnavailableError() from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectoryUnavailableError("The map directory returned an unreadable response.") from exc


def geocode_city(city: str, http_json: Callable[..., Any] = _request_json) -> Dict[str, Any]:
    """Resolve a city / neighbourhood / postcode via Nominatim."""
    query = (city or "").strip()
    if len(query) < 2:
        raise CityNotFoundError(query or "that place")
    url = (
        NOMINATIM_URL
        + "?"
        + urllib.parse.urlencode({"q": query, "format": "json", "limit": 1, "addressdetails": 1})
    )
    try:
        payload = http_json(url)
    except DirectoryUnavailableError:
        raise
    except Exception as exc:
        raise DirectoryUnavailableError() from exc
    if not isinstance(payload, list) or not payload:
        raise CityNotFoundError(query)
    hit = payload[0]
    try:
        lat = float(hit["lat"])
        lon = float(hit["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CityNotFoundError(query) from exc
    display = hit.get("display_name") or query
    return {"lat": lat, "lon": lon, "label": display, "source": "OpenStreetMap Nominatim"}


def _overpass_query(lat: float, lon: float, radius_m: int) -> str:
    around = f"(around:{radius_m},{lat:.6f},{lon:.6f})"
    return (
        f"[out:json][timeout:{HTTP_TIMEOUT_SECONDS}];"
        "("
        f'nwr["amenity"~"^(clinic|doctors|hospital)$"]{around};'
        f'nwr["healthcare"~"^(doctor|clinic|hospital|centre|center)$"]{around};'
        f'nwr["healthcare:speciality"]{around};'
        ");"
        "out center tags;"
    )


def fetch_osm_places(
    lat: float,
    lon: float,
    radius_m: int,
    http_json: Callable[..., Any] = _request_json,
) -> List[Dict[str, Any]]:
    """Query Overpass for clinics, doctors, and hospitals around a point."""
    body = _overpass_query(lat, lon, radius_m).encode("utf-8")
    try:
        payload = http_json(OVERPASS_URL, data=body)
    except DirectoryUnavailableError:
        raise
    except Exception as exc:
        raise DirectoryUnavailableError() from exc
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise DirectoryUnavailableError("The map directory returned no usable places.")
    return elements


def geocode_city_geoapify(city: str, http_json: Callable[..., Any] = _request_json) -> Dict[str, Any]:
    """Resolve a city / neighbourhood / postcode via Geoapify Geocoding."""
    query = (city or "").strip()
    if len(query) < 2:
        raise CityNotFoundError(query or "that place")
    key = geoapify_key()
    if not key:
        raise DirectoryUnavailableError("Geoapify is not configured.")
    url = (
        GEOAPIFY_GEOCODE_URL
        + "?"
        + urllib.parse.urlencode({"text": query, "format": "json", "limit": 1, "apiKey": key})
    )
    try:
        payload = http_json(url)
    except DirectoryUnavailableError:
        raise
    except Exception as exc:
        raise DirectoryUnavailableError() from exc
    if not isinstance(payload, dict):
        raise DirectoryUnavailableError("Geoapify returned an unreadable geocode response.")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        features = payload.get("features")
        if isinstance(features, list) and features:
            props = (features[0] or {}).get("properties") or {}
            results = [props]
        else:
            raise CityNotFoundError(query)
    hit = results[0] if isinstance(results[0], dict) else {}
    try:
        lat = float(hit["lat"])
        lon = float(hit["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CityNotFoundError(query) from exc
    return {
        "lat": lat,
        "lon": lon,
        "label": hit.get("formatted") or hit.get("city") or query,
        "source": "Geoapify Geocoding",
        "place_id": hit.get("place_id"),
    }


def fetch_geoapify_places(
    lat: float,
    lon: float,
    radius_m: int,
    *,
    specialty_id: str = "general_practice",
    http_json: Callable[..., Any] = _request_json,
) -> List[Dict[str, Any]]:
    """Query Geoapify Places for clinics / hospitals around a point.

    Returns GeoJSON features (not OSM elements).
    """
    key = geoapify_key()
    if not key:
        raise DirectoryUnavailableError("Geoapify is not configured.")
    categories = GEOAPIFY_CATEGORIES.get(specialty_id) or GEOAPIFY_CATEGORIES["general_practice"]
    url = (
        GEOAPIFY_PLACES_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "categories": ",".join(categories),
                "filter": f"circle:{lon},{lat},{radius_m}",
                "bias": f"proximity:{lon},{lat}",
                "limit": 40,
                "apiKey": key,
            }
        )
    )
    try:
        payload = http_json(url)
    except DirectoryUnavailableError:
        raise
    except Exception as exc:
        raise DirectoryUnavailableError() from exc
    if not isinstance(payload, dict):
        raise DirectoryUnavailableError("Geoapify returned an unreadable places response.")
    features = payload.get("features")
    if not isinstance(features, list):
        raise DirectoryUnavailableError("The map directory returned no usable places.")
    return features


def _geoapify_categories_of(feature: Dict[str, Any]) -> List[str]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else feature
    raw = props.get("categories") or []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    return []


def _geoapify_place_type(categories: Sequence[str]) -> str:
    joined = " ".join(categories).lower()
    if "hospital" in joined:
        return "hospital"
    if "clinic" in joined or "praxis" in joined:
        return "clinic"
    if "dentist" in joined:
        return "doctor"
    return "healthcare"


def _geoapify_match_kind(categories: Sequence[str], name: str, specialty_id: str) -> str:
    tokens = _specialty_tokens(specialty_id)
    hay = f"{' '.join(categories)} {name}".lower()
    if specialty_id != "general_practice" and any(token and token in hay for token in tokens):
        return "specialty"
    place = _geoapify_place_type(categories)
    if place == "hospital":
        return "hospital"
    if specialty_id == "general_practice" or place in {"clinic", "doctor"}:
        return "general"
    return "other"


def _geoapify_contact(props: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    raw = ((props.get("datasource") or {}).get("raw") or {}) if isinstance(props.get("datasource"), dict) else {}
    contact = props.get("contact") if isinstance(props.get("contact"), dict) else {}
    phone = (
        props.get("phone")
        or contact.get("phone")
        or raw.get("phone")
        or raw.get("contact:phone")
    )
    website = (
        props.get("website")
        or contact.get("website")
        or raw.get("website")
        or raw.get("contact:website")
    )
    hours = props.get("opening_hours") or raw.get("opening_hours")
    return (
        str(phone).strip() if phone else None,
        str(website).strip() if website else None,
        str(hours).strip() if hours else None,
    )


def _geoapify_address(props: Dict[str, Any]) -> Optional[str]:
    formatted = props.get("formatted")
    if formatted:
        return str(formatted)
    parts = [
        props.get("housenumber"),
        props.get("street"),
        props.get("suburb") or props.get("district"),
        props.get("city") or props.get("town"),
        props.get("postcode"),
    ]
    line = ", ".join(str(p) for p in parts if p)
    return line or None


def _geoapify_coords(feature: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    try:
        if "lat" in props and "lon" in props:
            return float(props["lat"]), float(props["lon"])
    except (TypeError, ValueError):
        pass
    geom = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    coords = geom.get("coordinates")
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            return float(coords[1]), float(coords[0])
        except (TypeError, ValueError):
            return None
    return None


def _normalize_geoapify_place(
    feature: Dict[str, Any],
    *,
    origin: Dict[str, Any],
    specialty_id: str,
    days: Sequence[str],
    time_of_day: str,
    radius_km: float,
) -> Optional[Dict[str, Any]]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else feature
    if not isinstance(props, dict):
        return None
    coords = _geoapify_coords(feature if "geometry" in feature or "properties" in feature else {"properties": props})
    if coords is None:
        return None
    lat, lon = coords
    name = (props.get("name") or props.get("address_line1") or "").strip()
    categories = _geoapify_categories_of(feature if "properties" in feature else {"properties": props})
    place_type = _geoapify_place_type(categories)
    if not name:
        if place_type == "hospital":
            name = "Hospital"
        elif place_type == "clinic":
            name = "Clinic"
        else:
            return None
    phone, website, hours = _geoapify_contact(props)
    address = _geoapify_address(props)
    availability = availability_status(hours, days, time_of_day)
    match_kind = _geoapify_match_kind(categories, name, specialty_id)
    place_id = props.get("place_id") or ""
    tags = {
        "phone": phone,
        "website": website,
        "opening_hours": hours,
        "addr:full": address,
    }
    distance_km = _haversine_km(origin["lat"], origin["lon"], lat, lon)
    specialties = []
    for cat in categories:
        if "clinic_or_praxis." in cat:
            specialties.append(cat.rsplit(".", 1)[-1].replace("_", " "))
        elif cat.endswith(".hospital"):
            specialties.append("hospital")
    source_url = (
        f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}"
    )
    raw = ((props.get("datasource") or {}).get("raw") or {}) if isinstance(props.get("datasource"), dict) else {}
    osm_type = raw.get("osm_type") or raw.get("osm_kind")
    osm_id = raw.get("osm_id")
    if osm_type and osm_id:
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
    return {
        "id": f"geoapify/{place_id}" if place_id else f"geoapify/{name}",
        "name": name,
        "place_type": place_type,
        "match_kind": match_kind,
        "specialties": specialties,
        "address": address,
        "phone": phone,
        "website": website,
        "opening_hours": hours,
        "availability": availability,
        "lat": lat,
        "lon": lon,
        "distance_km": round(distance_km, 2),
        "score": round(
            _score_place(
                match_kind=match_kind,
                distance_km=distance_km,
                radius_km=radius_km,
                availability=availability,
                tags=tags,
            ),
            1,
        ),
        "source": "Geoapify",
        "source_url": source_url,
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


def _coords(element: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    if "lat" in element and "lon" in element:
        try:
            return float(element["lat"]), float(element["lon"])
        except (TypeError, ValueError):
            return None
    center = element.get("center") or {}
    try:
        return float(center["lat"]), float(center["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def _address(tags: Dict[str, Any]) -> Optional[str]:
    parts = [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
        tags.get("addr:suburb") or tags.get("addr:neighbourhood"),
        tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village"),
        tags.get("addr:postcode"),
    ]
    line = ", ".join(str(p) for p in parts if p)
    return line or tags.get("addr:full")


def _place_type(tags: Dict[str, Any]) -> str:
    healthcare = (tags.get("healthcare") or "").lower()
    amenity = (tags.get("amenity") or "").lower()
    if amenity == "hospital" or healthcare == "hospital":
        return "hospital"
    if amenity == "clinic" or healthcare in {"clinic", "centre", "center"}:
        return "clinic"
    if amenity == "doctors" or healthcare == "doctor":
        return "doctor"
    return amenity or healthcare or "healthcare"


def _specialty_tokens(specialty_id: str) -> Tuple[str, ...]:
    spec = SPECIALTIES.get(specialty_id) or SPECIALTIES["general_practice"]
    return tuple(spec["osm"]) + tuple(spec["keywords"]) + (spec["label"].lower(),)


def _match_kind(tags: Dict[str, Any], name: str, specialty_id: str) -> str:
    tokens = _specialty_tokens(specialty_id)
    raw_speciality = " ".join(
        str(tags.get(key) or "")
        for key in ("healthcare:speciality", "healthcare:specialty", "speciality", "specialty")
    ).lower()
    hay = f"{raw_speciality} {name}".lower()
    if specialty_id != "general_practice" and any(token and token in hay for token in tokens):
        return "specialty"
    place = _place_type(tags)
    if place == "hospital":
        return "hospital"
    if specialty_id == "general_practice" or place in {"clinic", "doctor"}:
        return "general"
    return "other"


def _score_place(
    *,
    match_kind: str,
    distance_km: float,
    radius_km: float,
    availability: str,
    tags: Dict[str, Any],
) -> float:
    specialty_points = {"specialty": 100, "hospital": 45, "general": 35, "other": 10}[match_kind]
    avail_points = {"open": 30, "unknown": 12, "closed": 0}[availability]
    span = max(radius_km, 0.1)
    distance_points = 40.0 * max(0.0, 1.0 - (distance_km / span))
    info_points = 0.0
    if tags.get("phone") or tags.get("contact:phone"):
        info_points += 5
    if tags.get("website") or tags.get("contact:website"):
        info_points += 5
    if tags.get("opening_hours"):
        info_points += 5
    if _address(tags):
        info_points += 5
    return specialty_points + avail_points + distance_points + info_points


def _normalize_place(
    element: Dict[str, Any],
    *,
    origin: Dict[str, Any],
    specialty_id: str,
    days: Sequence[str],
    time_of_day: str,
    radius_km: float,
) -> Optional[Dict[str, Any]]:
    tags = element.get("tags") or {}
    if not isinstance(tags, dict):
        return None
    coords = _coords(element)
    if coords is None:
        return None
    lat, lon = coords
    name = (tags.get("name") or tags.get("official_name") or "").strip()
    place_type = _place_type(tags)
    if not name:
        if place_type == "hospital":
            name = "Hospital"
        elif place_type == "clinic":
            name = "Clinic"
        else:
            return None
    distance_km = _haversine_km(origin["lat"], origin["lon"], lat, lon)
    hours = tags.get("opening_hours")
    availability = availability_status(hours, days, time_of_day)
    match_kind = _match_kind(tags, name, specialty_id)
    osm_type = element.get("type") or "node"
    osm_id = element.get("id")
    source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_id else "https://www.openstreetmap.org/"
    speciality = tags.get("healthcare:speciality") or tags.get("healthcare:specialty") or tags.get("speciality")
    return {
        "id": f"{osm_type}/{osm_id}",
        "name": name,
        "place_type": place_type,
        "match_kind": match_kind,
        "specialties": [part.strip() for part in str(speciality).split(";") if part.strip()] if speciality else [],
        "address": _address(tags),
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "website": tags.get("website") or tags.get("contact:website"),
        "opening_hours": hours,
        "availability": availability,
        "lat": lat,
        "lon": lon,
        "distance_km": round(distance_km, 2),
        "score": round(
            _score_place(
                match_kind=match_kind,
                distance_km=distance_km,
                radius_km=radius_km,
                availability=availability,
                tags=tags,
            ),
            1,
        ),
        "source": "OpenStreetMap",
        "source_url": source_url,
    }


def _pack_search(
    *,
    city: str,
    chosen_id: str,
    chosen_label: str,
    wanted_days: List[str],
    tod: str,
    radius_km_used: float,
    location: Dict[str, Any],
    suggestion: Dict[str, Any],
    places: List[Dict[str, Any]],
    source: Dict[str, Any],
) -> Dict[str, Any]:
    places = sorted(places, key=lambda item: (-item["score"], item["distance_km"], item["name"]))[:25]
    zero_hint = None
    if not places:
        zero_hint = (
            f"No clinics, doctors, or hospitals are listed within {radius_km_used:g} km of "
            f"{location['label']}. Try a larger area, a nearby city, or a different spelling. "
            f"Coverage is better in cities than in small towns."
        )
    return {
        "query": {
            "city": city.strip(),
            "specialty_id": chosen_id,
            "specialty_label": chosen_label,
            "days": wanted_days,
            "time_of_day": tod,
            "radius_km": radius_km_used,
        },
        "location": location,
        "suggestion": suggestion["suggested"],
        "results": places,
        "result_count": len(places),
        "zero_results_hint": zero_hint,
        "source": dict(source),
        "disclaimer": DISCLAIMER,
    }


def _search_osm(
    *,
    city: str,
    chosen_id: str,
    chosen_label: str,
    wanted_days: List[str],
    tod: str,
    radius_m: int,
    radius_km_used: float,
    suggestion: Dict[str, Any],
    geocode: Callable[[str], Dict[str, Any]],
    fetch_places: Callable[..., List[Dict[str, Any]]],
) -> Dict[str, Any]:
    location = geocode(city)
    elements = fetch_places(location["lat"], location["lon"], radius_m)
    seen = set()
    places: List[Dict[str, Any]] = []
    for element in elements:
        key = (element.get("type"), element.get("id"))
        if key in seen:
            continue
        seen.add(key)
        place = _normalize_place(
            element,
            origin=location,
            specialty_id=chosen_id,
            days=wanted_days,
            time_of_day=tod,
            radius_km=radius_km_used,
        )
        if place:
            places.append(place)
    return _pack_search(
        city=city,
        chosen_id=chosen_id,
        chosen_label=chosen_label,
        wanted_days=wanted_days,
        tod=tod,
        radius_km_used=radius_km_used,
        location=location,
        suggestion=suggestion,
        places=places,
        source=SOURCE_OSM,
    )


def _search_geoapify(
    *,
    city: str,
    chosen_id: str,
    chosen_label: str,
    wanted_days: List[str],
    tod: str,
    radius_m: int,
    radius_km_used: float,
    suggestion: Dict[str, Any],
    geocode: Callable[[str], Dict[str, Any]] = geocode_city_geoapify,
    fetch_places: Callable[..., List[Dict[str, Any]]] = fetch_geoapify_places,
) -> Dict[str, Any]:
    location = geocode(city)
    features = fetch_places(
        location["lat"],
        location["lon"],
        radius_m,
        specialty_id=chosen_id,
    )
    places: List[Dict[str, Any]] = []
    seen = set()
    for feature in features:
        props = feature.get("properties") if isinstance(feature, dict) else None
        place_id = (props or {}).get("place_id") if isinstance(props, dict) else None
        key = place_id or id(feature)
        if key in seen:
            continue
        seen.add(key)
        place = _normalize_geoapify_place(
            feature if isinstance(feature, dict) else {},
            origin=location,
            specialty_id=chosen_id,
            days=wanted_days,
            time_of_day=tod,
            radius_km=radius_km_used,
        )
        if place:
            places.append(place)
    return _pack_search(
        city=city,
        chosen_id=chosen_id,
        chosen_label=chosen_label,
        wanted_days=wanted_days,
        tod=tod,
        radius_km_used=radius_km_used,
        location=location,
        suggestion=suggestion,
        places=places,
        source=SOURCE_GEOAPIFY,
    )


def search_care(
    *,
    city: str,
    specialty_id: Optional[str] = None,
    days: Optional[Sequence[str]] = None,
    time_of_day: str = "any",
    radius_km: float = 8.0,
    timeline: Optional[Dict[str, Any]] = None,
    geocode: Optional[Callable[[str], Dict[str, Any]]] = None,
    fetch_places: Optional[Callable[..., List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Search nearby clinics. Geoapify first when keyed; OSM otherwise."""
    suggestion = suggest_specialties(timeline)
    chosen_id = (specialty_id or suggestion["suggested"]["id"] or "general_practice").strip()
    if chosen_id not in SPECIALTIES:
        chosen_id = "general_practice"
    chosen_label = SPECIALTIES[chosen_id]["label"]

    wanted_days = [d for d in (days or DAYS[:5]) if d in DAY_INDEX]
    if not wanted_days:
        wanted_days = list(DAYS[:5])
    tod = time_of_day if time_of_day in TIME_WINDOWS else "any"
    radius_m = int(max(1000, min(MAX_RADIUS_M, (radius_km or 8) * 1000)))
    radius_km_used = radius_m / 1000.0

    shared = dict(
        city=city,
        chosen_id=chosen_id,
        chosen_label=chosen_label,
        wanted_days=wanted_days,
        tod=tod,
        radius_m=radius_m,
        radius_km_used=radius_km_used,
        suggestion=suggestion,
    )

    # Tests (and callers) that inject OSM helpers stay on the OSM path.
    injected = geocode is not None or fetch_places is not None
    if injected:
        return _search_osm(
            **shared,
            geocode=geocode or geocode_city,
            fetch_places=fetch_places or fetch_osm_places,
        )

    if geoapify_configured():
        try:
            result = _search_geoapify(**shared)
            if result["results"]:
                return result
            logger.info("Geoapify returned 0 clinics for %s; trying OpenStreetMap.", city)
        except CityNotFoundError:
            logger.info("Geoapify geocoding missed %r; trying Nominatim.", city)
        except DirectoryUnavailableError as exc:
            logger.warning("Geoapify unavailable (%s); trying OpenStreetMap.", exc)
        except Exception as exc:
            logger.warning("Geoapify failed (%s); trying OpenStreetMap.", exc)

    return _search_osm(
        **shared,
        geocode=geocode_city,
        fetch_places=fetch_osm_places,
    )
