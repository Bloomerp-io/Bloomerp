"""Display SQL statements executed by the agent's SQL tool."""

from uuid import UUID

from django.http import HttpRequest
from django.utils.html import format_html

from bloomerp.agents.definition import (
    AIArtifactCandidate,
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactRenderer,
    AIArtifactToolResult,
    AIArtifactToolResultAdapter,
    AIArtifactTypeDefinition,
)


class SqlQueryArtifactPayload(AIArtifactPayload):
    """Store the SQL statement from a completed tool call."""

    query: str


def describe_sql_query(payload: SqlQueryArtifactPayload) -> AIArtifactDescription:
    """Describe the executed SQL statement without running it again."""
    return AIArtifactDescription(title="SQL Query", summary=payload.query)


class SqlQueryArtifactRenderer(AIArtifactRenderer[SqlQueryArtifactPayload]):
    """Present the executed statement as escaped, formatted code."""

    @classmethod
    def render(
        cls, artifact_id: UUID, payload: SqlQueryArtifactPayload, request: HttpRequest
    ) -> str:
        """Show a collapsed Query badge that expands to escaped SQL text."""
        return format_html(
            '<details>'
            '<summary class="badge badge-secondary cursor-pointer gap-2 list-none">'
            'Query <i class="fa-solid fa-chevron-down" aria-hidden="true"></i>'
            '</summary>'
            '<pre class="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg border border-gray-200 p-3 text-xs">'
            '<code>{}</code></pre>'
            '</details>',
            payload.query,
        )


class SqlQueryToolResultAdapter(AIArtifactToolResultAdapter):
    """Attach the SQL statement after a successful execution tool call."""

    key = "called_sql_query"
    tool_names = ("api_sql_execute",)

    @classmethod
    def adapt(
        cls, result: AIArtifactToolResult, request: HttpRequest
    ) -> list[AIArtifactCandidate]:
        """Copy the successful call's SQL argument into a displayed artifact."""
        if result.tool_name not in cls.tool_names or result.result.get("isError"):
            return []
        query = result.arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return []
        payload = SqlQueryArtifactPayload(query=query.strip())
        return [
            AIArtifactCandidate(key="query", payload=payload.model_dump(mode="json"))
        ]


SQL_QUERY_ARTIFACT = AIArtifactTypeDefinition[SqlQueryArtifactPayload](
    key="sql_query",
    label="SQL Query",
    model=SqlQueryArtifactPayload,
    describe=describe_sql_query,
    render_cls=SqlQueryArtifactRenderer,
    tool_result_adapters=(SqlQueryToolResultAdapter,),
    icon="fa-code",
)
