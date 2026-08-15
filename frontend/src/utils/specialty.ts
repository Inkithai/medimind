import type { Timeline } from "../types/api";
import type { CareSpecialty } from "../types/facility";

/**
 * Best-effort, *conservative* suggestion of a clinical specialty from the
 * patient's own records. This is only used to pre-select the Find Care
 * specialty dropdown; it is NOT sent to the backend as a claimed diagnosis
 * and the user can change or clear it. We only suggest when there is a clear
 * keyword signal in the records (medication names / clinical notes).
 */

interface Rule {
  key: string;
  pattern: RegExp;
}

// Keep this aligned with the backend care/taxonomy.py catalog keys.
const RULES: Rule[] = [
  { key: "gastroenterology", pattern: /gastro|gastrit|ulcer|reflux|gerd|hepatit|liver|\bgut\b|colon|endoscop/i },
  { key: "cardiology", pattern: /cardiac|cardio|\bheart\b|hypertens|blood pressure|cholesterol/i },
  { key: "dermatology", pattern: /dermat|eczema|psoriasis|\bskin\b/i },
  { key: "endocrinology", pattern: /diabet|metformin|insulin|glucose|glyburide|gliclazide|thyroid/i },
  { key: "neurology", pattern: /neurolog|epilep|seizure|migraine|\bparkinson/i },
  { key: "pulmonology", pattern: /asthma|copd|inhaler|\blung\b|respirator|pulmon/ },
  { key: "mental_health", pattern: /anxiet|depress|psychiatr|psycholog|bipolar/i },
  { key: "orthopedics", pattern: /fracture|arthrit|orthop|\bbone\b|joint pain/i },
];

// Some medication-name-only signals map to a specialty even without a note.
const MEDICATION_HINTS: Array<{ key: string; pattern: RegExp }> = [
  { key: "gastroenterology", pattern: /omeprazole|pantoprazole|ranitidine|lansoprazole|esomeprazole/i },
  { key: "cardiology", pattern: /atorvastatin|amlodipine|metoprolol|losartan|ramipril/i },
  { key: "endocrinology", pattern: /metformin|insulin|gliclazide|glimepiride/i },
  { key: "pulmonology", pattern: /salbutamol|budesonide|montelukast|fluticasone/i },
];

/** Returns the suggested specialty key, or null when no clear signal exists. */
export function suggestSpecialty(timeline: Timeline | null | undefined): string | null {
  if (!timeline) return null;
  const text: string[] = [];

  for (const visit of timeline.visits || []) {
    if (visit.clinical_notes) text.push(visit.clinical_notes);
    if (visit.provider_or_doctor) text.push(visit.provider_or_doctor);
    for (const med of visit.medications || []) text.push(med.name);
  }
  for (const med of timeline.medications_timeline || []) text.push(med.name);
  for (const lab of timeline.lab_results_timeline || []) text.push(lab.test_name);

  const haystack = text.join(" \n ");
  if (!haystack.trim()) return null;

  for (const rule of RULES) {
    if (rule.pattern.test(haystack)) return rule.key;
  }
  for (const hint of MEDICATION_HINTS) {
    if (hint.pattern.test(haystack)) return hint.key;
  }
  return null;
}

/** Returns a patient display name from the timeline, if any. */
export function patientName(timeline: Timeline | null | undefined): string | null {
  if (!timeline) return null;
  for (const visit of timeline.visits || []) {
    const name = visit.patient_name?.trim();
    if (name) return name;
  }
  return null;
}

export function specialtyLabel(
  key: string | null | undefined,
  catalog: CareSpecialty[]
): string | null {
  if (!key) return null;
  return catalog.find((item) => item.key === key)?.label ?? null;
}
