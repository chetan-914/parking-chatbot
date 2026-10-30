import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import weaviate
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from weaviate.classes.config import Configure, DataType, Property


load_dotenv()

# Configuration
KNOWLEDGE_DIR = Path("knowledge")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

COLLECTION_NAME = os.getenv(
    "WEAVIATE_COLLECTION",
    "ParkingKnowledge",
)

EMBEDDING_MODEL = "text-embedding-3-small"


@dataclass
class DocumentChunk:
    text: str
    source: str
    section: str
    chunk_index: int


def split_text(text: str) -> list[str]:
    """Split text into overlapping character chunks."""
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))

        if end < len(text):
            # Prefer breaking at a paragraph or word boundary.
            boundary = max(
                text.rfind("\n", start, end),
                text.rfind(" ", start, end),
            )

            if boundary > start + CHUNK_SIZE // 2:
                end = boundary

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(end - CHUNK_OVERLAP, start + 1)

    return chunks


def load_markdown_file(file_path: Path) -> list[DocumentChunk]:
    """Load a Markdown file and split it by heading sections."""
    content = file_path.read_text(encoding="utf-8")

    source = str(file_path.relative_to(KNOWLEDGE_DIR.parent))
    sections = []
    current_section = "General"
    current_lines = []

    for line in content.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)$", line)

        if heading:
            if current_lines:
                sections.append(
                    (current_section, "\n".join(current_lines).strip())
                )

            current_section = heading.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append(
            (current_section, "\n".join(current_lines).strip())
        )

    chunks = []
    chunk_index = 0

    for section, section_text in sections:
        if not section_text:
            continue

        for text in split_text(section_text):
            chunks.append(
                DocumentChunk(
                    text=text,
                    source=source,
                    section=section,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    return chunks


def load_all_documents() -> list[DocumentChunk]:
    """Load all Markdown files recursively."""
    if not KNOWLEDGE_DIR.exists():
        raise FileNotFoundError(
            f"Knowledge directory not found: {KNOWLEDGE_DIR}"
        )

    files = sorted(KNOWLEDGE_DIR.rglob("*.md"))
    chunks = []

    for file_path in files:
        file_chunks = load_markdown_file(file_path)
        chunks.extend(file_chunks)
        print(f"Loaded {file_path}: {len(file_chunks)} chunks")

    return chunks


def create_collection(client):
    """Create the Weaviate collection if it does not exist."""
    if client.collections.exists(COLLECTION_NAME):
        return client.collections.get(COLLECTION_NAME)

    client.collections.create(
        name=COLLECTION_NAME,
        vector_config=Configure.Vectors.self_provided(),
        properties=[
            Property(name="text", data_type=DataType.TEXT),
            Property(name="source", data_type=DataType.TEXT),
            Property(name="section", data_type=DataType.TEXT),
            Property(name="chunk_index", data_type=DataType.INT),
        ],
    )

    print(f"Created Weaviate collection: {COLLECTION_NAME}")

    return client.collections.get(COLLECTION_NAME)


def store_chunks(collection, chunks: list[DocumentChunk]):
    """Embed chunks and upsert them using the named default vector."""
    if not chunks:
        print("No Markdown chunks found.")
        return

    embeddings = OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
    )

    texts = [chunk.text for chunk in chunks]
    vectors = embeddings.embed_documents(texts)

    inserted = 0
    updated = 0

    for chunk, vector in zip(chunks, vectors):
        object_uuid = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{chunk.source}:{chunk.chunk_index}",
            )
        )

        properties = {
            "text": chunk.text,
            "source": chunk.source,
            "section": chunk.section,
            "chunk_index": chunk.chunk_index,
        }

        named_vector = {
            "default": vector,
        }

        if collection.data.exists(uuid=object_uuid):
            collection.data.replace(
                uuid=object_uuid,
                properties=properties,
                vector=named_vector,
            )
            updated += 1
        else:
            collection.data.insert(
                uuid=object_uuid,
                properties=properties,
                vector=named_vector,
            )
            inserted += 1

    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    print(f"Total processed: {len(chunks)}")


def main():
    client = None

    try:
        chunks = load_all_documents()

        if not chunks:
            print("No Markdown documents to ingest.")
            return

        client = weaviate.connect_to_local(
            host=os.getenv("WEAVIATE_HOST", "localhost"),
            port=int(os.getenv("WEAVIATE_HTTP_PORT", "8080")),
            grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
        )

        collection = create_collection(client)
        store_chunks(collection, chunks)

        print("Knowledge ingestion completed.")

    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()