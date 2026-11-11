import os
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from .tools import EXPRESSIONS, get_expressions, get_targets

MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
TIME_BUDGET_SECONDS = int(os.getenv("MODEL_TIMEOUT_SECONDS", "300"))
MAX_OUTPUT_TOKENS = int(os.getenv("MODEL_MAX_OUTPUT_TOKENS", "768"))
CPU_THREADS = int(os.getenv("OLLAMA_CPUS", "0"))


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class QueryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["help", "list_genes", "median_expressions", "clarify", "unsupported"]
    scope: Literal["one", "multiple", "all", "unspecified"]
    cancers: list[NonEmptyText]
    genes: list[NonEmptyText]


QUERY_SCHEMA = QueryDecision.model_json_schema()
SYSTEM_PROMPT = f"""Classify the user's request for a gene expression dataset. Return the JSON
decision only. Python executes the decision and answers the user.

Operation:
- help: the user asks what the assistant can do.
- list_genes: list genes associated with a cancer. "Main genes" means the
  associated genes, without ranking.
- median_expressions: retrieve the recorded median expression of each gene.
- clarify: the requested lookup or cancer cannot be determined from this
  question. A clearly named cancer or gene is enough to identify it, even
  when it might be absent from the dataset.
- unsupported: any comparison, intersection, ranking, highest or lowest value,
  count, average, other calculation, or medical advice. Use unsupported even
  for a single cancer and even if a supported lookup is part of the request.
  A request that explicitly says "no ranking" is asking for raw data.

Scope:
- one: exactly one cancer is requested.
- multiple: several cancers are requested.
- all: every cancer in the dataset is requested.
- unspecified: no cancer is identified.

In cancers, list only the cancers the user is asking about. Exclude any
explicitly excluded cancer. If the user asks about every cancer, use scope all
and leave cancers empty. Use these English keys for normalization only:
{", ".join(sorted(EXPRESSIONS))}. Keep any explicitly named cancer outside
that list under its English name. Python will check whether the data exists.
For example, "Show the medians for thyroid cancer" is median_expressions
with scope one and cancers ["thyroid"].

In genes, include all explicitly requested gene symbols for median_expressions,
including symbols that might not be in the dataset. Use an empty list if no
specific genes were requested. Do not infer a cancer or gene from an example,
a gene symbol, or a previous question."""


class AgentError(Exception):
    """The model did not return a usable query decision."""


def ask(question: str, client: httpx.Client) -> dict:
    if TIME_BUDGET_SECONDS <= 0:
        raise httpx.TimeoutException("The model exceeded the response budget.")

    response = client.post(
        "/api/chat",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "format": QUERY_SCHEMA,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": 4096,
                "num_predict": MAX_OUTPUT_TOKENS,
                "num_thread": CPU_THREADS,
            },
        },
        timeout=httpx.Timeout(TIME_BUDGET_SECONDS, connect=min(5, TIME_BUDGET_SECONDS)),
    )
    response.raise_for_status()
    completion = response.json()
    if completion.get("done_reason") == "length":
        raise AgentError("The model could not finish interpreting the question. Please try rephrasing it.")
    try:
        decision = QueryDecision.model_validate_json(completion["message"]["content"])
    except ValidationError as exc:
        raise AgentError("The model returned an invalid query decision. Please try rephrasing the question.") from exc

    cancers = {name.lower() for name in decision.cancers}
    if decision.operation == "unsupported" or decision.scope in {"multiple", "all"} or len(cancers) > 1:
        return {
            "answer": (
                "I can list genes or show recorded median expressions for one cancer at a time. "
                "Comparisons, rankings and calculations are outside this tool's scope."
            ),
            "tools_used": [],
        }
    if decision.operation == "help":
        return {
            "answer": (
                "I can help you explore the gene expression dataset for one cancer at a time.\n\n"
                "- List the genes recorded for a cancer.\n"
                "- Show the recorded median expression for all or selected genes."
            ),
            "tools_used": [],
        }
    if decision.operation == "clarify" or decision.scope != "one" or len(cancers) != 1:
        return {
            "answer": "Please specify one cancer and whether you want its gene list or recorded median expressions.",
            "tools_used": [],
        }

    cancer = cancers.pop()
    targets = get_targets(cancer)
    tools_used = ["get_targets"]
    if not targets:
        return {"answer": f"The dataset has no records for {cancer}.", "tools_used": tools_used}
    if decision.operation == "list_genes":
        return {
            "answer": f"Genes associated with {cancer} in this dataset.",
            "genes": targets,
            "tools_used": tools_used,
        }

    requested = list(dict.fromkeys(gene.upper() for gene in decision.genes))
    available = [gene for gene in requested if gene in targets] if requested else targets
    missing = [gene for gene in requested if gene not in targets]
    if not available:
        return {
            "answer": f"No recorded median expression for {', '.join(missing)} in {cancer}.",
            "tools_used": tools_used,
        }

    answer = f"Median expression values for {cancer} in this dataset."
    if missing:
        answer += f" No recorded median expression for {', '.join(missing)}."
    return {
        "answer": answer,
        "expressions": get_expressions(cancer, available),
        "tools_used": [*tools_used, "get_expressions"],
    }
