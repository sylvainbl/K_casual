import unittest

from app.tools import get_expressions


class ToolsTest(unittest.TestCase):
    def test_shared_gene_keeps_the_median_for_the_requested_cancer(self):
        self.assertEqual(get_expressions("breast", ["BRCA2"]), {"BRCA2": 0.032})
        self.assertEqual(get_expressions("pancreatic", ["BRCA2"]), {"BRCA2": 0.112})
