const defaults = { backendUrl: "http://127.0.0.1:8000", crmOrigins: ["http://127.0.0.1:8001", "http://localhost:8001"] };

chrome.storage.sync.get(defaults).then((s) => {
  document.getElementById("backendUrl").value = s.backendUrl;
  document.getElementById("crmOrigins").value = s.crmOrigins.join(", ");
});
chrome.storage.local.get({ apiKey: "" }).then(({ apiKey }) => {
  document.getElementById("apiKey").value = apiKey;
});

document.getElementById("save").addEventListener("click", async () => {
  const backendUrl = document.getElementById("backendUrl").value.trim() || defaults.backendUrl;
  const crmOrigins = document
    .getElementById("crmOrigins")
    .value.split(",")
    .map((o) => o.trim().replace(/\/+$/, ""))
    .filter(Boolean);
  await chrome.storage.sync.set({ backendUrl, crmOrigins: crmOrigins.length ? crmOrigins : defaults.crmOrigins });
  await chrome.storage.local.set({ apiKey: document.getElementById("apiKey").value.trim() });
  document.getElementById("saved").textContent = "Saved";
});
