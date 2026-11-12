import json
import unittest
from unittest.mock import patch

import httpx

from app.agent import AgentError, ask
from app.main import app


def query_response(operation, scope, cancers=(), genes=()):
    return httpx.Response(
        200,
        json={
            "message": {
                "content": json.dumps(
                    {"operation": operation, "scope": scope, "cancers": list(cancers), "genes": list(genes)}
                ),
            },
        },
    )


class AgentTest(unittest.IsolatedAsyncioTestCase):
    def test_expressions_use_one_structured_decision_and_keep_csv_values(self):
        calls = []

        def model(request):
            payload = json.loads(request.content)
            calls.append(payload)
            return query_response("median_expressions", "one", ["breast"])

        with httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(model)) as client:
            with patch("app.agent.MAX_OUTPUT_TOKENS", 700), patch("app.agent.CPU_THREADS", 2):
                result = ask("Show the median expression values for breast cancer genes.", client)

        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0]["format"]["required"]), {"operation", "scope", "cancers", "genes"})
        self.assertEqual(calls[0]["options"]["num_predict"], 700)
        self.assertEqual(calls[0]["options"]["num_ctx"], 4096)
        self.assertEqual(calls[0]["options"]["num_thread"], 2)
        self.assertEqual(result["tools_used"], ["get_targets", "get_expressions"])
        self.assertEqual(len(result["expressions"]), 10)
        self.assertEqual(result["expressions"]["BRCA2"], 0.032)

    def test_unsupported_operation_or_multiple_cancers_never_reaches_dataset(self):
        cases = [
            ("Which gene has the highest median in breast cancer?", "unsupported", "one", ["breast"]),
            ("Which genes are common to breast and prostate cancer?", "unsupported", "multiple", ["breast", "prostate"]),
            ("List the genes for every cancer.", "list_genes", "all", []),
            ("List genes for lung and breast cancer.", "list_genes", "one", ["lung", "breast"]),
        ]
        for question, operation, scope, cancers in cases:
            with self.subTest(question=question):
                with (
                    httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(
                        lambda _: query_response(operation, scope, cancers)
                    )) as client,
                    patch("app.agent.get_targets") as get_targets,
                    patch("app.agent.get_expressions") as get_expressions,
                ):
                    result = ask(question, client)

                self.assertIn("one cancer at a time", result["answer"])
                self.assertEqual(result["tools_used"], [])
                self.assertNotIn("genes", result)
                self.assertNotIn("expressions", result)
                get_targets.assert_not_called()
                get_expressions.assert_not_called()

    def test_missing_cancer_is_a_clarification_and_unknown_cancer_is_a_lookup(self):
        cases = [
            ("What are the main genes?", "unspecified", [], "Please specify one cancer", []),
            ("What are the main genes for bladder cancer?", "one", ["bladder"], "no records for bladder", ["get_targets"]),
        ]
        for question, scope, cancers, message, tools in cases:
            with self.subTest(question=question):
                with httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(
                    lambda _: query_response("list_genes", scope, cancers)
                )) as client:
                    result = ask(question, client)

                self.assertIn(message, result["answer"])
                self.assertEqual(result["tools_used"], tools)
                self.assertNotIn("genes", result)

    def test_missing_genes_are_named_without_substituting_other_values(self):
        for genes in (["EGFR"], ["brca2", "EGFR"]):
            with self.subTest(genes=genes):
                with httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(
                    lambda _: query_response("median_expressions", "one", ["breast"], genes)
                )) as client:
                    result = ask("Show the recorded expression medians for " + " and ".join(genes), client)

                self.assertIn("No recorded median expression for EGFR", result["answer"])
                if "brca2" in genes:
                    self.assertEqual(result["expressions"], {"BRCA2": 0.032})
                    self.assertEqual(result["tools_used"], ["get_targets", "get_expressions"])
                else:
                    self.assertNotIn("expressions", result)
                    self.assertEqual(result["tools_used"], ["get_targets"])

    def test_invalid_or_truncated_decisions_do_not_reach_dataset(self):
        cases = [
            {"message": {"content": "BRCA2 has a median expression of 42."}},
            {"done_reason": "length", "message": {"content": '{"operation":"list_genes"'}},
        ]
        for completion in cases:
            with self.subTest(completion=completion):
                with (
                    httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json=completion)
                    )) as client,
                    patch("app.agent.get_targets") as get_targets,
                ):
                    with self.assertRaises(AgentError):
                        ask("What are the main genes for breast cancer?", client)
                get_targets.assert_not_called()

    async def test_api_renders_markdown_with_raw_html_disabled(self):
        result = {
            "answer": "**Example**\nSecond line\n\n- Item\n\n<b>Raw HTML</b>",
            "tools_used": [],
        }
        with patch("app.main.ask", return_value=result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/chat", json={"question": "How can you help me?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("<strong>Example</strong><br />", payload["answer_html"])
        self.assertIn("<li>Item</li>", payload["answer_html"])
        self.assertIn("&lt;b&gt;Raw HTML&lt;/b&gt;", payload["answer_html"])

    async def test_api_keeps_simple_default_and_returns_the_advanced_table_and_sql(self):
        simple = {"answer": "Lung cancer genes.", "genes": ["RET"], "tools_used": ["get_targets"]}
        advanced = {
            "answer": "Find shared genes.",
            "columns": ["gene"],
            "rows": [["BRCA2"]],
            "sql": "SELECT gene FROM expressions",
            "truncated": False,
            "tools_used": ["query_expressions"],
        }
        with (
            patch("app.main.ask", return_value=simple) as ask,
            patch("app.main.ask_advanced", return_value=advanced) as ask_advanced,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                simple_response = await client.post("/api/chat", json={"question": "Lung cancer genes?"})
                advanced_response = await client.post(
                    "/api/chat", json={"question": "Which genes are shared?", "is_advanced": True}
                )

        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[0], "Lung cancer genes?")
        ask_advanced.assert_called_once()
        self.assertEqual(ask_advanced.call_args.args[0], "Which genes are shared?")
        self.assertEqual(simple_response.status_code, 200)
        self.assertEqual(simple_response.json()["genes"], ["RET"])
        self.assertEqual(advanced_response.status_code, 200)
        self.assertEqual(
            advanced_response.json(), {**advanced, "answer_html": "<p>Find shared genes.</p>\n"}
        )
