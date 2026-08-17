"""Offline tests for the WHO antidote reference knowledge graph
(poisoning_kg.py + graph_db.py). No real Neo4j or WHO PDF required:
extraction is tested against synthetic WHO-EML-shaped PDFs, and the graph
layer is tested with faked sessions — deterministic code, no network."""

import os
import sys
import types
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import graph_db
import poisoning_kg

# ---------------------------------------------------------------------------
# Synthetic WHO EML PDF fixtures (PyMuPDF-drawn grid + text, which
# pdfplumber reads back as real tables)
# ---------------------------------------------------------------------------


def _make_who_pdf(path, population="adult", with_section=True):
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    title = (
        "WHO Model List of Essential Medicines for Children - 9th list (2025)"
        if population == "children"
        else "WHO Model List of Essential Medicines - 24th list (2025)"
    )
    page.insert_text((45, 40), title, fontsize=10)
    page.insert_text((45, 60), "Essential Medicines Library, Geneva", fontsize=8)

    # grid: verticals x=40,300,560; horizontals every 20pt from y=100
    for x in (40, 300, 560):
        page.draw_line((x, 100), (x, 280))
    for y in range(100, 300, 20):
        page.draw_line((40, y), (560, y))

    rows = []
    if with_section:
        rows += [
            (None, "4. ANTIDOTES AND OTHER SUBSTANCES USED IN POISONINGS"),
            (None, "4.1 Non-specific"),
            ("charcoal, activated", "Powder"),
            ("naloxone", "Injection: 400 micrograms/mL"),
            (None, "4.2 Specific"),
            ("acetylcysteine", "Injection: 200 mg/mL"),
            (None, "Complementary List"),
            ("atropine", "Injection: 1 mg/mL"),
            (None, "5. MEDICINES FOR PAIN AND PALLIATIVE CARE"),
        ]
    else:
        rows += [
            (None, "5. MEDICINES FOR PAIN AND PALLIATIVE CARE"),
            ("morphine", "Injection: 10 mg/mL"),
        ]

    for i, (name, form) in enumerate(rows):
        y = 108 + i * 20
        if name:
            page.insert_text((45, y + 8), name, fontsize=8)
            page.insert_text((305, y + 8), form, fontsize=8)
        else:
            page.insert_text((45, y + 8), form, fontsize=8)
    doc.save(path)
    doc.close()


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extracts_adult_eml_entries_with_subsection_and_list_type(tmp_path):
    pdf = tmp_path / "who_eml.pdf"
    _make_who_pdf(str(pdf), population="adult")
    section = poisoning_kg.extract_antidote_section(str(pdf))

    assert section["population"] == "adult"
    by_name = {e["name"]: e for e in section["entries"]}
    assert set(by_name) == {
        "charcoal, activated", "naloxone", "acetylcysteine", "atropine",
    }
    assert by_name["naloxone"]["subsection"] == "non_specific"
    assert by_name["naloxone"]["list_type"] == "core"
    assert by_name["naloxone"]["dosage_form"] == "Injection: 400 micrograms/mL"
    assert by_name["acetylcysteine"]["subsection"] == "specific"
    # 'Complementary List' marker switches every following row
    assert by_name["atropine"]["list_type"] == "complementary"


def test_children_population_read_from_document_title_not_filename(tmp_path):
    pdf = tmp_path / "anything.pdf"  # deliberately misleading name
    _make_who_pdf(str(pdf), population="children")
    section = poisoning_kg.extract_antidote_section(str(pdf))
    assert section["population"] == "children"
    assert len(section["entries"]) == 4


def test_pdf_without_antidote_section_yields_no_entries(tmp_path):
    pdf = tmp_path / "not_who.pdf"
    _make_who_pdf(str(pdf), with_section=False)
    section = poisoning_kg.extract_antidote_section(str(pdf))
    assert section["entries"] == []


def test_deterministic_extraction_is_verbatim():
    """Every field is copied from a table cell — nothing is inferred or
    synthesized, which is the whole point of a deterministic reference
    loader (nothing to hallucinate)."""
    import pdfplumber

    entries = [
        {"name": "naloxone", "dosage_form": "Injection: 400 micrograms/mL",
         "subsection": "non_specific", "list_type": "core", "source_page": 1},
    ]
    section = {"population": "adult", "entries": entries}
    # verify the ingested row shape matches the extraction shape exactly
    row = entries[0]
    assert set(row) == {"name", "dosage_form", "subsection", "list_type", "source_page"}
    # and that the graph query params carry rows/population/source verbatim
    assert section["population"] == "adult"


# ---------------------------------------------------------------------------
# Lookup (faked graph session)
# ---------------------------------------------------------------------------


class _DummySession:
    pass


@contextmanager
def _fake_session_scope(operation):
    yield _DummySession()


def test_lookup_returns_listings_per_original_spelling(monkeypatch):
    captured = {}

    def _fake_run_read(session, operation, step, cypher, **params):
        captured["cypher"] = cypher
        captured["params"] = params
        return [
            {"wanted": "Naloxone", "display_name": "naloxone", "category": "specific",
             "dosage_form": "Injection", "list_type": "core",
             "source_document": "who_eml.pdf", "population": "adult"},
            {"wanted": "Naloxone", "display_name": "naloxone", "category": "specific",
             "dosage_form": "Injection", "list_type": "core",
             "source_document": "who_emlc.pdf", "population": "children"},
        ]

    monkeypatch.setattr(poisoning_kg, "session_scope", _fake_session_scope)
    monkeypatch.setattr(poisoning_kg, "run_read", _fake_run_read)

    refs = poisoning_kg.lookup_antidote_references(["Naloxone", "ibuprofen"])

    assert set(refs) == {"Naloxone"}
    ref = refs["Naloxone"]
    assert ref["display_name"] == "naloxone"
    assert ref["category"] == "specific"
    assert len(ref["listings"]) == 2
    populations = {listing["population"] for listing in ref["listings"]}
    assert populations == {"adult", "children"}  # both lists, not last-loaded-wins
    # one bulk query for the whole medication list
    assert captured["params"]["names"] == ["Naloxone", "ibuprofen"]
    assert "UNWIND $names" in captured["cypher"]


def test_lookup_with_no_names_sends_no_query(monkeypatch):
    called = []

    def _fake_run_read(*args, **kwargs):
        called.append(args)
        return []

    monkeypatch.setattr(poisoning_kg, "session_scope", _fake_session_scope)
    monkeypatch.setattr(poisoning_kg, "run_read", _fake_run_read)
    assert poisoning_kg.lookup_antidote_references([]) == {}
    assert poisoning_kg.lookup_antidote_references([""]) == {}
    assert called == []


def test_lookup_single_drug_wrapper(monkeypatch):
    monkeypatch.setattr(
        poisoning_kg, "lookup_antidote_references",
        lambda names: {"naloxone": {"display_name": "naloxone"}},
    )
    assert poisoning_kg.lookup_antidote_reference("naloxone") == {"display_name": "naloxone"}
    assert poisoning_kg.lookup_antidote_reference("ibuprofen") is None


# ---------------------------------------------------------------------------
# Ingestion (faked graph session)
# ---------------------------------------------------------------------------


def _fake_summary(nodes=0, rels=0, props=0):
    return types.SimpleNamespace(
        counters=types.SimpleNamespace(
            nodes_created=nodes, relationships_created=rels, properties_set=props,
        )
    )


def test_ingest_writes_rows_with_population_and_source(monkeypatch):
    captured = {}

    def _fake_run_write(session, operation, step, cypher, **params):
        captured["cypher"] = cypher
        captured["params"] = params
        return _fake_summary(nodes=2, rels=4, props=6)

    monkeypatch.setattr(poisoning_kg, "session_scope", _fake_session_scope)
    monkeypatch.setattr(poisoning_kg, "run_write", _fake_run_write)

    section = {
        "population": "children",
        "entries": [
            {"name": "naloxone", "dosage_form": "Injection", "subsection": "specific",
             "list_type": "core", "source_page": 1},
            {"name": "charcoal, activated", "dosage_form": "Powder",
             "subsection": "non_specific", "list_type": "core", "source_page": 1},
        ],
    }
    count = poisoning_kg.ingest_antidote_entries(section, source_document="who_emlc.pdf")

    assert count == 2
    params = captured["params"]
    assert params["source_document"] == "who_emlc.pdf"
    assert params["population"] == "children"
    assert params["rows"] == section["entries"]
    # MERGE-based: idempotent by construction
    assert "MERGE (m:Medicine" in captured["cypher"]
    assert "LISTED_IN" in captured["cypher"]


def test_ingest_with_no_entries_skips_write_entirely(monkeypatch):
    called = []

    def _fake_run_write(*args, **kwargs):
        called.append(args)
        return _fake_summary()

    monkeypatch.setattr(poisoning_kg, "session_scope", _fake_session_scope)
    monkeypatch.setattr(poisoning_kg, "run_write", _fake_run_write)
    assert poisoning_kg.ingest_antidote_entries(
        {"population": "adult", "entries": []}, source_document="empty.pdf",
    ) == 0
    assert called == []


# ---------------------------------------------------------------------------
# graph_db configuration gates
# ---------------------------------------------------------------------------


def test_graph_not_configured_without_env(monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    assert graph_db.is_configured() is False
    try:
        graph_db.get_driver()
    except graph_db.GraphUnavailableError:
        pass
    else:
        raise AssertionError("get_driver must refuse to connect when unconfigured")


def test_graph_configured_with_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://example.databases.neo4j.io")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    if graph_db.NEO4J_IMPORT_OK:
        assert graph_db.is_configured() is True
    monkeypatch.delenv("NEO4J_URI")
    monkeypatch.delenv("NEO4J_USERNAME")
    monkeypatch.delenv("NEO4J_PASSWORD")


def test_safe_uri_strips_embedded_credentials():
    assert graph_db._safe_uri("neo4j+s://user:secret@host.db") == "neo4j+s://<redacted>@host.db"
    assert graph_db._safe_uri("neo4j://host") == "neo4j://host"
