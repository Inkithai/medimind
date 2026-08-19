/**
 * Browser file download helper.
 *
 * The export endpoints return JSON objects; saving them as a file is a
 * purely client-side concern (no extra dependency, no second request).
 * Kept in one place so every "download" button in the app produces the
 * same well-named, correctly typed file.
 */

/** Slug-safe timestamp for filenames, e.g. 2026-08-19. */
export function todayStamp(date = new Date()): string {
  return date.toISOString().slice(0, 10);
}

/**
 * Save a JSON-serialisable value as a downloaded file.
 * Returns false when the browser blocked it, so callers can tell the user.
 */
export function downloadJsonFile(filename: string, data: unknown): boolean {
  try {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    return downloadBlob(filename, blob);
  } catch {
    return false;
  }
}

/**
 * Save an arbitrary Blob (e.g. a generated PDF) as a downloaded file.
 * Returns false when the browser blocked it, so callers can tell the user.
 */
export function downloadBlob(filename: string, blob: Blob): boolean {
  try {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    // Revoke on the next tick so Safari has time to start the download.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  } catch {
    return false;
  }
}
