document.addEventListener("DOMContentLoaded", function () {
  const root = document.querySelector("[data-chatbot-root]");
  if (!root) {
    return;
  }

  const toggle = root.querySelector("[data-chatbot-toggle]");
  const closeBtn = root.querySelector("[data-chatbot-close]");
  const panel = root.querySelector("[data-chatbot-panel]");
  const form = root.querySelector("[data-chatbot-form]");
  const input = root.querySelector(".chatbot-input");
  const messages = root.querySelector("[data-chatbot-messages]");
  const sendButton = root.querySelector(".chatbot-send");

  function appendMessage(kind, text) {
    const bubble = document.createElement("article");
    bubble.className = `chatbot-message ${kind}`;
    bubble.textContent = text;
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
  }

  function setOpen(isOpen) {
    panel.hidden = !isOpen;
    toggle.setAttribute("aria-expanded", String(isOpen));
    root.classList.toggle("is-open", isOpen);
    if (isOpen) {
      input.focus();
      messages.scrollTop = messages.scrollHeight;
    }
  }

  toggle.addEventListener("click", function () {
    setOpen(panel.hidden);
  });

  closeBtn.addEventListener("click", function () {
    setOpen(false);
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const message = input.value.trim();

    if (!message) {
      return;
    }

    appendMessage("user", message);
    input.value = "";
    input.disabled = true;
    sendButton.disabled = true;

    try {
      const response = await fetch("/chatbot", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ message })
      });

      const data = await response.json();
      appendMessage("bot", data.reply || "I couldn't generate a response just now.");
    } catch (error) {
      appendMessage("bot", "I couldn't reach the assistant right now. Please try again.");
    } finally {
      input.disabled = false;
      sendButton.disabled = false;
      input.focus();
    }
  });
});
