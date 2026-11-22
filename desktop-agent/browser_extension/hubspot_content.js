// Reports saves on a HubSpot contact record: "a note was saved" or "property X was saved".
// Best effort: HubSpot does not document its page structure, so this looks for the save buttons by
// their visible label. Note text and property values are never read; the value an "Update contact"
// step writes comes from Settings in WorkFlowOS.
const RECORD_PATH = /^\/contacts\/\d+\/(record\/0-1|contact)\/\d+/;

function label(el) {
  return (el?.innerText || el?.getAttribute?.("aria-label") || "").trim().toLowerCase();
}

function propertyName(button) {
  // Property editors usually carry the internal name on an ancestor; omitted when not found.
  const holder = button.closest("[data-property-name], [data-selenium-test*='property-input-']");
  if (!holder) return null;
  const direct = holder.getAttribute("data-property-name");
  if (direct) return direct;
  const m = (holder.getAttribute("data-selenium-test") || "").match(/property-input-([a-z0-9_]+)/i);
  return m ? m[1] : null;
}

document.addEventListener(
  "click",
  (e) => {
    if (!RECORD_PATH.test(location.pathname)) return;
    const button = e.target?.closest?.("button");
    if (!button) return;
    const text = label(button);
    if (text === "save note" || text === "create note") {
      chrome.runtime.sendMessage({ type: "form_submitted", formFields: { kind: "note" } });
    } else if (text === "save" && button.closest("[data-property-name], [data-selenium-test*='property']")) {
      const name = propertyName(button);
      chrome.runtime.sendMessage({ type: "form_submitted", formFields: name ? { kind: "property", property: name } : { kind: "property" } });
    }
  },
  true
);
