def chunk_text(text: str, chunk_size: int = 3000, overlap_ratio: float = 0.2) -> list[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []

    overlap = int(chunk_size * overlap_ratio)
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap

    return chunks
