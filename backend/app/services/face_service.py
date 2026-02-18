"""Face detection, encoding, and matching service using DeepFace."""

import numpy as np
from deepface import DeepFace

from app.config import SIMILARITY_THRESHOLD, USE_SUPABASE

if USE_SUPABASE:
    from app.supabase_client import get_supabase


def detect_and_encode(image_path: str) -> list[dict]:
    """
    Detect faces in an image and generate embeddings.
    Returns list of dicts: [{"embedding": [...], "location": [x, y, w, h]}]
    """
    try:
        # Use DeepFace to extract face embeddings
        # model_name="Facenet" gives 128d embeddings and is fast
        results = DeepFace.represent(
            img_path=image_path,
            model_name="Facenet",
            detector_backend="opencv",
            enforce_detection=False,
        )

        faces = []
        for result in results:
            embedding = result.get("embedding", [])
            face_area = result.get("facial_area", {})

            if embedding and len(embedding) > 0:
                location = [
                    face_area.get("x", 0),
                    face_area.get("y", 0),
                    face_area.get("w", 0),
                    face_area.get("h", 0),
                ]
                faces.append({
                    "embedding": embedding,
                    "location": location,
                })

        return faces

    except Exception as e:
        # If no face is found or processing fails, return empty
        print(f"Face detection error: {e}")
        return []


def encode_selfie(image_path: str) -> list[float] | np.ndarray | None:
    """
    Encode a single selfie image. Returns the embedding of the first
    (largest) face found, or None if no face detected.
    """
    faces = detect_and_encode(image_path)
    if not faces:
        return None
    # Return the first face's embedding
    return faces[0]["embedding"]


def find_matches(selfie_embedding: list[float] | np.ndarray, stored_embeddings: list[dict], threshold: float = None) -> list[dict]:
    """
    Compare a selfie embedding against stored face embeddings using cosine similarity.
    Returns list of matches sorted by similarity (best first).

    Each stored_embedding dict must have: embedding, photo_id

    NOTE: This is a fallback for SQLite mode. For Supabase, use find_matches_vector() instead.
    """
    if threshold is None:
        threshold = SIMILARITY_THRESHOLD

    selfie_vec = np.array(selfie_embedding)
    selfie_norm = np.linalg.norm(selfie_vec)
    if selfie_norm == 0:
        return []

    matches = []
    seen_photos = set()

    for stored in stored_embeddings:
        stored_vec = np.array(stored["embedding"])
        stored_norm = np.linalg.norm(stored_vec)

        if stored_norm == 0:
            continue

        # Cosine similarity (higher = more similar, 1.0 = identical)
        cosine_sim = float(np.dot(selfie_vec, stored_vec) / (selfie_norm * stored_norm))

        if cosine_sim >= threshold and stored["photo_id"] not in seen_photos:
            matches.append({
                "photo_id": stored["photo_id"],
                "similarity": round(cosine_sim, 4),
            })
            seen_photos.add(stored["photo_id"])

    # Sort by similarity descending
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches


def find_matches_vector(event_id: str, selfie_embedding: list[float] | np.ndarray, threshold: float = None) -> list[dict]:
    """
    Compare a selfie embedding against stored face embeddings using pgvector.
    Uses indexed vector search for O(log n) performance instead of O(n).

    This is the recommended method for Supabase/PostgreSQL with pgvector.

    Args:
        event_id: The event UUID
        selfie_embedding: List or array of 128 float values
        threshold: Minimum similarity score (0-1). Defaults to SIMILARITY_THRESHOLD.

    Returns:
        List of matches: [{"photo_id": uuid, "similarity": float}]
    """
    if not USE_SUPABASE:
        raise RuntimeError("find_matches_vector requires Supabase with pgvector. Use find_matches() instead.")

    if threshold is None:
        threshold = SIMILARITY_THRESHOLD

    # Convert embedding to vector string format for pgvector
    if isinstance(selfie_embedding, np.ndarray):
        selfie_embedding = selfie_embedding.tolist()

    # Format as vector string: '[0.1, 0.2, ...]'
    vector_str = f"[{','.join(map(str, selfie_embedding))}]"

    try:
        supabase = get_supabase()

        # Call the SQL function we created in the migration
        result = supabase.rpc(
            "find_similar_faces",
            {
                "target_embedding": vector_str,
                "event_id_param": event_id,
                "threshold": threshold,
            }
        ).execute()

        matches = []
        seen_photos = set()

        if result.data:
            for row in result.data:
                photo_id = row.get("photo_id")
                if photo_id and photo_id not in seen_photos:
                    matches.append({
                        "photo_id": photo_id,
                        "similarity": round(float(row.get("similarity", 0)), 4),
                    })
                    seen_photos.add(photo_id)

        return matches

    except Exception as e:
        print(f"Vector search error: {e}")
        # Fallback to sequential search if vector search fails
        from app.database import get_embeddings_for_event
        stored = get_embeddings_for_event(event_id)
        return find_matches(selfie_embedding, stored, threshold)


def normalize_vector(vec: list[float] | np.ndarray) -> list[float]:
    """
    Normalize a vector to unit length for better cosine similarity results.
    This is important for pgvector which expects normalized vectors for optimal performance.
    """
    arr = np.array(vec)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return vec.tolist() if isinstance(vec, list) else vec
    return (arr / norm).tolist()


def embedding_to_vector_str(embedding: list[float] | np.ndarray) -> str:
    """Convert embedding to pgvector string format."""
    if isinstance(embedding, np.ndarray):
        embedding = embedding.tolist()
    return f"[{','.join(map(str, embedding))}]"
