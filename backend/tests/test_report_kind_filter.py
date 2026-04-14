import unittest

from app.routers.reports import _kind_filter_clause


class TestReportKindFilter(unittest.TestCase):
    def test_tenant_export_clause_contains_marker(self):
        expr = _kind_filter_clause("tenant_export")
        self.assertIn("LIKE", str(expr))
        self.assertIn("tenant_export", str(getattr(expr.right, "value", "")))

    def test_report_clause_is_negated_marker(self):
        expr = _kind_filter_clause("report")
        self.assertIn("NOT LIKE", str(expr))
        self.assertIn("tenant_export", str(getattr(expr.right, "value", "")))


if __name__ == "__main__":
    unittest.main()
