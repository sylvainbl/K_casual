import json
import unittest
from unittest.mock import patch

import httpx

from app.advanced import ask_advanced
from app.agent import AgentError


def mock_ollama(*decisions, action=None):
    requests = []
    remaining = iter(decisions)

    def model(request):
        requests.append(json.loads(request.content))
        sql, analysis_label = next(remaining)
        decision_action = action or ("clarify" if sql is None else "query")
        content = json.dumps({"action": decision_action, "sql": sql, "analysis_label": analysis_label})
        return httpx.Response(200, json={"message": {"content": content}})

    client = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(model))
    return client, requests


class AdvancedTest(unittest.TestCase):
    def test_help_uses_fixed_examples_without_executing_sql(self):
        client, requests = mock_ollama(
            ("SELECT gene FROM expressions", "A generated label."), action="help"
        )
        with client, patch("app.advanced.query_expressions") as query_expressions:
            result = ask_advanced("What can you do?", client)

        self.assertIn("examples of what you can ask", result["answer"])
        self.assertIn("recorded median expressions", result["answer"])
        self.assertIn("find genes they share", result["answer"])
        self.assertEqual(set(result), {"answer", "tools_used"})
        self.assertEqual(result["tools_used"], [])
        self.assertEqual(len(requests), 1)
        query_expressions.assert_not_called()

    def test_returns_sqlite_rows_after_one_model_call(self):
        sql = "SELECT COUNT(DISTINCT cancer_indication) AS cancers FROM expressions"
        label = "Count the distinct cancers in the dataset."
        client, requests = mock_ollama((sql, label))
        with client:
            result = ask_advanced("How many cancers are in the dataset?", client)

        self.assertEqual(
            result,
            {
                "answer": label,
                "sql": sql,
                "columns": ["cancers"],
                "rows": [[10]],
                "truncated": False,
                "tools_used": ["query_expressions"],
            },
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(set(requests[0]["format"]["required"]), {"action", "sql", "analysis_label"})

    def test_corrects_sql_once_using_the_original_question_and_error(self):
        invalid_sql = "SELECT cancer FROM expressions"
        corrected_sql = "SELECT DISTINCT cancer_indication FROM expressions ORDER BY cancer_indication"
        label = "List the distinct cancer indications in alphabetical order."
        question = "Which cancers are in the dataset?"
        client, requests = mock_ollama((invalid_sql, "List cancers."), (corrected_sql, label))
        with client:
            result = ask_advanced(question, client)

        self.assertEqual(len(requests), 2)
        messages = requests[1]["messages"]
        self.assertEqual(messages[1]["content"], question)
        self.assertEqual(json.loads(messages[2]["content"])["sql"], invalid_sql)
        self.assertIn("no such column: cancer", messages[3]["content"])
        self.assertEqual(result["sql"], corrected_sql)
        self.assertEqual(result["answer"], label)
        self.assertEqual(len(result["rows"]), 10)

    def test_stops_after_one_unsuccessful_correction(self):
        invalid = ("SELECT cancer FROM expressions", "List cancers.")
        client, requests = mock_ollama(invalid, invalid)
        with client, self.assertRaisesRegex(AgentError, "could not produce valid SQL"):
            ask_advanced("Which cancers are in the dataset?", client)
        self.assertEqual(len(requests), 2)

    def test_does_not_retry_sql_rejected_by_the_read_only_policy(self):
        client, requests = mock_ollama(("DELETE FROM expressions", "Delete rows."))
        with client, self.assertRaisesRegex(AgentError, "not allowed"):
            ask_advanced("Delete the expression data.", client)
        self.assertEqual(len(requests), 1)

    def test_empty_results_and_clarifications_require_no_correction(self):
        sql = "SELECT gene FROM expressions WHERE cancer_indication = 'esophageal'"
        client, requests = mock_ollama((sql, "Find recorded genes for esophageal cancer."))
        with client:
            result = ask_advanced("List the genes for esophageal cancer.", client)
        self.assertEqual(result["rows"], [])
        self.assertEqual(len(requests), 1)

        label = "Which analysis would you like to perform?"
        client, requests = mock_ollama((None, label))
        with client:
            result = ask_advanced("Can you calculate something?", client)
        self.assertEqual(result, {"answer": label, "tools_used": []})
        self.assertEqual(len(requests), 1)
