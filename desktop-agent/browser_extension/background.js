// WorkFlowOS Activity Observer - background service worker.
//
// Sends ActivityEvents to the WorkFlowOS backend (POST /api/events). Only these are reported:
//   - Gmail search routes (#search/<query>), which carry the search query
//   - Demo CRM page views (/ui/customers...)
//   - Completed downloads that came from Gmail (origin + path only, no tokens)
//   - Form submissions reported by the CRM / Slack content scripts
// Every other page the user visits is ignored and never leaves the browser.

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
const DEFAULT_CRM_ORIGINS = ["http://127.0.0.1:8001", "http://localhost:8001"];
const GMAIL_HOSTS = ["mail.google.com", "mail-attachment.googleusercontent.com"];
const QUEUE_KEY = "pendingEvents";
const MAX_QUEUE = 500;

async function settings() {
  const s = await chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND_URL, crmOrigins: DEFAULT_CRM_ORIGINS });
  return { backendUrl: s.backendUrl.replace(/\/+$/, ""), crmOrigins: s.crmOrigins };
}

function hostMatches(url, hosts) {
  try {
    const h = new URL(url).hostname;
    return hosts.some((x) => h === x || h.endsWith("." + x));
  } catch {
    return false;
  }
}

function isGmailSearch(url) {
  try {
    const u = new URL(url);
    return u.hostname === "mail.google.com" && u.hash.startsWith("#search/");
  } catch {
    return false;
  }
}

async function isCrmPage(url) {
  try {
    const u = new URL(url);
    const { crmOrigins } = await settings();
    return crmOrigins.includes(u.origin) && u.pathname.startsWith("/ui/");
  } catch {
    return false;
  }
}

function originAndPath(url) {
  try {
    const u = new URL(url);
    return u.origin + u.pathname;
  } catch {
    return "";
  }
}

// Sends are serialized so concurrent events cannot read and rewrite the queue at the same time.
let sendChain = Promise.resolve();
function post(event) {
  sendChain = sendChain.then(() => flush(event)).catch(() => {});
  return sendChain;
}

async function flush(event) {
  const { backendUrl } = await settings();
  const { [QUEUE_KEY]: queued = [] } = await chrome.storage.local.get(QUEUE_KEY);
  const pending = [...queued, event];
  const remaining = [];
  for (const e of pending) {
    try {
      const res = await fetch(`${backendUrl}/api/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(e),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch {
      remaining.push(e); // backend offline: keep for the next attempt
    }
  }
  await chrome.storage.local.set({ [QUEUE_KEY]: remaining.slice(-MAX_QUEUE) });
}

function activityEvent(eventType, metadata) {
  return {
    event_type: eventType,
    timestamp: new Date().toISOString(),
    application: "Web Browser",
    source: "browser_extension",
    metadata: { collector: "WorkFlowOSBrowserExtension", ...metadata },
  };
}

// Gmail is a single-page app: searches change only the URL fragment.
let lastNavigation = "";
async function onNavigation(details) {
  if (details.frameId !== 0) return;
  const url = details.url;
  if (!(isGmailSearch(url) || (await isCrmPage(url)))) return;
  if (url === lastNavigation) return; // the same route fires several webNavigation events
  lastNavigation = url;
  await post(activityEvent("browser_navigation", { url }));
}

chrome.webNavigation.onCompleted.addListener(onNavigation);
chrome.webNavigation.onReferenceFragmentUpdated.addListener(onNavigation);
chrome.webNavigation.onHistoryStateUpdated.addListener(onNavigation);

chrome.downloads.onChanged.addListener(async (delta) => {
  if (!delta.state || delta.state.current !== "complete") return;
  const [item] = await chrome.downloads.search({ id: delta.id });
  if (!item) return;
  const sources = [item.url, item.finalUrl, item.referrer].filter(Boolean);
  if (!sources.some((u) => hostMatches(u, GMAIL_HOSTS))) return;
  await post(
    activityEvent("file_downloaded", {
      url: originAndPath(sources.find((u) => hostMatches(u, GMAIL_HOSTS))),
      file_name: item.filename.split(/[\\/]/).pop(),
      file_size: item.fileSize,
    })
  );
});

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg?.type !== "form_submitted" || !sender.tab) return;
  // Only the URL (which identifies the record/channel) and whitelisted fields are forwarded.
  post(activityEvent("form_submitted", { url: sender.tab.url, form_fields: msg.formFields || {} }));
});
