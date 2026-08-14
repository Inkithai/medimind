# Accessibility and Internationalization

## Architecture review

- **Framework:** React 18 + TypeScript + React Router + Vite + Tailwind CSS.
- **Structure:** routed pages in `src/pages`, reusable UI in `src/components`, API access in `src/api`, auth and locale providers in `src/context` / `src/i18n`.
- **Previous i18n:** none; UI copy and browser-locale formatting were distributed across components.
- **High-priority accessibility surfaces:** responsive sidebar, upload control/progress, location combobox and Leaflet map, document tabs/viewer, medical data tables, lab SVG chart, safety alerts, AI forms, and live conversation log.

## i18n design

`I18nProvider` owns the selected `en`, `si`, or `ta` language. It:

1. Reads `medimind.language.v1` from local storage.
2. Falls back to the first supported language in `navigator.languages`, then English.
3. Updates `<html lang>` and persists changes immediately.
4. Provides interpolation and locale-aware date, date-time, number, relative-time, percentage, and list formatting.
5. Falls back per key to English, making a new language a single catalog addition.

Catalogs are isolated in `src/i18n/locales`. Medical names, extracted clinical text, provider names, API evidence, and source-document wording are intentionally preserved rather than machine-translated.

## WCAG-oriented changes

- Skip links, semantic headers/navigation/main landmarks, route title updates, route announcements, and main-content focus on navigation.
- Mobile navigation removes hidden links from the tab order, supports Escape, restores trigger focus, prevents background scrolling, and exposes expanded/dialog state.
- Consistent 44px targets and 3px `:focus-visible` indicators.
- Reduced animation and smooth scrolling when `prefers-reduced-motion: reduce` is active.
- AA-oriented text-token contrast correction and non-color labels/icons for state.
- Named forms and controls, proper submit behavior, accessible validation/errors, `aria-live`, `aria-busy`, and progressbar values.
- ARIA tab pattern and arrow-key navigation for document views.
- Table captions and scoped column headers.
- SVG chart title/description plus the equivalent data table.
- Accessible location combobox, map region, language selector, file upload, conversation log, alerts, and loading states.
- Unicode-capable Sinhala/Tamil font fallback stack and layouts that wrap longer labels.

## Test coverage

- `npm run test:i18n`: language detection, fallback, Sinhala/Tamil Unicode, interpolation, switching, persistence, refresh behavior, and `<html lang>`.
- `npm run test:a11y`: axe-core audit of shared interactive controls, alerts, loading state, language selector, and document tabs/viewer.
- `npm run lint`: strict TypeScript validation.
- `npm run build`: production Vite build and long-string layout compilation.

Manual release checks should still cover keyboard-only use at 320px/200% zoom and current screen-reader/browser combinations (NVDA/Firefox, JAWS/Chrome, VoiceOver/Safari).

## Known boundaries

- LLM/API-generated medical explanations remain in their authored language to avoid unsafe automatic translation of clinical meaning; surrounding labels and controls are localized.
- Accessibility of an embedded original PDF depends on the source PDF and browser PDF viewer.
- Leaflet/OpenStreetMap tiles are visual; the confirmed textual place, coordinates, search controls, and keyboard-operable map controls provide the non-visual alternative.
- WCAG conformance ultimately requires periodic manual audit with production data and assistive technology; automated tests cannot certify conformance alone.
