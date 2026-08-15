import type { PatientSnapshot, Timeline } from "../types/api";

/**
 * Turns keywords found in already-extracted records into a *search signal*
 * for the care directory.
 *
 * This is deliberately not a diagnosis engine. It reports the keyword it saw,
 * the file it came from, and the specialty it used to bias the directory
 * search, so the UI can show the full chain:
 *   keyword detected → potential specialty → professional verification.
 */

export interface SpecialtyOption {
  value: string;
  label: string;
}

export interface SpecialtySuggestion {
  /** Directory search term, e.g. "Gastroenterologist". */
  specialty: string;
  label: string;
  /** The literal keyword found in the records, e.g. "abdominal". */
  keyword: string;
  /** Source file names the keyword appeared in. */
  evidence: string[];
  /** Findings that carry low extraction confidence. */
  lowConfidenceCount: number;
}

const LOW_CONFIDENCE_THRESHOLD = 0.6;

/** Specialties offered in the picker. Values double as Google search terms. */
export const SPECIALTY_OPTIONS: SpecialtyOption[] = [
  { value: "cardiologist", label: "Cardiologist" },
  { value: "dermatologist", label: "Dermatologist" },
  { value: "endocrinologist", label: "Endocrinologist" },
  { value: "ent", label: "ENT specialist" },
  { value: "gastroenterologist", label: "Gastroenterologist" },
  { value: "general practitioner", label: "General practitioner" },
  { value: "gynecologist", label: "Gynecologist" },
  { value: "nephrologist", label: "Nephrologist" },
  { value: "neurologist", label: "Neurologist" },
  { value: "oncologist", label: "Oncologist" },
  { value: "ophthalmologist", label: "Ophthalmologist" },
  { value: "orthopedic surgeon", label: "Orthopaedic surgeon" },
  { value: "pediatrician", label: "Paediatrician" },
  { value: "psychiatrist", label: "Psychiatrist" },
  { value: "pulmonologist", label: "Pulmonologist" },
  { value: "rheumatologist", label: "Rheumatologist" },
  { value: "urologist", label: "Urologist" },
];

/** Keyword → potential specialty. Ordered: the first match wins. */
const KEYWORD_SPECIALTY: Array<{ keywords: string[]; specialty: string }> = [
  { keywords: ["abdominal", "gastric", "gastritis", "liver", "hepatic", "colon", "endoscopy"], specialty: "gastroenterologist" },
  { keywords: ["cardiac", "heart", "ecg", "ekg", "hypertension", "cholesterol", "ldl"], specialty: "cardiologist" },
  { keywords: ["hba1c", "diabetes", "thyroid", "tsh", "insulin"], specialty: "endocrinologist" },
  { keywords: ["creatinine", "kidney", "renal", "egfr"], specialty: "nephrologist" },
  { keywords: ["asthma", "copd", "spirometry", "respiratory", "wheeze"], specialty: "pulmonologist" },
  { keywords: ["migraine", "seizure", "neuropathy", "epilepsy"], specialty: "neurologist" },
  { keywords: ["fracture", "joint pain", "arthritis", "ligament", "orthopaedic", "orthopedic"], specialty: "orthopedic surgeon" },
  { keywords: ["rash", "eczema", "psoriasis", "dermatitis"], specialty: "dermatologist" },
  { keywords: ["urinary", "prostate", "bladder"], specialty: "urologist" },
  { keywords: ["vision", "retina", "cataract", "intraocular"], specialty: "ophthalmologist" },
];

export function specialtyLabel(value: string): string {
  const match = SPECIALTY_OPTIONS.find((option) => option.value === value.trim().toLowerCase());
  if (match) return match.label;
  const trimmed = value.trim();
  return trimmed ? trimmed.charAt(0).toUpperCase() + trimmed.slice(1) : trimmed;
}

interface TextFragment {
  text: string;
  file: string | null;
  confidence: number;
}

function collectFragments(timeline: Timeline | undefined): TextFragment[] {
  if (!timeline) return [];
  const fragments: TextFragment[] = [];
  for (const visit of timeline.visits || []) {
    const file = visit._source?.file || null;
    if (visit.clinical_notes) {
      fragments.push({ text: visit.clinical_notes, file, confidence: visit.overall_confidence });
    }
    for (const lab of visit.lab_results || []) {
      fragments.push({ text: lab.test_name, file, confidence: lab.confidence });
    }
    for (const medication of visit.medications || []) {
      fragments.push({ text: medication.name, file, confidence: medication.confidence });
    }
    for (const field of visit.illegible_or_low_confidence_fields || []) {
      fragments.push({ text: field, file, confidence: 0 });
    }
  }
  return fragments;
}

/**
 * Derive a suggested specialty from the record, or null when nothing in the
 * record points anywhere. Never guesses when there is no keyword hit.
 */
export function suggestSpecialty(snapshot: PatientSnapshot | null): SpecialtySuggestion | null {
  if (!snapshot) return null;
  const fragments = collectFragments(snapshot.patient_timeline);
  if (!fragments.length) return null;

  const lowConfidenceCount = fragments.filter(
    (fragment) => fragment.confidence < LOW_CONFIDENCE_THRESHOLD
  ).length;

  for (const rule of KEYWORD_SPECIALTY) {
    for (const keyword of rule.keywords) {
      const hits = fragments.filter((fragment) => fragment.text.toLowerCase().includes(keyword));
      if (!hits.length) continue;
      const evidence = [...new Set(hits.map((hit) => hit.file).filter((file): file is string => Boolean(file)))];
      return {
        specialty: rule.specialty,
        label: specialtyLabel(rule.specialty),
        keyword,
        evidence,
        lowConfidenceCount,
      };
    }
  }
  return null;
}
