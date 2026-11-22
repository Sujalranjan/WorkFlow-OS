// Reports that a message was sent in a Slack channel, or as a reply in a thread. The message text
// is never read; the channel id comes from the page URL (app.slack.com/client/<team>/<channel>).
// Best effort: Slack does not document its page structure; the thread reply box is recognised by
// being inside the thread pane.
function inComposer(el) {
  return !!el?.closest?.('[data-qa="message_input"]');
}

function inThread(el) {
  return !!el?.closest?.('[data-qa="threads_flexpane"], [data-qa="thread_view"], .p-threads_flexpane, .p-thread_view');
}

function reportSend(el) {
  chrome.runtime.sendMessage({ type: "form_submitted", formFields: inThread(el) ? { kind: "thread_reply" } : {} });
}

document.addEventListener(
  "keydown",
  (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && inComposer(e.target)) reportSend(e.target);
  },
  true
);

document.addEventListener(
  "click",
  (e) => {
    const button = e.target?.closest?.('[data-qa="texty_send_button"]');
    if (button) reportSend(button);
  },
  true
);
