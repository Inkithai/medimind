export type PrepCategory =
  | "product"
  | "medical"
  | "rag"
  | "safety"
  | "architecture"
  | "data"
  | "clinical"
  | "care"
  | "differentiation"
  | "decisions"
  | "limitations"
  | "scale"
  | "privacy"
  | "competition";

export interface PrepItem {
  id: string;
  category: PrepCategory;
  q: string;
  say: string;
  answer: string;
  hard?: boolean;
}

export const PREP_CATEGORIES: Array<{ id: PrepCategory; label: string; blurb: string }> = [
  { id: "product", label: "Product", blurb: "What MediMind is, who it is for, and the one-sentence pitch." },
  { id: "medical", label: "Medical intelligence", blurb: "Extraction, timeline, labs, and what the system actually computes." },
  { id: "rag", label: "AI / RAG", blurb: "How Ask AI is grounded, cited, and refused when evidence is missing." },
  { id: "safety", label: "Safety", blurb: "Interactions, duplicates, dosage, allergies, confidence, and consult cues." },
  { id: "architecture", label: "Architecture", blurb: "Modules, pipeline, storage split, and why safety is a separate service." },
  { id: "data", label: "Data / FHIR / guidelines", blurb: "What is stored, FHIR import/export, and living-guideline status." },
  { id: "clinical", label: "Clinical reasoning", blurb: "What we infer, what we never infer, and how we talk to patients." },
  { id: "care", label: "Doctor recommendation", blurb: "Final-round flow: flag → specialty → location → live directory." },
  { id: "differentiation", label: "Differentiation", blurb: "Vs ChatGPT, vs a portal, vs the other YGC repos." },
  { id: "decisions", label: "Technical decisions", blurb: "Why anonymous, why JSON+vector, why deterministic-first." },
  { id: "limitations", label: "Limitations", blurb: "Honest gaps. Say these first if a judge probes." },
  { id: "scale", label: "Reliability / scale", blurb: "Jobs, quotas, restarts, and what survives a redeploy." },
  { id: "privacy", label: "Privacy / security", blurb: "Anonymous workspace, keys, isolation, and what we do not claim." },
  { id: "competition", label: "Competition / demo", blurb: "YGC rules, demo path, and questions about scoring." },
];

export const PREP_ITEMS: PrepItem[] = [
  // ── Product ──────────────────────────────────────────────
  {
    id: "p1",
    category: "product",
    q: "What is MediMind, in one sentence?",
    say: "A private workspace that turns messy medical files into a timeline, safety checks, lab trends, grounded answers, and a live local-doctor list — without diagnosing.",
    answer:
      "You upload prescriptions, labs, notes, and discharge summaries. We extract them, merge one patient timeline, flag interactions, duplicates, and dosage conflicts, show lab trends in plain language, answer follow-ups only from those files, and if something is high-risk or low-confidence we help you find a real nearby doctor. No account. Not a diagnosis.",
  },
  {
    id: "p2",
    category: "product",
    q: "Who is the user?",
    say: "A patient or caregiver holding a pile of PDFs and photos — not a clinician EHR.",
    answer:
      "The product is patient-facing. A clinician can use the appointment-prep packet, but we do not log into a hospital system, we do not write orders, and we do not replace a pharmacist. The workspace is one anonymous browser session, one patient.",
  },
  {
    id: "p3",
    category: "product",
    q: "Walk me through the product in 30 seconds.",
    say: "Upload → timeline → Safety → labs → Ask → Find Care.",
    answer:
      "Start a workspace. Drop several files. Each file extracts independently. We merge visits, meds, labs, allergies. Open Safety for interactions, duplicates, dosage, allergy. Open Labs for trends. Ask a cross-document question and click the citation. If a high-risk or low-confidence flag exists, Find Local Care asks city and availability and lists live Google Places or OpenStreetMap results.",
  },
  {
    id: "p4",
    category: "product",
    q: "What problem are you solving that Google Drive or ChatGPT does not?",
    say: "Structure plus deterministic safety plus citations — not a chat over raw PDFs.",
    answer:
      "A folder of scans is not a record. ChatGPT will answer fluently and can invent a dose or a doctor. We extract a structured timeline, run code-level interaction and dosage rules that do not depend on the model noticing, and every Ask answer has to cite a retrieved chunk or we cap confidence and say we do not know.",
  },
  {
    id: "p5",
    category: "product",
    q: "Do I need to sign up?",
    say: "No. One tap creates an anonymous workspace.",
    answer:
      "POST /api/v1/anonymous/session mints a user_id and a JWT. The browser stores them in localStorage. There is no email, password, or recovery account. New workspace forgets the key in this browser; stored rows stay until you delete the workspace in Settings.",
  },
  {
    id: "p6",
    category: "product",
    q: "Which languages does the product support?",
    say: "UI in English, Sinhala, and Tamil. Documents can be in many languages; ingredients are normalized to English INN.",
    answer:
      "The interface catalogs are en / si / ta with locale formatting. Extraction keeps printed brand names as written, but active ingredients are mapped to English generic names so two prescriptions in different languages can still match. Translation confidence is scored separately from OCR confidence.",
  },
  {
    id: "p7",
    category: "product",
    q: "Is this a medical device?",
    say: "No. It is a record navigator and flagging tool.",
    answer:
      "We do not claim CE, FDA, or any clinical certification. Copy on landing, Safety, Ask, and Care says observations are not diagnoses and you should not start or stop a medicine from this app. That is a product boundary, not a disclaimer we hide in the footer.",
  },

  // ── Medical intelligence ─────────────────────────────────
  {
    id: "m1",
    category: "medical",
    q: "What document types can you extract?",
    say: "Prescription, lab report, discharge summary, consultation note, imaging report, procedure report — plus other if it still has clinical fields.",
    answer:
      "The extractor pins a free-form model type onto that closed list in document_types.py. Non-medical files are rejected before they pollute the record. Magic-byte checks reject a .pdf that is not actually a PDF.",
  },
  {
    id: "m2",
    category: "medical",
    q: "How do you merge many files into one timeline?",
    say: "We flatten pages, group by patient name, sort by a shared date convention, and roll up meds, labs, and clinical events.",
    answer:
      "build_patient_timeline in medical_extractor.py. Same-prescription scans get a shared prescription_group so one paper photographed twice is not two prescriptions. Conflicting facts can be quarantined in Trust Review before they enter trends or Ask.",
  },
  {
    id: "m3",
    category: "medical",
    q: "How do lab trends work? Is that the LLM?",
    say: "No. Pure Python. Direction, range crossings, recovery, unit clash.",
    answer:
      "lab_trends.py parses values with thousands-aware rules. Mixed units such as mg/dL vs mmol/L are declined, not converted by guess. The sentence on the Labs page is filled from those numbers. We do not ask a model ‘is this getting worse?’",
  },
  {
    id: "m4",
    category: "medical",
    q: "Do you extract diagnoses from symptoms?",
    say: "No. Diagnoses only if the document names them.",
    answer:
      "The extraction contract has separate arrays for diagnoses, symptoms, procedures, vitals, and imaging. The prompt and the code both refuse to promote a symptom, a medicine, or a lab into a diagnosis. Event dates stay separate from the document date.",
  },
  {
    id: "m5",
    category: "medical",
    q: "How do you handle scanned photos vs digital PDFs?",
    say: "Text layer if it exists; optional Tesseract OCR; otherwise vision. Digital quotes get a real PDF rectangle.",
    answer:
      "Digital PDFs go through pdfplumber. Scanned pages try Tesseract if installed, then the vision model. PyMuPDF searches the original PDF for the quote so the highlight is deterministic. If we cannot locate a box we show page plus quote and do not invent a rectangle.",
  },
  {
    id: "m6",
    category: "medical",
    q: "What if I upload the same file twice?",
    say: "Byte-identical files are skipped. Same prescription in two photos is grouped, not deleted.",
    answer:
      "content_sha256 skips CBC_Report.pdf and CBC_Report (1).pdf before extraction. document_dedup.py tags copies of one prescription so duplicate detection counts prescriptions, not files. Nothing is silently deleted.",
  },
  {
    id: "m7",
    category: "medical",
    q: "Can the user correct a wrong extraction?",
    say: "Yes. Append-only corrections. Original values stay.",
    answer:
      "On My Documents, Correct & Audit writes an immutable event with original, previous, and new value. The timeline, safety, labs, and vector index rebuild. Trust Review lets you pick an authoritative source or reopen a conflict. Unresolved conflicts are quarantined from Ask and trends.",
  },
  {
    id: "m8",
    category: "medical",
    q: "Do you track vitals as well as labs?",
    say: "Yes — a separate vital-trends engine, same idea as labs.",
    answer:
      "vital_trends.py looks at BP, pulse, SpO2, weight, temperature, respiratory rate, glucose. Patient-reported home readings can be folded in and tagged patient_reported. Early-warning and deterioration views sit on top of those series. Still not a diagnosis.",
  },

  // ── AI / RAG ─────────────────────────────────────────────
  {
    id: "r1",
    category: "rag",
    q: "How does Ask AI stay grounded?",
    say: "Three layers: prompt, isolation, verification.",
    answer:
      "The system prompt refuses diagnosis and dose changes. Retrieved text is fenced as data and instruction-shaped lines are defanged. After the model answers we drop citations it invented, fix dates from chunk metadata, and cap uncited answers at 0.5 confidence. The UI only opens a source on an exact filename match.",
  },
  {
    id: "r2",
    category: "rag",
    q: "What happens if the vector index is empty or stale?",
    say: "We detect it and rebuild from the saved timeline instead of answering from nothing.",
    answer:
      "Before retrieval we compare a timeline fingerprint and chunk count. After a correction or conflict decision the index is replaced. If VECTOR_STORE=supabase and the chunks table is missing, Q&A returns 502 with a migration hint, not a fake empty answer.",
  },
  {
    id: "r3",
    category: "rag",
    q: "Do you use the same model for extraction and answering?",
    say: "Same provider layer, different jobs and prompts.",
    answer:
      "LLM_PROVIDER is groq, gemini, or a generic OpenAI-compatible endpoint. Extraction uses vision plus a strict JSON schema. Cross-check has its own schema. Ask uses intent routing and only retrieved chunks. Groq/Gemini have no embeddings API — embeddings are OpenAI if keyed, otherwise local MiniLM.",
  },
  {
    id: "r4",
    category: "rag",
    q: "How do follow-up questions work? ‘Was that safe?’",
    say: "We rewrite the follow-up and we also keep a deterministic entity focus.",
    answer:
      "conversation.py rewrites ‘was that safe?’ into a self-contained query. Independently we track which medications, labs, and documents are in focus from the patient’s own vocabulary, so the subject survives even if the rewrite is weak. Sessions are in memory unless persisted — a restart can 404 an old session id.",
  },
  {
    id: "r5",
    category: "rag",
    q: "Can a malicious PDF jailbreak Ask AI?",
    say: "We treat retrieved documents as untrusted data.",
    answer:
      "_neutralize_injection plus a <patient_records> fence, and the instruction is restated after the block. Invented citations are stripped. This is defense in depth, not a proof against every attack. We do not claim formal red-teaming.",
  },
  {
    id: "r6",
    category: "rag",
    q: "Why not just put the whole record in the prompt?",
    say: "Intent-routed retrieval keeps the answer on the right evidence type.",
    answer:
      "Questions are classified as medication, safety, lab, trend, allergy, timeline, change, or general. Candidates are filtered to matching structured chunks. Trend and change questions need at least two dated sources. If nothing matches we answer without calling the model rather than free-associate.",
  },
  {
    id: "r7",
    category: "rag",
    q: "What model are you on today?",
    say: "Configurable. Gemini 3.6 Flash is the current recommended multimodal default.",
    answer:
      "Groq default is gpt-oss-120b plus a Qwen vision model. Gemini 2.0 Flash was retired; we default to 3.6 Flash. Operators set LLM_PROVIDER and a key. The retry ladder — strict schema, then json_object, then plain text — is the same across providers.",
  },

  // ── Safety ───────────────────────────────────────────────
  {
    id: "s1",
    category: "safety",
    q: "Where does prescription cross-checking live?",
    say: "In a dedicated service: medication_safety.py — not inside extraction.",
    answer:
      "Extraction only builds a timeline. medication_safety.py reads that timeline and writes analyses. HTTP is GET /api/v1/medication-safety and POST /api/v1/medication-safety/reanalyze. The Safety page is the dedicated view. The extractor re-exports the old function name so nothing else broke.",
  },
  {
    id: "s2",
    category: "safety",
    q: "Is the interaction check just the LLM?",
    say: "No. A curated knowledge base always runs. The LLM is a broad extra pass.",
    answer:
      "drug_interactions.py matches normalized ingredients against textbook pairs — anticoagulant plus NSAID, nitrate plus PDE5, warfarin plus cipro, and so on. If the model misses it, the KB still flags it. KB findings are tagged curated_knowledge_base so grading does not cap them.",
  },
  {
    id: "s3",
    category: "safety",
    q: "How do you score confidence on a flag?",
    say: "Code grades the finding. Model self-scores are not trusted raw.",
    answer:
      "evidence_grading.py. Deterministic or KB findings keep their score — typically 0.95–0.97. Model-only pharmacology is capped at 0.6 and we keep the model’s original number visible. That is how a flashy 0.95 hallucination cannot outrank an arithmetic duplicate.",
  },
  {
    id: "s4",
    category: "safety",
    q: "What about duplicates and dosage?",
    say: "Duplicates are set-equality on ingredient plus numeric dose. Dosage is arithmetic against adult limits.",
    answer:
      "detect_exact_duplicate_medications counts distinct prescription_group values. dosage_rules.py converts to mg when the conversion is exact or a documented standard strength; otherwise the dose is ‘not evaluated’, never guessed. Ended courses are listed as excluded_inactive, not dropped.",
  },
  {
    id: "s5",
    category: "safety",
    q: "Allergy to penicillin, prescribed amoxicillin — do you catch that?",
    say: "Yes, in code, even if the model misses it.",
    answer:
      "drug_allergy_rules.py matches normalized ingredients to allergen classes and names. Negative statements like ‘no known drug allergies’ are recognized, and exceptions like ‘except penicillin’ still match. Fail-open: a KB error never kills the rest of the report.",
  },
  {
    id: "s6",
    category: "safety",
    q: "Do you check kidney function or drug–lab pairs?",
    say: "Yes — extra deterministic engines, still no replacement dose.",
    answer:
      "renal_hepatic_dosing.py flags drugs that usually need review when eGFR/creatinine or LFTs are off. drug_lab_interactions.py flags things like ACE inhibitor plus high potassium. condition_contraindications.py flags NSAID plus ulcer, and similar documented pairs. We surface a reason to ask the prescriber. We never print a new dose.",
  },
  {
    id: "s7",
    category: "safety",
    q: "When do you tell the user to see a doctor?",
    say: "High-risk flags, low confidence, and any risk/allergy/dosage Ask question.",
    answer:
      "Safety and Care show a professional-care cue. Ask sets recommend_professional_consult with a consult_reason. consult_triage.py routes each finding to pharmacist or doctor with urgency and will not de-escalate a non-overlapping historical pair into ‘you are fine’.",
  },
  {
    id: "s8",
    category: "safety",
    q: "Is your interaction table complete?",
    hard: true,
    say: "No. It is a guaranteed floor, not DrugBank.",
    answer:
      "The KB is a small set of unambiguous textbook pairs. Dose-dependent, rare, and patient-specific interactions stay with the LLM pass and are capped. Absence of a flag is not a safety endorsement. Say that sentence if they push.",
  },

  // ── Architecture ─────────────────────────────────────────
  {
    id: "a1",
    category: "architecture",
    q: "Draw the pipeline.",
    say: "File → extract → validate → timeline → three derived views: safety service, lab trends, search index.",
    answer:
      "Upload is async with per-file progress. Extraction is medical_extractor.py. Safety is medication_safety.py. Labs are lab_trends.py. Ask is retrieval.py over Chroma or Supabase chunks. Find Care is a later, optional path from existing flags. Originals go to Cloudinary; JSON to Supabase; embeddings to the chosen vector store.",
  },
  {
    id: "a2",
    category: "architecture",
    q: "Why is safety not inside the extractor?",
    say: "Different job. Extract writes a timeline. Safety reads it and writes analyses.",
    answer:
      "Judges comparing repos look for a dedicated medication-safety service. Ours is medication_safety.py plus GET /api/v1/medication-safety plus the /safety view. Keeping it out of the 3k-line extractor also means a KB change does not touch OCR or vision.",
  },
  {
    id: "a3",
    category: "architecture",
    q: "What is the backend stack?",
    say: "FastAPI, one patient per anonymous JWT, Supabase, Cloudinary, Groq or Gemini.",
    answer:
      "api.py is a thin HTTP wrapper. Auth is HS256 JWT plus X-User-Id must match the claim. VECTOR_STORE=supabase is what we recommend on Railway so we do not need a volume. Jobs can be in-memory or a Supabase jobs table.",
  },
  {
    id: "a4",
    category: "architecture",
    q: "Frontend stack?",
    say: "React, TypeScript, Vite, Tailwind. English, Sinhala, Tamil.",
    answer:
      "Anonymous AuthContext provisions the workspace. Pages map to the API. Accessibility work covers landmarks, keyboard, live regions, and reduced motion. Find Care uses Leaflet tiles; the Google key never ships to the browser.",
  },
  {
    id: "a5",
    category: "architecture",
    q: "How many moving parts does an upload touch?",
    say: "Per file: read, extract, save. Once: timeline, safety, dosage, labs, triage, persist, then index.",
    answer:
      "We persist the record before indexing on purpose. If the process dies during embeddings, the documents are already in Supabase. Indexing is derived data and can rebuild. One bad file does not fail the batch.",
  },

  // ── Data / FHIR ──────────────────────────────────────────
  {
    id: "d1",
    category: "data",
    q: "What do you persist?",
    say: "Original file, extracted JSON, snapshot, optional chunks. Not raw tokens.",
    answer:
      "Cloudinary holds the PDF or image. Supabase documents is append-only extraction rows. patient_snapshots is a cache of timeline plus safety plus labs. chunks is the vector table if VECTOR_STORE=supabase. Corrections and conflicts have their own tables.",
  },
  {
    id: "d2",
    category: "data",
    q: "Do you support FHIR?",
    say: "Yes — conservative R4 export, and a lossy import into our extraction shape.",
    answer:
      "GET /api/v1/export?format=fhir emits Patient, MedicationStatement, Observation, AllergyIntolerance, Provenance. Unmapped codes stay unmapped. POST /api/v1/import/fhir parses a Bundle into our document shape. We do not claim a full EHR FHIR server.",
  },
  {
    id: "d3",
    category: "data",
    q: "What about clinical guidelines?",
    say: "Pinned reference texts plus a living-guidelines registry. Auto-refresh is opt-in.",
    answer:
      "SAMHSA opioid guidance and WHO EML antidote tables are parsed deterministically when configured. GET /api/v1/guidelines/status reports staleness. POST refresh needs a manifest URL. If Neo4j is unset, those graphs simply stay empty — fail-open.",
  },
  {
    id: "d4",
    category: "data",
    q: "Can I delete my data?",
    say: "Yes. Delete one document or the whole workspace. That is different from ‘forget this browser’.",
    answer:
      "DELETE /api/v1/documents/{id} removes the file and rebuilds every derived view. DELETE /api/v1/workspace wipes originals, rows, chunks, corrections, jobs, conversations. Settings keeps ‘remove from this browser’ as a local-key forget only.",
  },
  {
    id: "d5",
    category: "data",
    q: "Why JSON documents instead of a normalized EHR schema?",
    hard: true,
    say: "The source of truth is the file. We derive views. We did add optional normalized tables later.",
    answer:
      "A prescription is a document, not a row we want to silently overwrite. Derived timelines and safety reports rebuild from those documents after every correction. We later added optional clinical_* tables and a profile API; if the migration is not applied, the JSON path still works.",
  },

  // ── Clinical reasoning ───────────────────────────────────
  {
    id: "c1",
    category: "clinical",
    q: "Are you diagnosing the patient?",
    say: "No. We flag what is already in the record.",
    answer:
      "We never infer a disease from a medicine or a lab. Symptom intake cross-references the record and still says it is not a diagnosis. Care specialty matching is a search category — cardiologist, pharmacist — not a clinical conclusion.",
  },
  {
    id: "c2",
    category: "clinical",
    q: "How do you decide cardiologist vs GP vs pharmacist?",
    say: "Medication flags go to pharmacist or the prescribing doctor. Other flags use conservative term matches. Ambiguous goes to GP.",
    answer:
      "specialty_mapping.py. high_severity_interaction, allergy, and dosage types map to pharmacy. Heart, kidney, lung, neuro, derm terms in the evidence pick a specialty. No match → General Physician. The reason string is shown on the card.",
  },
  {
    id: "c3",
    category: "clinical",
    q: "What if two drugs were not taken at the same time?",
    say: "We time the finding. Non-overlap is not presented as a live interaction.",
    answer:
      "risk_timeline.py builds treatment windows from dates and durations. consult_triage drops urgency to routine and marks is_historical when status is not_concurrent. The Risk Timeline page shows when each flag was actually live.",
  },
  {
    id: "c4",
    category: "clinical",
    q: "Do you invent follow-up deadlines?",
    say: "No. The user picks reminder dates. We do not invent clinical due dates.",
    answer:
      "follow_up.py builds a stable queue from existing flags and trends. Completion and reminder dates stay in the browser. .ics export is optional. Push and email reminders are not implemented.",
  },

  // ── Care / doctor recommendation ─────────────────────────
  {
    id: "k1",
    category: "care",
    q: "Show me the Final Round feature.",
    say: "Flag → ask city and availability → live API → list. No agents.",
    answer:
      "Find Local Care at /care. GET /api/v1/care-recommendations lists only existing high-risk or low-confidence flags. The user picks one, types a city, picks this week or evenings, and POST /search hits Google Places or OpenStreetMap. Cards show name, specialty, address, distance, rating or phone if the source published them.",
  },
  {
    id: "k2",
    category: "care",
    q: "Which API do you use for doctors?",
    say: "Google Places API (New) when keyed; otherwise OpenStreetMap Nominatim plus Overpass. Geoapify if that key is set.",
    answer:
      "PROVIDER_DIRECTORY_SOURCE or CARE_PROVIDER selects the source. Keys stay on the server. Default is keyless OSM so the page works without billing. Hybrid tries Geoapify then OSM. We never seed, mock, or hard-code a clinic.",
  },
  {
    id: "k3",
    category: "care",
    q: "What if the API returns nothing?",
    say: "Empty list, a clear message, suggest a wider area. No fake doctors.",
    answer:
      "The payload includes no_results_message. The UI does not fill sample cards. Missing rating or phone renders ‘Not available’. An unnamed listing is dropped. Fabricated doctor data is an automatic competition deduction — we designed against that.",
  },
  {
    id: "k4",
    category: "care",
    q: "Does availability mean you can book a slot?",
    hard: true,
    say: "No. We only rank on published opening-hours text when we can read it safely.",
    answer:
      "Preferences are any, today, this week, evenings, weekends. If hours are missing or are OSM compact syntax we cannot parse, availability is not used. The card says regular hours are not appointment availability. There is no booking integration.",
  },
  {
    id: "k5",
    category: "care",
    q: "Is Find Care the same as Find Local Care?",
    say: "Two pages. /care is the competition path from a clinical flag. /find-care is a map directory.",
    answer:
      "/care is evidence → specialty → city → live ranked providers plus a consultation pack. /find-care is search-as-you-type or GPS, map pin, then hospitals, clinics, pharmacies, labs, doctors in a radius. Same ‘no fabricated fields’ rule. /care is what the 5-minute demo should use.",
  },
  {
    id: "k6",
    category: "care",
    q: "Do you send the patient’s medicines to Google?",
    say: "No. The directory only gets a generic category and the city.",
    answer:
      "The live request is ‘cardiologist near Negombo’, not the warfarin explanation. Consultation-pack contents stay on our side and are not mixed into provider records.",
  },
  {
    id: "k7",
    category: "care",
    q: "How do you rank doctors?",
    say: "Specialty match, then distance, then rating and hours only if the source sent them.",
    answer:
      "provider_ranking.py. Weights are disclosed on the card. We never say ‘best doctor’. Score is a directory match, not clinical quality.",
  },

  // ── Differentiation ──────────────────────────────────────
  {
    id: "f1",
    category: "differentiation",
    q: "How is this different from ChatGPT with a PDF plugin?",
    say: "Deterministic safety, citations that are verified, and a live doctor list with no invented clinics.",
    answer:
      "A general model will happily write a dose and a clinic name. Our interaction and dosage floors run in Python. Ask drops fake citations. Care listings are live public data or an empty state. That is the product.",
  },
  {
    id: "f2",
    category: "differentiation",
    q: "The other team has a dedicated medication-safety service. Do you?",
    say: "Yes. medication_safety.py, GET /api/v1/medication-safety, /safety view.",
    answer:
      "It used to live next to extraction. We split it so the architecture matches the job: extract writes the record, safety reads the record and writes analyses. The engines themselves — interactions, dosage, allergy, duplicates — were already real.",
  },
  {
    id: "f3",
    category: "differentiation",
    q: "They have login and a relational EHR. Why don’t you?",
    hard: true,
    say: "Anonymous-by-design for a demo and for patients who will not create an account. It is a choice, not a missing login screen.",
    answer:
      "We issue a workspace key, not an identity. That costs us multi-device recovery. We accepted that. Optional normalized tables exist now; the live path still works from JSON documents plus a vector index.",
  },
  {
    id: "f4",
    category: "differentiation",
    q: "What is actually novel here?",
    say: "Language-independent med matching, deterministic trends, graded evidence, and a live directory that refuses to lie.",
    answer:
      "Ingredients as English INN across Tamil or Sinhala scripts. Lab math that will not invent a unit conversion. Confidence that distinguishes ‘we computed this’ from ‘the model recalled this’. Care that shows Not available instead of a fake star rating.",
  },

  // ── Technical decisions ──────────────────────────────────
  {
    id: "t1",
    category: "decisions",
    q: "Why Groq or Gemini instead of a local clinical model?",
    say: "We need vision plus structured JSON on a free or cheap tier for a student demo.",
    answer:
      "The provider is swappable because we only use the OpenAI SDK. A local model would need GPU and still would not be a validated drug database. The important bet is deterministic checks around the model, not the logo on the API key.",
  },
  {
    id: "t2",
    category: "decisions",
    q: "Why Chroma and also Supabase chunks?",
    say: "Chroma is easy locally. Supabase chunks survive a free-tier container restart.",
    answer:
      "VECTOR_STORE=chroma writes to disk and needs a volume. VECTOR_STORE=supabase stores embeddings in Postgres and does brute-force cosine. We recommend supabase for Railway. Switching backends means re-upload or rebuild.",
  },
  {
    id: "t3",
    category: "decisions",
    q: "Why not agentic multi-step planning for Find Care?",
    say: "The brief forbids the need for it. Detect flag, ask two questions, call the API, show results.",
    answer:
      "YGC Final Round section 3 says a straightforward flow is sufficient. We did not add an agent that browses the web or books clinics. That keeps the demo predictable and the data trail auditable.",
  },
  {
    id: "t4",
    category: "decisions",
    q: "Why keep an LLM pass on safety at all?",
    say: "Coverage. The KB is the floor; the model can surface pairs we did not hard-code — then we cap them.",
    answer:
      "A 20-rule table will miss things. The LLM pass is labeled model_knowledge, confidence-capped, and worded as ‘ask a pharmacist’. If the provider is down, the deterministic passes still run.",
  },

  // ── Limitations ──────────────────────────────────────────
  {
    id: "l1",
    category: "limitations",
    q: "What are you weakest at?",
    hard: true,
    say: "Not clinically validated. Interaction table is small. No booking. Anonymous means no account recovery.",
    answer:
      "We have not run a formal clinical evaluation set. Renal and pediatric dosing are explicitly out of scope of the arithmetic table. Conversations and jobs can be in-memory. Living-guideline auto-refresh needs a manifest we do not ship. Secure messaging is a store, not SMS to a real clinic.",
  },
  {
    id: "l2",
    category: "limitations",
    q: "What if extraction is wrong?",
    say: "The user can correct it. Until then, low-confidence fields stay labeled and can unlock Find Care as a review path, not as truth.",
    answer:
      "Vision on handwriting is capped at 0.85. Brand-to-generic mapping is treated as inference, not transcription. Corrections are append-only. We would rather show a low score than a clean wrong med list.",
  },
  {
    id: "l3",
    category: "limitations",
    q: "Does ‘no finding’ mean the prescription is safe?",
    hard: true,
    say: "No. It means no rule fired.",
    answer:
      "Many drugs have no dosage rule. The interaction KB is not complete. Individual factors — pregnancy, weight, undocumented OTCs — may be absent from the files. The report text says this. Repeat it if they ask twice.",
  },
  {
    id: "l4",
    category: "limitations",
    q: "Can two people share one workspace from two phones?",
    say: "Not as a product feature. The key lives in one browser.",
    answer:
      "You can paste the token, but we did not build multi-device accounts, email recovery, or family switching. One workspace, one patient, one browser is the contract.",
  },
  {
    id: "l5",
    category: "limitations",
    q: "Is FHIR import lossless?",
    say: "No. We collapse FHIR into our extraction fields on purpose.",
    answer:
      "fhir_ingestion.py is lossy-by-design. Extensions, contained resources, and unmapped codes do not survive. Export is conservative in the other direction. Do not claim ‘full interoperability’.",
  },

  // ── Scale / reliability ──────────────────────────────────
  {
    id: "z1",
    category: "scale",
    q: "What happens when Gemini rate-limits mid-upload?",
    say: "Per-file failure, circuit breaker, other files still save. We do not retry a hard quota.",
    answer:
      "A shared worker pool defaults to one concurrent extraction. 429s honor Retry-After. Daily quota or a retired model fails immediately and queued files are not sent into the same wall. The user sees a short message, not a stack trace.",
  },
  {
    id: "z2",
    category: "scale",
    q: "Does a server restart lose the patient?",
    say: "Documents and snapshots survive. In-memory chats and jobs may not.",
    answer:
      "Supabase and Cloudinary are durable. If VECTOR_STORE=chroma without a volume, the index dies and Q&A rebuilds or 502s honestly. USE_SUPABASE_JOBS can persist jobs. We tell the UI when records are saved even if indexing is only partial.",
  },
  {
    id: "z3",
    category: "scale",
    q: "Would this survive a hospital deployment?",
    hard: true,
    say: "Not as-is. It is a demo-grade anonymous workspace.",
    answer:
      "We would need authenticated identities, BAAs, audit to a SIEM, a real interaction database, HA jobs, and a clinical evaluation. What transfers is the pipeline shape: extract, deterministic safety, grounded RAG, live directory with no fake rows.",
  },

  // ── Privacy ──────────────────────────────────────────────
  {
    id: "v1",
    category: "privacy",
    q: "How is data isolated?",
    say: "Application-scoped user_id after JWT plus header match. Not magic RLS.",
    answer:
      "Every query is keyed by the verified user_id. Cloudinary path is mediscan/<user_id>/. Chroma collection names are sanitized from that id. RLS is enabled with no policies; the service-role key bypasses it. Do not say ‘Postgres RLS protects you’.",
  },
  {
    id: "v2",
    category: "privacy",
    q: "Where do API keys live?",
    say: "Server only. No VITE_ Google key.",
    answer:
      "LLM, Supabase service role, Cloudinary, Google Places, Geoapify are backend env. The browser only gets a session JWT. Care adapters log provider errors server-side and return a neutral message.",
  },
  {
    id: "v3",
    category: "privacy",
    q: "Is this HIPAA compliant?",
    hard: true,
    say: "We do not claim HIPAA, GDPR certification, or a BAA.",
    answer:
      "Anonymous workspaces reduce account surface, but the files are still health data on Supabase and Cloudinary. A real deployment would need contracts, encryption-at-rest evidence, and access logs we only partially have via audit.record.",
  },
  {
    id: "v4",
    category: "privacy",
    q: "What is in the audit trail?",
    say: "Workspace events: upload, export, safety reanalyze, care search, corrections. Not a full SIEM.",
    answer:
      "audit.py records actions with the user_id. Clinician feedback and finding lifecycle add more. We do not ship an admin console for those logs in the patient UI.",
  },

  // ── Competition ──────────────────────────────────────────
  {
    id: "y1",
    category: "competition",
    q: "Map your app to the YGC Final Round brief.",
    say: "Round 1 is the record. Round 2 is live local doctors. Nineteen of nineteen.",
    answer:
      "R1–R8: extract, timeline, cross-check, labs, plain language, multi-doc Q&A, confidence, consult cue. R9–R14: specialty, city, availability, Google or OSM, result cards, empty state. R15–R16: real listings, no diagnosis. R17–R19: the flow, this README, a 4:30 demo script.",
  },
  {
    id: "y2",
    category: "competition",
    q: "How will you demo in five minutes?",
    say: "Disclaimer, upload, history, Safety, labs, one Ask, Find Care.",
    answer:
      "docs/DEMO_RUNBOOK.md. Thirty seconds on anonymous plus not-a-diagnosis. One minute upload. History with a page link. Safety with a real flag and a confidence. Labs sparkline. One cross-document question with a citation. Find Care with a city in Sri Lanka and live listings. If extraction overruns, switch to the pre-validated workspace and say so.",
  },
  {
    id: "y3",
    category: "competition",
    q: "Why should we trust you did not fake the clinics?",
    say: "There is no clinic table in the repo. The response is labeled Live provider data — source.",
    answer:
      "provider_sources.py calls Google, Nominatim, Overpass, or Geoapify at request time. Tests assert those URLs exist and that the factory must not substitute mock data. Zero results stay zero. That is also how we avoid the automatic deduction in section 6.",
  },
  {
    id: "y4",
    category: "competition",
    q: "What will you say if extraction fails live?",
    say: "Tell the truth. Use the prepared workspace. Do not type a fake flag.",
    answer:
      "Independent per-file progress is the feature. Name the provider error in one clause — quota, blurry image — then continue from a workspace you already validated this morning. Inventing a safety flag or a doctor is worse than a slow upload.",
  },
  {
    id: "y5",
    category: "competition",
    q: "Scoring is 30 / 30 / 20 / 10 / 10. Where do you win?",
    say: "AI depth is the deterministic safety plus grounded Ask. Execution is real APIs and empty states. Originality is explainable specialty and ranking.",
    answer:
      "Usefulness is a phone number and a Maps link on a real listing. Presentation is the disclaimer on every safety and care screen. We lose points if we over-claim diagnosis, completeness, or HIPAA — so we will not.",
  },
  {
    id: "y6",
    category: "competition",
    q: "Can medical samples be synthetic?",
    say: "Yes. Doctor data cannot.",
    answer:
      "Section 4 of the brief: Round 1 de-identified or synthetic documents are allowed. Doctor and clinic rows must come from a public directory. We kept that split on purpose.",
  },
];
