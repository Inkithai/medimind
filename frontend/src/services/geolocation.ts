import type { Coordinates } from "../types/location";

/** A GPS fix plus the radius the browser believes it is accurate to. */
export interface PositionFix extends Coordinates {
  /** Horizontal accuracy radius in metres (95% confidence, per the W3C spec). */
  accuracyMetres: number;
}

export type GeolocationFailureReason = "unsupported" | "denied" | "timeout" | "unavailable";

export class GeolocationFailure extends Error {
  reason: GeolocationFailureReason;

  constructor(reason: GeolocationFailureReason, message: string) {
    super(message);
    this.name = "GeolocationFailure";
    this.reason = reason;
  }
}

export interface AccuratePositionOptions {
  /** Stop early once a fix is at least this precise. */
  desiredAccuracyMetres?: number;
  /** Hard limit on how long to keep refining before returning the best fix. */
  timeoutMs?: number;
  signal?: AbortSignal;
}

const DEFAULT_DESIRED_ACCURACY_M = 30;
const DEFAULT_TIMEOUT_MS = 15_000;

/**
 * Resolve the device's position, preferring precision over speed.
 *
 * `getCurrentPosition` typically returns the very first fix the platform can
 * produce, which is often a coarse Wi-Fi/IP estimate accurate to hundreds of
 * metres or worse. GPS hardware then refines that fix over the next few
 * seconds. This helper therefore watches the position, keeps the most accurate
 * reading seen, and returns as soon as the fix is good enough (or when the
 * timeout expires, with the best reading so far).
 *
 * `maximumAge: 0` is deliberate: a cached fix may predate the user moving.
 */
export function getAccuratePosition(
  options: AccuratePositionOptions = {}
): Promise<PositionFix> {
  const desiredAccuracy = options.desiredAccuracyMetres ?? DEFAULT_DESIRED_ACCURACY_M;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  return new Promise<PositionFix>((resolve, reject) => {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      reject(
        new GeolocationFailure(
          "unsupported",
          "Your browser doesn't support location access. Search for a place instead."
        )
      );
      return;
    }

    let best: PositionFix | null = null;
    let settled = false;
    let watchId: number | null = null;
    let timer: number | null = null;

    const cleanup = () => {
      if (watchId !== null) navigator.geolocation.clearWatch(watchId);
      if (timer !== null) window.clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      watchId = null;
      timer = null;
    };

    const succeed = (fix: PositionFix) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(fix);
    };

    const fail = (error: GeolocationFailure) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    function onAbort() {
      fail(new GeolocationFailure("timeout", "Location lookup was cancelled."));
    }

    if (options.signal) {
      if (options.signal.aborted) {
        onAbort();
        return;
      }
      options.signal.addEventListener("abort", onAbort);
    }

    watchId = navigator.geolocation.watchPosition(
      (position) => {
        const accuracy = Number.isFinite(position.coords.accuracy)
          ? position.coords.accuracy
          : Number.POSITIVE_INFINITY;
        const fix: PositionFix = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracyMetres: accuracy,
        };
        // Keep refining: later readings are only adopted when they are better.
        if (!best || fix.accuracyMetres < best.accuracyMetres) best = fix;
        if (best.accuracyMetres <= desiredAccuracy) succeed(best);
      },
      (error) => {
        // A late error after a usable fix should not discard that fix.
        if (best) {
          succeed(best);
          return;
        }
        if (error.code === error.PERMISSION_DENIED) {
          fail(
            new GeolocationFailure(
              "denied",
              "Location access was blocked. Allow it in your browser settings, or search for a place instead."
            )
          );
        } else if (error.code === error.TIMEOUT) {
          fail(
            new GeolocationFailure(
              "timeout",
              "We couldn't get your location in time. Try again or search for a place."
            )
          );
        } else {
          fail(
            new GeolocationFailure(
              "unavailable",
              "We couldn't find your current location. Search for a place instead."
            )
          );
        }
      },
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 }
    );

    timer = window.setTimeout(() => {
      if (best) {
        succeed(best);
        return;
      }
      fail(
        new GeolocationFailure(
          "timeout",
          "We couldn't get your location in time. Try again or search for a place."
        )
      );
    }, timeoutMs);
  });
}

/** Human-readable precision, e.g. "±12 m" or "±1.4 km". */
export function accuracyLabel(accuracyMetres: number): string {
  if (!Number.isFinite(accuracyMetres)) return "accuracy unknown";
  if (accuracyMetres < 1000) return `±${Math.round(accuracyMetres)} m`;
  return `±${(accuracyMetres / 1000).toFixed(1)} km`;
}

/** Above this radius a GPS fix is too coarse to trust for a 5 km facility search. */
export const COARSE_ACCURACY_THRESHOLD_M = 150;
