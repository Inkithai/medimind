/**
 * Proves the "Use my current location" fix returns an ACCURATE position.
 *
 * The old code called getCurrentPosition() with maximumAge: 60_000 and took
 * the first reading, which is typically a coarse Wi-Fi/IP estimate. These
 * tests pin the new behaviour: watch, keep the best fix, stop early when it is
 * precise enough, and never hand back a cached or worse reading.
 *
 * Run with: npm run test:geolocation
 */
import assert from "node:assert/strict";

import {
  COARSE_ACCURACY_THRESHOLD_M,
  GeolocationFailure,
  accuracyLabel,
  getAccuratePosition,
} from "../geolocation";

type WatchSuccess = (position: unknown) => void;
type WatchError = (error: unknown) => void;

interface FakeWatch {
  success: WatchSuccess;
  error: WatchError;
  options: PositionOptions;
}

const PERMISSION_DENIED = 1;
const POSITION_UNAVAILABLE = 2;
const TIMEOUT = 3;

function positionError(code: number) {
  return { code, PERMISSION_DENIED, POSITION_UNAVAILABLE, TIMEOUT, message: "" };
}

function coords(latitude: number, longitude: number, accuracy: number) {
  return { coords: { latitude, longitude, accuracy } };
}

/** Installs a controllable navigator.geolocation and a synchronous timer shim. */
function withFakeGeolocation(run: (watch: () => FakeWatch, cleared: number[]) => Promise<void>) {
  const watches: FakeWatch[] = [];
  const cleared: number[] = [];
  const timers = new Map<number, () => void>();
  let nextTimer = 1;

  const globalScope = globalThis as Record<string, unknown>;
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const previousWindow = globalScope.window;

  Object.defineProperty(globalThis, "navigator", {
    value: {
      geolocation: {
        watchPosition(success: WatchSuccess, error: WatchError, options: PositionOptions) {
          watches.push({ success, error, options });
          return watches.length;
        },
        clearWatch(id: number) {
          cleared.push(id);
        },
      },
    },
    configurable: true,
  });

  globalScope.window = {
    setTimeout(callback: () => void) {
      const id = nextTimer++;
      timers.set(id, callback);
      return id;
    },
    clearTimeout(id: number) {
      timers.delete(id);
    },
    // Exposed so a test can fire the deadline deterministically.
    __fireTimers() {
      for (const callback of [...timers.values()]) callback();
    },
  };

  const restore = () => {
    if (previousNavigator) Object.defineProperty(globalThis, "navigator", previousNavigator);
    globalScope.window = previousWindow;
  };

  return run(() => {
    const watch = watches[watches.length - 1];
    if (!watch) throw new Error("watchPosition was never called");
    return watch;
  }, cleared).finally(restore);
}

function fireTimers() {
  (globalThis as unknown as { window: { __fireTimers: () => void } }).window.__fireTimers();
}

async function test_requests_high_accuracy_and_never_uses_a_cached_fix() {
  await withFakeGeolocation(async (watch) => {
    const pending = getAccuratePosition();
    const options = watch().options;
    assert.equal(options.enableHighAccuracy, true, "must ask for GPS, not coarse positioning");
    assert.equal(options.maximumAge, 0, "a cached fix may predate the user moving");
    watch().success(coords(9.8, 80.19, 10));
    await pending;
  });
}

async function test_resolves_early_once_the_fix_is_precise_enough() {
  await withFakeGeolocation(async (watch, cleared) => {
    const pending = getAccuratePosition({ desiredAccuracyMetres: 30 });
    watch().success(coords(9.80138, 80.1945, 12));
    const fix = await pending;
    assert.equal(fix.latitude, 9.80138);
    assert.equal(fix.accuracyMetres, 12);
    assert.equal(cleared.length, 1, "the watch must be released once resolved");
  });
}

async function test_keeps_refining_past_a_coarse_first_reading() {
  await withFakeGeolocation(async (watch) => {
    const pending = getAccuratePosition({ desiredAccuracyMetres: 30 });
    // A coarse Wi-Fi estimate arrives first — the old code returned exactly this.
    watch().success(coords(9.7, 80.1, 2400));
    watch().success(coords(9.79, 80.18, 300));
    watch().success(coords(9.80138, 80.19453, 8));
    const fix = await pending;
    assert.equal(fix.accuracyMetres, 8);
    assert.equal(fix.latitude, 9.80138, "must return the refined GPS point, not the first estimate");
  });
}

async function test_never_downgrades_to_a_worse_later_reading() {
  await withFakeGeolocation(async (watch) => {
    const pending = getAccuratePosition({ desiredAccuracyMetres: 5 });
    watch().success(coords(9.80138, 80.19453, 20));
    watch().success(coords(9.60000, 80.00000, 1800));
    fireTimers();
    const fix = await pending;
    assert.equal(fix.accuracyMetres, 20);
    assert.equal(fix.latitude, 9.80138);
  });
}

async function test_timeout_returns_best_effort_fix_instead_of_failing() {
  await withFakeGeolocation(async (watch) => {
    const pending = getAccuratePosition({ desiredAccuracyMetres: 5 });
    watch().success(coords(9.8, 80.19, 90));
    fireTimers();
    const fix = await pending;
    assert.equal(fix.accuracyMetres, 90, "a usable coarse fix beats an error");
  });
}

async function test_timeout_with_no_fix_at_all_reports_timeout() {
  await withFakeGeolocation(async () => {
    const pending = getAccuratePosition();
    fireTimers();
    await assert.rejects(pending, (error: unknown) => {
      assert.ok(error instanceof GeolocationFailure);
      assert.equal(error.reason, "timeout");
      return true;
    });
  });
}

async function test_permission_denied_is_reported_distinctly() {
  await withFakeGeolocation(async (watch) => {
    const pending = getAccuratePosition();
    watch().error(positionError(PERMISSION_DENIED));
    await assert.rejects(pending, (error: unknown) => {
      assert.ok(error instanceof GeolocationFailure);
      assert.equal(error.reason, "denied");
      assert.match(error.message, /blocked/i);
      return true;
    });
  });
}

async function test_late_error_after_a_good_fix_keeps_the_fix() {
  await withFakeGeolocation(async (watch) => {
    const pending = getAccuratePosition({ desiredAccuracyMetres: 1 });
    watch().success(coords(9.80138, 80.19453, 15));
    watch().error(positionError(POSITION_UNAVAILABLE));
    const fix = await pending;
    assert.equal(fix.accuracyMetres, 15);
  });
}

async function test_accuracy_labels_are_human_readable() {
  assert.equal(accuracyLabel(12.4), "±12 m");
  assert.equal(accuracyLabel(1400), "±1.4 km");
  assert.equal(accuracyLabel(Number.POSITIVE_INFINITY), "accuracy unknown");
  assert.ok(COARSE_ACCURACY_THRESHOLD_M > 0);
}

const tests = [
  test_requests_high_accuracy_and_never_uses_a_cached_fix,
  test_resolves_early_once_the_fix_is_precise_enough,
  test_keeps_refining_past_a_coarse_first_reading,
  test_never_downgrades_to_a_worse_later_reading,
  test_timeout_returns_best_effort_fix_instead_of_failing,
  test_timeout_with_no_fix_at_all_reports_timeout,
  test_permission_denied_is_reported_distinctly,
  test_late_error_after_a_good_fix_keeps_the_fix,
  test_accuracy_labels_are_human_readable,
];

const run = async () => {
  for (const test of tests) {
    await test();
    console.log(`PASS ${test.name}`);
  }
  console.log(`\n${tests.length} tests passed`);
};

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
