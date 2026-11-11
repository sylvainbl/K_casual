const form = document.querySelector("#question-form");
const input = document.querySelector("#question");
const status = document.querySelector("#status");
const result = document.querySelector("#result");
const buttons = form.querySelectorAll("button");

function addText(parent, tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  parent.append(element);
  return element;
}

function showAnswer(question, response) {
  addText(result, "h2", question);
  const answer = document.createElement("div");
  answer.className = "answer-text";
  // FastAPI renders this field with raw Markdown HTML disabled.
  answer.innerHTML = response.answer_html;
  result.append(answer);

  if (response.genes) {
    addText(result, "p", response.genes.join(", "));
  }

  if (response.expressions) {
    const table = document.createElement("table");
    const headings = table.createTHead().insertRow();
    addText(headings, "th", "Gene").scope = "col";
    addText(headings, "th", "Median expression").scope = "col";
    const body = table.createTBody();
    for (const [gene, value] of Object.entries(response.expressions)) {
      const row = body.insertRow();
      addText(row, "th", gene).scope = "row";
      addText(row, "td", value);
    }
    result.append(table);
  }

  if (response.tools_used.length) {
    const details = document.createElement("details");
    addText(details, "summary", "Tools used");
    addText(details, "code", response.tools_used.join(" → "));
    result.append(details);
  }
  result.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) {
    status.textContent = "Enter a question to continue.";
    return;
  }

  buttons.forEach((button) => { button.disabled = true; });
  result.replaceChildren();
  result.hidden = true;
  status.textContent = "Waiting for the local model…";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : undefined);
    }
    showAnswer(question, data);
    status.textContent = data.truncated
      ? "Partial answer. The local model reached its output limit."
      : "Answer ready.";
  } catch (error) {
    status.textContent = error.message || "The request could not be completed.";
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
});

for (const button of form.querySelectorAll("[data-question]")) {
  button.addEventListener("click", () => {
    input.value = button.dataset.question;
    form.requestSubmit();
  });
}
