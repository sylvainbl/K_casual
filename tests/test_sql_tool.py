import unittest
from unittest.mock import patch

from app.tools import MAX_ROWS, SQLQueryError, query_expressions


class SQLToolTest(unittest.TestCase):
    def test_highest_recorded_median_keeps_the_gene_and_value_for_each_cancer(self):
        result = query_expressions("""
            WITH ranked AS (
                SELECT *, RANK() OVER (
                    PARTITION BY cancer_indication ORDER BY median_value DESC
                ) AS position
                FROM expressions
            )
            SELECT cancer_indication, gene, median_value FROM ranked
            WHERE position = 1 ORDER BY cancer_indication, gene
        """)
        self.assertEqual(result["columns"], ["cancer_indication", "gene", "median_value"])
        self.assertEqual(len(result["rows"]), 10)
        self.assertIn(["breast", "ESR1", 0.716], result["rows"])
        self.assertIn(["lung", "RET", 0.763], result["rows"])
        self.assertFalse(result["truncated"])

    def test_count_and_intersection_are_supported(self):
        result = query_expressions("SELECT COUNT(*) AS total FROM expressions")
        self.assertEqual(result["rows"], [[81]])
        result = query_expressions("""
            SELECT gene FROM expressions WHERE cancer_indication = 'breast'
            INTERSECT
            SELECT gene FROM expressions WHERE cancer_indication = 'prostate'
        """)
        self.assertEqual(result["rows"], [["BRCA2"]])

    def test_empty_result_has_columns_and_is_not_truncated(self):
        result = query_expressions(
            "SELECT gene FROM expressions WHERE cancer_indication = 'esophageal'"
        )
        self.assertEqual(result, {"columns": ["gene"], "rows": [], "truncated": False})

    def test_syntax_and_unknown_columns_are_correctable(self):
        for sql in ("SELEC gene FROM expressions", 'SELECT "missing_column" FROM expressions'):
            with self.subTest(sql=sql), self.assertRaises(SQLQueryError) as raised:
                query_expressions(sql)
            self.assertTrue(raised.exception.retryable)

    def test_disallowed_sql_is_rejected_without_correction(self):
        for sql in (
            "DELETE FROM expressions",
            "SELECT name FROM sqlite_schema",
            "ATTACH ':memory:' AS other",
            "PRAGMA table_info(expressions)",
            "SELECT sqlite_version()",
            "SELECT gene FROM expressions; SELECT gene FROM expressions",
        ):
            with self.subTest(sql=sql), self.assertRaises(SQLQueryError) as raised:
                query_expressions(sql)
            self.assertFalse(raised.exception.retryable)

    def test_row_limit_is_reported_and_execution_time_is_bounded(self):
        result = query_expressions(
            "SELECT a.gene, b.gene FROM expressions AS a CROSS JOIN expressions AS b"
        )
        self.assertEqual(len(result["rows"]), MAX_ROWS)
        self.assertTrue(result["truncated"])

        with patch("app.tools.QUERY_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(SQLQueryError, "time limit") as raised:
                query_expressions(
                    "SELECT COUNT(*) FROM expressions AS a CROSS JOIN expressions AS b"
                )
        self.assertFalse(raised.exception.retryable)
