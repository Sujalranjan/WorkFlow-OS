// Reports that a message was sent in a Slack channel. The message text is never read;
// the channel id comes from the page URL (app.slack.com/client/<team>/<channel>).
function inComposer(el) {
  return !!el?.closest?.('[data-qa="message_input"]');
}

function reportSend() {
  chrome.runtime.sendMessage({ type: "form_submitted", formFields: {} });
}

document.addEventListener(
  "keydown",
  (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && inComposer(e.target)) reportSend();
  },
  true
);

document.addEventListener(
  "click",
  (e) => {
    if (e.target?.closest?.('[data-qa="texty_send_button"]')) reportSend();
  },
  true
);
