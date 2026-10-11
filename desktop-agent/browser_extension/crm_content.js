// Reports Demo CRM customer updates. Only the 'status' field is forwarded; notes stay local.
document.addEventListener(
  "submit",
  (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post") return;
    if (!/^\/ui\/customers\/[^/]+\/?$/.test(new URL(form.action, location.href).pathname)) return;
    const status = form.elements.namedItem("status");
    chrome.runtime.sendMessage({
      type: "form_submitted",
      formFields: status && "value" in status ? { status: status.value } : {},
    });
  },
  true
);
