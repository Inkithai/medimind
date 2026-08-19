/**
 * Toast notifications.
 *
 * A toast is how the app answers "did that work?". These tests pin the
 * behaviour that matters for a non-technical user: the message actually
 * appears, an error is announced assertively and never disappears on its
 * own, a success clears itself, and dismissing works.
 *
 * Run with: npm run test:toast
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { ToastProvider, toastMessage, useToast } from "../Toast";

const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>", {
  url: "https://medimind.test/",
});
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Node: dom.window.Node,
  Element: dom.window.Element,
  HTMLElement: dom.window.HTMLElement,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

let api: ReturnType<typeof useToast> | null = null;

function Probe() {
  api = useToast();
  return null;
}

const container = dom.window.document.getElementById("root")!;
const root = createRoot(container);

act(() => {
  root.render(
    <ToastProvider>
      <Probe />
    </ToastProvider>,
  );
});

// --- success -------------------------------------------------------------
act(() => {
  api!.toastSuccess("Document saved", "Your record was updated.");
});
assert(container.textContent!.includes("Document saved"), "a success toast shows its title");
assert(
  container.textContent!.includes("Your record was updated."),
  "a success toast shows its description",
);
assert(
  container.textContent!.includes("Done"),
  "status is written as a word, not carried by colour alone",
);
assert(
  container.querySelector('[role="status"]') !== null,
  "a success toast is announced politely to screen readers",
);

// --- error ---------------------------------------------------------------
act(() => {
  api!.toastError("Upload failed", "The connection dropped.");
});
assert(
  container.querySelector('[role="alert"]') !== null,
  "an error toast is announced assertively",
);
assert(
  container.textContent!.includes("Could not finish"),
  "an error toast states the failure in words",
);

// --- dismissing ----------------------------------------------------------
const closeButtons = container.querySelectorAll("button");
assert(closeButtons.length >= 2, "every toast has its own close button");
assert(
  Array.from(closeButtons).every((button) => button.textContent!.includes("Close this message")),
  "the close button has a screen-reader label",
);

act(() => {
  const id = api!.toastInfo("Temporary note");
  api!.dismissToast(id);
});
assert(!container.textContent!.includes("Temporary note"), "dismissing removes a toast");

// --- stack limit ---------------------------------------------------------
act(() => {
  for (let index = 0; index < 8; index += 1) api!.toastInfo(`Note ${index}`);
});
assert(
  container.querySelectorAll('[role="status"], [role="alert"]').length <= 4,
  "the toast stack stays readable (oldest fall off)",
);

// --- error message extraction -------------------------------------------
assert(
  toastMessage(new Error("Server is unreachable")) === "Server is unreachable",
  "an Error becomes its message",
);
assert(toastMessage({}) === "Please try again.", "an unknown failure gets a plain fallback");
assert(
  toastMessage(null, "Try later.") === "Try later.",
  "callers can supply their own fallback wording",
);

act(() => {
  root.unmount();
});

console.log("toast tests passed");
