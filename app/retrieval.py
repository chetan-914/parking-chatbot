import weaviate

from langchain_openai import OpenAIEmbeddings
from weaviate.classes.query import MetadataQuery

from app.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    """Create the OpenAI embedding model."""
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_key,
    )


def search_static(
    query: str,
    k: int = 3,
) -> list[dict]:
    """
    Search the Weaviate knowledge collection.

    Returns matching documents with their metadata.
    """
    if not query.strip():
        return []

    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(query)

    client = weaviate.connect_to_local(
        host=settings.weaviate_host,
        port=settings.weaviate_http_port,
        grpc_port=settings.weaviate_grpc_port,
    )

    try:
        if not client.collections.exists(
            settings.weaviate_collection
        ):
            raise RuntimeError(
                f"Weaviate collection "
                f"'{settings.weaviate_collection}' does not exist."
            )

        collection = client.collections.get(
            settings.weaviate_collection
        )

        response = collection.query.near_vector(
            near_vector=query_vector,
            limit=k,
            return_properties=[
                "text",
                "source",
                "section",
                "chunk_index",
            ],
            return_metadata=MetadataQuery(
                distance=True,
            ),
        )

        results = []

        for item in response.objects:
            properties = item.properties

            results.append({
                "text": properties.get("text", ""),
                "source": properties.get("source", ""),
                "section": properties.get("section", ""),
                "chunk_index": properties.get("chunk_index", 0),
                "distance": (
                    item.metadata.distance
                    if item.metadata
                    else None
                ),
            })

        return results

    finally:
        client.close()


def format_search_results(
    results: list[dict],
) -> str:
    """Format retrieved documents for the LLM context."""
    if not results:
        return "No relevant knowledge documents were found."

    formatted_documents = []

    for index, result in enumerate(results, start=1):
        document = f"""
[Document {index}]
Source: {result["source"]}
Section: {result["section"]}

Content:
{result["text"]}
"""
        formatted_documents.append(document.strip())

    return "\n\n---\n\n".join(formatted_documents)