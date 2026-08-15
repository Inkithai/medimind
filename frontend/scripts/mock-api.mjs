/**
 * Local mock of the MediMind API, used only to exercise the Find Care page in
 * a browser without Google/Supabase credentials. Not shipped or imported by
 * the app. Run: node scripts/mock-api.mjs
 */
import { createServer } from "node:http";

const PORT = Number(process.env.MOCK_API_PORT || 8000);

const FACILITIES = [
  {
    id: "g1",
    name: "Asiri Medical Hospital",
    kind: "hospital",
    latitude: 6.8951,
    longitude: 79.8636,
    distance_km: 3.2,
    address: "21 Kirimandala Mawatha, Colombo 05, Sri Lanka",
    rating: 4.2,
    user_rating_count: 1245,
    phone: "+94 11 452 3300",
    website: "https://asiri.lk",
    maps_url: "https://maps.google.com/?cid=1111",
    opening_hours: ["Monday: Open 24 hours", "Tuesday: Open 24 hours"],
    open_now: true,
    specialty: "Hospital",
    specialty_match: true,
    source: "Google Places public listing",
  },
  {
    id: "g2",
    name: "Nawaloka Hospital",
    kind: "hospital",
    latitude: 6.9182,
    longitude: 79.8541,
    distance_km: 4.6,
    address: "23 Deshamanya H K Dharmadasa Mawatha, Colombo 00200",
    rating: 3.9,
    user_rating_count: 2310,
    phone: "+94 11 254 4444",
    website: null,
    maps_url: null,
    opening_hours: null,
    open_now: true,
    specialty: null,
    specialty_match: false,
    source: "Google Places public listing",
  },
  {
    id: "g3",
    name: "Durdans Gastroenterology Centre",
    kind: "clinic",
    latitude: 6.9,
    longitude: 79.855,
    distance_km: 1.1,
    address: "3 Alfred Place, Colombo 00300",
    rating: null,
    user_rating_count: null,
    phone: null,
    website: null,
    maps_url: null,
    opening_hours: ["Monday: 8:00 AM – 8:00 PM"],
    open_now: false,
    specialty: "Medical clinic",
    specialty_match: true,
    source: "Google Places public listing",
  },
  {
    id: "g4",
    name: "Union Chemists Pharmacy",
    kind: "pharmacy",
    latitude: 6.905,
    longitude: 79.86,
    distance_km: 0.7,
    address: "417 Galle Road, Colombo 03",
    rating: 4.5,
    user_rating_count: 88,
    phone: "+94 11 257 3000",
    website: null,
    maps_url: null,
    opening_hours: null,
    open_now: null,
    specialty: null,
    specialty_match: false,
    source: "Google Places public listing",
  },
  {
    id: "g5",
    name: "Lanka Hospitals Diagnostics",
    kind: "laboratory",
    latitude: 6.888,
    longitude: 79.87,
    distance_km: 2.4,
    address: "578 Elvitigala Mawatha, Colombo 05",
    rating: 4.0,
    user_rating_count: 1,
    phone: "+94 11 553 0000",
    website: "https://lankahospitals.com",
    maps_url: null,
    opening_hours: ["Monday: 6:00 AM – 10:00 PM"],
    open_now: true,
    specialty: "Medical laboratory",
    specialty_match: false,
    source: "Google Places public listing",
  },
  {
    id: "g6",
    name: "Dr. S. Perera — Consultant Physician",
    kind: "doctor",
    latitude: 6.91,
    longitude: 79.868,
    distance_km: 1.9,
    address: null,
    rating: null,
    user_rating_count: null,
    phone: null,
    website: null,
    maps_url: null,
    opening_hours: null,
    open_now: null,
    specialty: "Doctor",
    specialty_match: false,
    source: "Google Places public listing",
  },
  {
    id: "g7",
    name: "Colombo Wellness Centre",
    kind: "other",
    latitude: 6.897,
    longitude: 79.858,
    distance_km: 5.0,
    address: "12 Marine Drive, Colombo 04",
    rating: 4.8,
    user_rating_count: 34,
    phone: "+94 77 123 4567",
    website: null,
    maps_url: null,
    opening_hours: null,
    open_now: false,
    specialty: null,
    specialty_match: false,
    source: "Google Places public listing",
  },
];

const SNAPSHOT = {
  user_id: "arun",
  patient_timeline: {
    visits: [
      {
        document_type: "other",
        date: "2026-02-11",
        provider_or_doctor: null,
        patient_name: "Arun Kumar",
        medications: [],
        lab_results: [],
        allergies_noted: [],
        clinical_notes: "Patient reports intermittent abdominal pain for three weeks.",
        illegible_or_low_confidence_fields: ["dosage", "date", "provider", "unit", "value"],
        overall_confidence: 0.42,
        _source: { file: "Arun (2).jpg", method: "vision_ocr" },
      },
      {
        document_type: "other",
        date: null,
        provider_or_doctor: null,
        patient_name: "Arun Kumar",
        medications: [],
        lab_results: [],
        allergies_noted: [],
        clinical_notes: "Abdominal ultrasound advised.",
        illegible_or_low_confidence_fields: [],
        overall_confidence: 0.55,
        _source: { file: "Arun (5).jpg", method: "vision_ocr" },
      },
    ],
    medications_timeline: [],
    lab_results_timeline: [],
    known_allergies: [],
  },
  cross_check_report: {},
  lab_trends: {},
  updated_at: "2026-08-15T00:00:00Z",
};

const server = createServer((request, response) => {
  const url = new URL(request.url, `http://${request.headers.host}`);
  response.setHeader("Content-Type", "application/json");
  response.setHeader("Access-Control-Allow-Origin", "*");
  response.setHeader("Access-Control-Allow-Headers", "*");
  if (request.method === "OPTIONS") {
    response.writeHead(204).end();
    return;
  }

  if (url.pathname === "/api/v1/anonymous/session") {
    response.end(JSON.stringify({ user_id: "anon_mock", token: "mock-token" }));
    return;
  }
  if (url.pathname === "/api/v1/health") {
    response.end(JSON.stringify({ status: "ok", version: "mock" }));
    return;
  }
  if (url.pathname === "/api/v1/patient-snapshot") {
    response.end(JSON.stringify(SNAPSHOT));
    return;
  }
  if (url.pathname === "/api/v1/care/facilities") {
    const kind = url.searchParams.get("kind") || "any";
    const scenario = url.searchParams.get("scenario") || process.env.MOCK_SCENARIO || "ok";
    if (scenario === "error") {
      response.writeHead(503).end(
        JSON.stringify({ detail: "The facility directory is temporarily unavailable." })
      );
      return;
    }
    if (scenario === "empty") {
      response.end("[]");
      return;
    }
    const results = kind === "any" ? FACILITIES : FACILITIES.filter((f) => f.kind === kind);
    setTimeout(() => response.end(JSON.stringify(results)), 400);
    return;
  }
  response.writeHead(404).end(JSON.stringify({ detail: "not found" }));
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Mock MediMind API listening on http://0.0.0.0:${PORT}`);
});
