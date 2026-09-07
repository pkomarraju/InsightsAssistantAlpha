import json

from dotenv import load_dotenv
from mcp.server import MCPServer

from insights_assistant.rag.retriever import RelationshipNotesRetriever, RetrieverError

load_dotenv()

server = MCPServer("relationship-notes")

_retriever: RelationshipNotesRetriever | None = None


def _get_retriever() -> RelationshipNotesRetriever:
    global _retriever
    if _retriever is None:
        _retriever = RelationshipNotesRetriever()
    return _retriever


@server.tool()
def search_relationship_notes(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    company_codes: list[str] | None = None,
    max_results: int = 50,
) -> str:
    """Search unstructured relationship-manager notes using semantic similarity and
    optional date and company filters. Use this tool for explicit relationship-risk
    flags, client sentiment, meeting observations, competitor activity, service
    issues, commitments, and follow-up actions."""
    response = {
        "query": query,
        "filters": {
            "date_from": date_from,
            "date_to": date_to,
            "company_codes": company_codes or [],
        },
    }
    try:
        results = _get_retriever().search(
            query=query,
            date_from=date_from,
            date_to=date_to,
            company_codes=company_codes,
            max_results=max_results,
        )
    except (RetrieverError, ValueError) as e:
        response["error"] = str(e)
        response["result_count"] = 0
        response["results"] = []
        return json.dumps(response, indent=2)

    response["result_count"] = len(results)
    response["results"] = results
    return json.dumps(response, indent=2)


if __name__ == "__main__":
    server.run(transport="stdio")
