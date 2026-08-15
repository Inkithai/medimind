/**
 * English copy for the Find Care flow.
 *
 * Every user-visible string on the page comes from this dictionary, so a
 * translation is a matter of adding a sibling file rather than hunting
 * literals through JSX.
 */
export const en = {
  findCare: {
    eyebrow: "Find care",
    title: "Find nearby facilities",
    subtitle:
      "Choose a location to find hospitals, clinics, pharmacies, laboratories, and doctors near you.",
    changeSearchArea: "Change search area",
    urgentTitle: "Need urgent help?",
    urgentBody:
      "For a life-threatening emergency, contact your local emergency service immediately. Facility information comes from public directory listings and should be verified before travelling.",

    preferencesTitle: "Care search preferences",
    preferencesSubtitle: "These narrow the directory search. You can change them at any time.",
    facilityTypeLabel: "Facility type",
    facilityTypeHelp: "Choose a category or search all public healthcare listings.",
    specialtyLabel: "Specialty",
    specialtyHelp: "Optional. Adds the specialty to the directory search.",
    specialtyNone: "No specific specialty",
    radiusLabel: "Search radius",
    radiusOption: (km: number) => `Within ${km} km`,

    suggestedSpecialtyTitle: "Suggested care specialty",
    suggestedSpecialtyApplied: (label: string) => `${label} · applied to this search`,
    suggestedSpecialtyDisclaimer:
      "Based on information extracted from your uploaded records. This is not a diagnosis or a referral.",
    suggestedSpecialtyWhy: "Why this specialty?",
    suggestedSpecialtyReason: (keyword: string, label: string) =>
      `Your records contain ${keyword}-related information, which was used as a search signal for ${label.toLowerCase()} providers. A keyword is not a diagnosis — a clinician should confirm which specialist you need.`,
    suggestedSpecialtyEvidence: "Evidence",
    lowConfidenceNote: (count: number) =>
      count === 1
        ? "1 finding needs professional verification."
        : `${count} findings need professional verification.`,
    useSuggested: "Use this specialty",
    changeSpecialty: "Change specialty",
    clearSpecialty: "Search without a specialty",

    locationTitle: "Where should we search?",
    locationDescription: "Search for a city, area or landmark, or use your current location.",
    confirmLabel: "Find facilities nearby",

    idleTitle: "Select an area to begin",
    idleBody: "Confirm the map pin above and nearby care options will appear here.",
    loadingTitle: (locationName: string) => `Finding care near ${locationName}…`,
    loadingSubtitle: (km: number) => `Searching within ${km} km`,

    errorTitle: "Nearby search didn't load",
    errorFallback: "We couldn't load nearby facilities. Please try again.",
    errorDirectoryHint:
      "The facility directory is unavailable right now. You can retry, widen the radius, or pick a different area.",
    tryAgain: "Try again",

    nearLocation: (name: string) => `Near ${name}`,
    resultsCount: (count: number) =>
      count === 1 ? "1 care option found" : `${count} care options found`,
    noResultsTitle: "No facilities found nearby",
    sortedByDistance: "Sorted by distance",
    sourcePrefix: "Source",
    notARecommendation: "Not a MediMind recommendation",

    filtersLabel: "Filter facilities by type",
    filterAll: "All",
    filterHospital: "Hospitals",
    filterClinic: "Clinics",
    filterPharmacy: "Pharmacies",
    filterLaboratory: "Laboratories",
    filterDoctor: "Doctors",
    filterOther: "Other",

    emptyAreaTitle: "Try a different area",
    emptyAreaBody: (km: number) =>
      `The directory doesn't list any supported healthcare facilities within ${km} km of this pin. Try a wider radius or another area.`,
    emptyFilterTitle: (label: string) => `No ${label.toLowerCase()} found nearby`,
    emptyFilterBody: (available: string) =>
      available
        ? `This search returned ${available}. Choose one of those categories, or show all results.`
        : "Choose another category, or show all results.",
    showAll: "Show all results",

    kindHospital: "Hospital",
    kindClinic: "Clinic",
    kindPharmacy: "Pharmacy",
    kindLaboratory: "Laboratory",
    kindDoctor: "Doctor",
    kindOther: "Healthcare",

    openNow: "Open now",
    closedNow: "Closed now",
    ratingLabel: (rating: string, count: string) => `Rated ${rating} out of 5 from ${count}`,
    ratingNoCount: (rating: string) => `Rated ${rating} out of 5`,
    reviews: (count: string) => `${count} reviews`,
    review: "1 review",
    noRating: "No rating available",
    addressNotAvailable: "Address not available",
    phoneNotAvailable: "Phone not available",
    hoursNotAvailable: "Opening hours not available",
    distanceNotAvailable: "Distance not available",
    openingHours: "Opening hours",
    specialtyMatch: (label: string) => `Matches ${label}`,
    distanceAway: (distance: string) => `${distance} away`,

    call: "Call",
    callAria: (name: string) => `Call ${name}`,
    openInGoogleMaps: "Open in Google Maps",
    openInGoogleMapsAria: (name: string) => `Open ${name} in Google Maps`,
    directions: "Directions",
    website: "Website",
    websiteAria: (name: string) => `Open the website for ${name}`,

    mapTitle: "Results map",
    mapDescription: "Each pin marks a facility from the list below.",
    mapListFallback: "Facility locations are also listed as text below the map.",
  },

  location: {
    stepSearch: "Step 1 of 2 — Search",
    stepConfirm: "Step 2 of 2 — Confirm location",
    searchTitle: "Where do you need the service?",
    confirmTitle: "Confirm your location",
    confirmDescription:
      "Check the pin is in the right area. You can drag it, or use the arrow keys after focusing the pin.",
    changeLocation: "Change location",
    selectedLocation: "Search location",
    currentLocationSource: "Using your current location",
    searchedLocationSource: "Selected from search",
    pinnedLocationSource: "Set by moving the map pin",
    savedLocationSource: "Saved from your last search",
    coordinates: "Coordinates",
    back: "Back",
  },
} as const;

export type Copy = typeof en;
