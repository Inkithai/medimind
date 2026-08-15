import { renderToStaticMarkup } from "react-dom/server";
import { I18nProvider } from "../../i18n/I18nContext";

import { ProviderResultCard } from "../ProviderResultCard";
import type { LiveProvider } from "../../types/api";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

// Generic directory-shaped test data only. It is not a doctor, clinic, or
// provider record and is never sent through the application API.
const sparseDirectoryResult: LiveProvider = {
  source_provider_id: null,
  name: "Directory result",
  provider_type: null,
  source_specialties: [],
  address: null,
  latitude: null,
  longitude: null,
  distance_km: null,
  rating: null,
  rating_count: null,
  phone: null,
  opening_hours: [],
  open_now: null,
  map_url: null,
  website_url: "javascript:invalid",
  source: "Live directory test source",
  ranking: {
    score: 72,
    specialty_relevance: "Source metadata matches the selected category.",
    distance: "Distance unavailable.",
    rating: "No rating was provided by the live directory.",
    availability: "Availability was not used.",
    availability_preference: "Any consultation time",
  },
};

const markup = renderToStaticMarkup(<I18nProvider><ProviderResultCard provider={sparseDirectoryResult} index={0} /></I18nProvider>);
assert(markup.includes("Directory match 72"), "labels score as a directory match");
assert(!markup.includes("Match score"), "does not use generic match-score wording");
assert(!markup.includes("Rating"), "does not render a missing directory rating");
assert(!markup.includes("Opening hours supplied by directory"), "does not render missing directory hours");
assert(!markup.includes("Provider website"), "does not render an invalid external URL");
assert(markup.includes("Why this directory match is shown"), "explains ranking as a directory match");

console.log("\nAll ProviderResultCard tests passed.");
