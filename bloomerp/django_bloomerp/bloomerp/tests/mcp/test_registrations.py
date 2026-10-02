from django.test import SimpleTestCase

from bloomerp.router import router
from bloomerp.views.api import mutations  # noqa: F401
from bloomerp.views.api.sql import accessible_tables  # noqa: F401
from bloomerp.views.api.sql import execute  # noqa: F401


class McpRouteRegistrationTests(SimpleTestCase):
    def test_mutation_and_sql_routes_are_registered_as_mcp_tools(self) -> None:
        """Expose the mutation, SQL execution, and accessible-table contracts."""
        routes = {route.mcp_tool_name: route for route in router.get_mcp_routes()}

        self.assertIn("api_assistant_mutation_catalog", routes)
        self.assertIn("api_assistant_mutations", routes)
        self.assertIn("api_sql_execute", routes)
        self.assertIn("api_sql_accessible_tables", routes)

        mutation = routes["api_assistant_mutations"].mcp
        self.assertTrue(mutation.destructive_hint)
        self.assertEqual(
            sorted(mutation.get_input_schema()["properties"]),
            ["data", "object_id", "operation", "resource"],
        )

        sql = routes["api_sql_execute"].mcp
        self.assertTrue(sql.read_only_hint)
        self.assertEqual(
            sorted(sql.get_input_schema()["properties"]),
            ["page", "page_size", "query"],
        )

        tables = routes["api_sql_accessible_tables"].mcp
        self.assertTrue(tables.read_only_hint)
        self.assertEqual(
            sorted(tables.get_input_schema()["properties"]),
            ["page", "page_size", "refresh", "search"],
        )
        self.assertIn("databases", tables.get_output_schema()["properties"])
