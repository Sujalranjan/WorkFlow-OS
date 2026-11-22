// Reports labels applied to an email in Gmail ("Label as" menu, then Apply), so WorkFlowOS can learn
// a "label the processed email" step. Only the label's name is sent; nothing about the email
// itself (subject, sender, body) is read. Best effort: Gmail does not document its page structure.
const pending = new Set();

function labelName(item) {
  return (item.getAttribute("title") || item.getAttribute("aria-label") || item.innerText || "").trim();
}

document.addEventListener(
  "click",
  (e) => {
    const box = e.target?.closest?.('[role="menuitemcheckbox"]');
    if (box) {
      const name = labelName(box);
      if (!name) return;
      // aria-checked still shows the state before this click
      if (box.getAttribute("aria-checked") === "true") pending.delete(name);
      else pending.add(name);
      return;
    }
    const item = e.target?.closest?.('[role="menuitem"]');
    if (item && pending.size && /^apply$/i.test((item.innerText || "").trim())) {
      for (const label of pending) {
        chrome.runtime.sendMessage({ type: "form_submitted", formFields: { kind: "label_added", label } });
      }
      pending.clear();
    }
  },
  true
);

// Closing the menu without Apply discards the choices.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") pending.clear();
});
