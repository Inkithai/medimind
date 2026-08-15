/**
 * Renders a care result and asserts the contract from the bug report:
 * real facility name, ⭐ rating + reviews when available, type, address,
 * phone, hours, distance, a Google Maps button, and a Call button — with
 * explicit "not available" fallbacks and never a fabricated value.
 *
 * Run with: npm run test:card
 */
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";

import { FacilityCard } from "../FacilityCard";
import type { CareFacility } from "../../../types/facility";

const FULL: CareFacility = {
  id: "g1",
  name: "Asiri Medical Hospital",
  kind: "hospital",
  latitude: 6.8951,
  longitude: 79.8636,
  distanceKm: 3.2,
  address: "21 Kirimandala Mawatha, Colombo 05",
  rating: 4.2,
  userRatingCount: 1245,
  phone: "+94 11 452 3300",
  website: "https://asiri.lk",
  mapsUrl: "https://maps.google.com/?cid=1111",
  openingHours: ["Monday: Open 24 hours"],
  openNow: true,
  specialty: "Hospital",
  specialtyMatch: true,
  source: "Google Places public listing",
};

const SPARSE: CareFacility = {
  id: "g6",
  name: "Dr. S. Perera — Consultant Physician",
  kind: "doctor",
  latitude: 6.91,
  longitude: 79.868,
  distanceKm: null,
  source: "Google Places public listing",
};

function render(facility: CareFacility): string {
  return renderToStaticMarkup(<FacilityCard facility={facility} />);
}

const tests: Array<[string, () => void]> = [
  [
    "a complete listing shows every field the directory provided",
    () => {
      const html = render(FULL);
      assert.ok(html.includes("Asiri Medical Hospital"), "real facility name");
      assert.ok(html.includes("Hospital"), "facility type");
      assert.ok(html.includes("⭐ 4.2"), "star rating");
      assert.ok(html.includes("1,245 reviews"), "formatted review count");
      assert.ok(html.includes("21 Kirimandala Mawatha, Colombo 05"), "full address");
      assert.ok(html.includes("+94 11 452 3300"), "phone number");
      assert.ok(html.includes("Monday: Open 24 hours"), "opening hours");
      assert.ok(html.includes("Open now"), "current open status");
      assert.ok(html.includes("3.2 km away"), "distance from selected location");
      assert.ok(html.includes("Matches Hospital"), "specialty match");
    },
  ],
  [
    "Open in Google Maps is present and points at Google Maps",
    () => {
      const html = render(FULL);
      assert.ok(html.includes("Open in Google Maps"));
      assert.ok(html.includes("https://maps.google.com/?cid=1111"));
      assert.ok(!html.toLowerCase().includes("openstreetmap.org/?mlat"));
    },
  ],
  [
    "a listing without a Google URI still gets a Google Maps link built from name + address",
    () => {
      const html = render({ ...FULL, mapsUrl: undefined });
      assert.ok(html.includes("https://www.google.com/maps/search/"));
      assert.ok(html.includes("Asiri+Medical+Hospital"));
    },
  ],
  [
    "a Call button appears only when a phone number exists",
    () => {
      assert.ok(render(FULL).includes("tel:+94114523300"), "call link for a real number");
      assert.ok(!render(SPARSE).includes("tel:"), "no call link without a number");
    },
  ],
  [
    "missing fields degrade gracefully and are never invented",
    () => {
      const html = render(SPARSE);
      assert.ok(html.includes("Dr. S. Perera"), "real name is preserved");
      assert.ok(html.includes("No rating available"));
      assert.ok(html.includes("Address not available"));
      assert.ok(html.includes("Phone not available"));
      assert.ok(html.includes("Opening hours not available"));
      assert.ok(html.includes("Distance not available"));
      assert.ok(!html.includes("⭐"), "no fake star rating");
      assert.ok(!html.includes("Open now"), "no fake open status");
    },
  ],
  [
    "a single review is not pluralised",
    () => {
      const html = render({ ...FULL, rating: 4, userRatingCount: 1 });
      assert.ok(html.includes("1 review"));
      assert.ok(!html.includes("1 reviews"));
    },
  ],
  [
    "the source line marks the listing as directory data, not a recommendation",
    () => {
      const html = render(FULL);
      assert.ok(html.includes("Google Places public listing"));
      assert.ok(html.includes("Not a MediMind recommendation"));
    },
  ],
  [
    "actions carry accessible names that identify the facility",
    () => {
      const html = render(FULL);
      assert.ok(html.includes('aria-label="Open Asiri Medical Hospital in Google Maps"'));
      assert.ok(html.includes('aria-label="Call Asiri Medical Hospital"'));
      assert.ok(html.includes("Rated 4.2 out of 5 from 1,245 reviews"), "rating aria-label");
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
