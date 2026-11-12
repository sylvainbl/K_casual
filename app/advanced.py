import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from .agent import (
    CPU_THREADS,
    MAX_OUTPUT_TOKENS,
    MODEL,
    TIME_BUDGET_SECONDS,
    AgentError,
    NonEmptyText,
)
from .tools import ALLOWED_FUNCTIONS, EXPRESSIONS, SQLQueryError, query_expressions


class AdvancedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["help", "query", "clarify", "unsupported"]
    sql: NonEmptyText | None
    analysis_label: NonEmptyText


QUERY_SCHEMA = AdvancedQuery.model_json_schema()
SYSTEM_PROMPT = f"""Interpret the user's question about the gene expression dataset.
The only table is expressions(cancer_indication TEXT, gene TEXT, median_value REAL).
Each row is one gene for one cancer. median_value is the recorded median expression.
Cancer keys are lowercase English names: {", ".join(sorted(EXPRESSIONS))}.
Gene symbols are uppercase. Keep explicitly named cancers even if absent from the dataset.

Choose action before writing any SQL.
- help: the user asks what you can do or how to use Advanced mode. Set sql to
  null and analysis_label to "Advanced mode capabilities".
- clarify: the question leaves the metric, comparison, or subject unspecified.
  For "Can you run an analysis?", return {{"action":"clarify","sql":null,
  "analysis_label":"Which metric or comparison would you like to explore?"}}.
- unsupported: the request cannot be answered from this table. Set sql to null
  and explain the limitation in analysis_label.
- query: the question specifies an analysis that this table can answer.
  A gene list for a named cancer is a complete request. Interpret "main genes
  involved in [cancer]" as the list of recorded genes for that cancer, without
  an implied ranking. For a request for the median expressions of a cancer's
  genes, select both gene and median_value. If no genes are specified, include
  all genes recorded for that cancer.

For action query, return sql as a single SELECT, optionally with non-recursive CTEs. Use single
quotes for text values. Available SQL functions: {", ".join(sorted(ALLOWED_FUNCTIONS))}.
Respect the requested filters, grouping, and ranking. Include ties when listing
the genes at a maximum or minimum unless the user asks for a specific tie-break.
For the single highest recorded median, compute the maximum across all rows
matching the requested filters. For the highest recorded median per cancer,
compute a separate maximum for each cancer. Include median_value when identifying
the genes at an extremum. A subquery used with = must return at most one row.

For the genes tied for the highest recorded median across all cancers, use:
SELECT cancer_indication, gene, median_value FROM expressions
WHERE median_value = (SELECT MAX(median_value) FROM expressions)
ORDER BY cancer_indication, gene

For the genes tied for the highest recorded median in each cancer, use:
SELECT e.cancer_indication, e.gene, e.median_value FROM expressions AS e
WHERE e.median_value = (SELECT MAX(median_value) FROM expressions
                       WHERE cancer_indication = e.cancer_indication)
ORDER BY e.cancer_indication, e.gene
For a top result within each group, rank and filter within that group.

Set analysis_label to a short English description of the analysis you intend to
run. Name the metric, filters and grouping when relevant. Check that the SQL
performs every operation in this description. Do not predict results or make
clinical claims. Python will display the query results directly.
Return only the JSON object, without Markdown."""


def ask_advanced(question: str, client: httpx.Client) -> dict:
    """Generate a query and execute it, with one correction for a retryable SQL error."""
    deadline = time.monotonic() + TIME_BUDGET_SECONDS
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    for attempt in (1, 2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise httpx.TimeoutException("The model exceeded the response budget.")
        response = client.post(
            "/api/chat",
            json={
                "model": MODEL,
                "messages": messages,
                "format": QUERY_SCHEMA,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_ctx": 4096,
                    "num_predict": MAX_OUTPUT_TOKENS,
                    "num_thread": CPU_THREADS,
                },
            },
            timeout=httpx.Timeout(remaining, connect=min(5, remaining)),
        )
        response.raise_for_status()
        completion = response.json()
        if completion.get("done_reason") == "length":
            raise AgentError(
                "The model could not finish preparing the SQL query. Please try rephrasing it."
            )
        try:
            query = AdvancedQuery.model_validate_json(completion["message"]["content"])
        except ValidationError as exc:
            raise AgentError(
                "The model returned an invalid SQL decision. Please try rephrasing the question."
            ) from exc

        if query.action == "help":
            return {
                "answer": (
                    "In Advanced mode, I can explore the recorded gene expression data. "
                    "Here are a few examples of what you can ask.\n\n"
                    "- List the genes and recorded median expressions for a cancer.\n"
                    "- Compare cancers and find genes they share.\n"
                    "- Calculate counts, rankings and maxima.\n\n"
                    "You can inspect the SQL behind each result."
                ),
                "tools_used": [],
            }
        if query.action != "query":
            return {"answer": query.analysis_label, "tools_used": []}
        if query.sql is None:
            raise AgentError(
                "The model did not provide a SQL query. Please try rephrasing the question."
            )

        try:
            table = query_expressions(query.sql)
        except SQLQueryError as exc:
            if not exc.retryable:
                raise AgentError(str(exc)) from exc
            if attempt == 2:
                raise AgentError(
                    "The model could not produce valid SQL. Please try rephrasing the question."
                ) from exc
            messages.extend(
                [
                    {"role": "assistant", "content": query.model_dump_json()},
                    {
                        "role": "user",
                        "content": f"SQLite rejected that query with this error: {exc}\n"
                        "Correct the SQL for the original question and return the JSON object.",
                    },
                ]
            )
        else:
            return {
                "answer": query.analysis_label,
                "sql": query.sql,
                **table,
                "tools_used": ["query_expressions"],
            }
