/**
 * Guards the Find Care invariant that broke in production:
 * the category counts and the rendered cards must come from the same
 * dataset and the same predicate, so "7 found" can never be followed by
 * "No facilities match this filter".
 *
 * Run with: npm run test:facilities
 */
import assert from "node:assert/strict";

import type { CareFacility, FacilityKind } from "../../types/facility";
import {
  countByFilter,
  filterFacilities,
  googleDirectionsUrl,
  googleMapsUrl,
  matchesFilter,
  normalizeFacilityKind,
  telHref,
  type FacilityFilter,
} from "../facilities";

const FILTERS: FacilityFilter[] = [
  "all",
  "hospital",
  "clinic",
  "pharmacy",
  "laboratory",
  "doctor",
  "other",
];

function facility(id: string, kind: FacilityKind, extra: Partial<CareFacility> = {}): CareFacility {
  return {
    id,
    name: `Facility ${id}`,
    kind,
    latitude: 6.9,
    longitude: 79.9,
    distanceKm: 1.2,
    source: "Google Places public listing",
    ...extra,
  };
}

const tests: Array<[string, () => void]> = [
  [
    "counts sum to the total, so no result is invisible under every filter",
    () => {
      const facilities = [
        facility("1", "clinic"),
        facility("2", "clinic"),
        facility("3", "hospital"),
        facility("4", "other"),
        facility("5", "pharmacy"),
        facility("6", "laboratory"),
        facility("7", "doctor"),
      ];
      const counts = countByFilter(facilities, FILTERS);
      assert.equal(counts.all, 7);
      const categorySum = FILTERS.filter((value) => value !== "all").reduce(
        (total, value) => total + counts[value],
        0
      );
      assert.equal(categorySum, 7, "every facility must fall into exactly one category");
    },
  ],
  [
    "a non-zero count always renders that many cards (BUG-001/002)",
    () => {
      const facilities = [
        facility("1", "clinic"),
        facility("2", "clinic"),
        facility("3", "hospital"),
      ];
      const counts = countByFilter(facilities, FILTERS);
      for (const value of FILTERS) {
        assert.equal(
          filterFacilities(facilities, value).length,
          counts[value],
          `count and rendered list disagree for "${value}"`
        );
      }
    },
  ],
  [
    "the All view shows every returned facility",
    () => {
      const facilities = Array.from({ length: 7 }, (_, index) =>
        facility(String(index), "clinic")
      );
      assert.equal(filterFacilities(facilities, "all").length, 7);
    },
  ],
  [
    "each category filter returns only that category",
    () => {
      const facilities = [
        facility("h", "hospital"),
        facility("c", "clinic"),
        facility("p", "pharmacy"),
        facility("l", "laboratory"),
        facility("d", "doctor"),
      ];
      for (const kind of ["hospital", "clinic", "pharmacy", "laboratory", "doctor"] as const) {
        const result = filterFacilities(facilities, kind);
        assert.equal(result.length, 1);
        assert.equal(result[0].kind, kind);
      }
    },
  ],
  [
    "unknown provider kinds are bucketed, never dropped (BUG-013)",
    () => {
      assert.equal(normalizeFacilityKind("healthcare"), "other");
      assert.equal(normalizeFacilityKind(undefined), "other");
      assert.equal(normalizeFacilityKind("lab"), "laboratory");
      assert.equal(normalizeFacilityKind("medical_clinic"), "clinic");
      assert.equal(normalizeFacilityKind("general_hospital"), "hospital");
      assert.equal(normalizeFacilityKind("drugstore"), "pharmacy");
      assert.equal(normalizeFacilityKind("dentist"), "doctor");
      assert.equal(normalizeFacilityKind("HOSPITAL"), "hospital");
      // Whatever the value, "all" still matches it.
      assert.ok(matchesFilter(facility("x", normalizeFacilityKind("weird_type")), "all"));
    },
  ],
  [
    "Open in Google Maps never links to OpenStreetMap",
    () => {
      const osmOnly = facility("1", "hospital", {
        name: "Asiri Medical Hospital",
        address: "21 Kirimandala Mawatha, Colombo 05",
        mapsUrl: "https://www.openstreetmap.org/?mlat=6.9&mlon=79.9",
      });
      const url = googleMapsUrl(osmOnly);
      assert.ok(url.startsWith("https://www.google.com/maps/"), url);
      assert.ok(!url.includes("openstreetmap"));
      assert.ok(url.includes("Asiri"));
    },
  ],
  [
    "a canonical Google Maps URI is preferred verbatim",
    () => {
      const google = facility("1", "hospital", { mapsUrl: "https://maps.google.com/?cid=123" });
      assert.equal(googleMapsUrl(google), "https://maps.google.com/?cid=123");
    },
  ],
  [
    "map links use coordinates when the listing has no address",
    () => {
      const bare = facility("1", "clinic", { name: "", address: undefined });
      const url = googleMapsUrl(bare);
      assert.ok(url.includes("6.9,79.9"), url);
      assert.ok(googleDirectionsUrl(bare).startsWith("https://www.google.com/maps/dir/"));
    },
  ],
  [
    "call links are produced only for real phone numbers",
    () => {
      assert.equal(telHref("+94 11 452 3300"), "tel:+94114523300");
      assert.equal(telHref(undefined), null);
      assert.equal(telHref(""), null);
      assert.equal(telHref("n/a"), null);
    },
  ],
];

let failures = 0;
for (const [name, run] of tests) {
  try {
    run();
    console.log(`PASS ${name}`);
  } catch (error) {
    failures += 1;
    console.error(`FAIL ${name}`);
    console.error(error);
  }
}
console.log(`\n${tests.length - failures}/${tests.length} tests passed`);
if (failures) process.exit(1);
