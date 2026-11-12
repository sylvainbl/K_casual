const form = document.querySelector("#question-form");
const input = document.querySelector("#question");
const status = document.querySelector("#status");
const loading = document.querySelector("#loading");
const elapsed = document.querySelector("#elapsed");
const result = document.querySelector("#result");
const advancedToggle = document.querySelector("#advanced-toggle");
const advancedWarning = document.querySelector("#advanced-warning");
const buttons = form.querySelectorAll("button");
const simplePlaceholder = input.placeholder;

function addText(parent, tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  parent.append(element);
  return element;
}

function showTable(columns, rows, hasRowHeaders = false) {
  const container = document.createElement("div");
  container.className = "table-scroll";
  const table = document.createElement("table");
  table.classList.toggle("expression-table", hasRowHeaders);
  const headings = table.createTHead().insertRow();
  for (const column of columns) {
    addText(headings, "th", column).scope = "col";
  }
  const body = table.createTBody();
  for (const values of rows) {
    const row = body.insertRow();
    for (const [index, value] of values.entries()) {
      if (hasRowHeaders && index === 0) {
        addText(row, "th", value).scope = "row";
      } else {
        addText(row, "td", value ?? "NULL").classList.toggle("number", typeof value === "number");
      }
    }
  }
  container.append(table);
  result.append(container);
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
    showTable(["Gene", "Median expression"], Object.entries(response.expressions), true);
  }

  if (response.sql) {
    const count = response.rows.length;
    if (count) {
      showTable(response.columns, response.rows);
      const label = count === 1 ? "row" : "rows";
      const message = response.truncated ? `Showing ${count} ${label}. More rows matched.` : `${count} ${label}.`;
      addText(result, "p", message).className = "result-count";
    } else {
      addText(result, "p", "No records matched this query.").className = "result-count";
    }
    const details = document.createElement("details");
    addText(details, "summary", "View executed SQL");
    const sql = document.createElement("pre");
    sql.className = "sql-query";
    addText(sql, "code", response.sql);
    details.append(sql);
    result.append(details);
  }

  if (response.tools_used.length) {
    const details = document.createElement("details");
    addText(details, "summary", "Tools used");
    addText(details, "code", response.tools_used.join(" → "));
    result.append(details);
  }
  result.hidden = false;
}

advancedToggle.addEventListener("click", () => {
  const isAdvanced = advancedToggle.getAttribute("aria-pressed") !== "true";
  advancedToggle.setAttribute("aria-pressed", String(isAdvanced));
  document.documentElement.classList.toggle("advanced-mode", isAdvanced);
  advancedWarning.hidden = !isAdvanced;
  if (isAdvanced) {
    input.setAttribute("aria-describedby", advancedWarning.id);
    input.placeholder = "Which genes are shared by breast and prostate cancers?";
  } else {
    input.removeAttribute("aria-describedby");
    input.placeholder = simplePlaceholder;
  }
  result.replaceChildren();
  result.hidden = true;
  status.textContent = "";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (advancedToggle.disabled) return;
  const question = input.value.trim();
  if (!question) {
    status.textContent = "Enter a question to continue.";
    return;
  }

  const isAdvanced = advancedToggle.getAttribute("aria-pressed") === "true";
  buttons.forEach((button) => { button.disabled = true; });
  result.replaceChildren();
  result.hidden = true;
  status.textContent = "Waiting for the local model…";
  const startedAt = performance.now();
  const secondsSinceStart = () => (performance.now() - startedAt) / 1000;
  elapsed.textContent = "0 s";
  loading.hidden = false;
  const timer = setInterval(() => {
    elapsed.textContent = `${Math.floor(secondsSinceStart())} s`;
  }, 1000);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, is_advanced: isAdvanced }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : undefined);
    }
    showAnswer(question, data);
    const elapsedSeconds = secondsSinceStart().toFixed(1);
    const message = data.truncated
      ? "Result limit reached."
      : "Answer ready.";
    status.textContent = `${message} (${elapsedSeconds} s)`;
  } catch (error) {
    status.textContent = error.message || "The request could not be completed.";
  } finally {
    clearInterval(timer);
    loading.hidden = true;
    buttons.forEach((button) => { button.disabled = false; });
  }
});

for (const button of form.querySelectorAll("[data-question]")) {
  button.addEventListener("click", () => {
    input.value = button.dataset.question;
    form.requestSubmit();
  });
}
