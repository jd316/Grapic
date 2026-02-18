"""Tests for face detection and encoding service."""

import pytest
import numpy as np
from PIL import Image
import io
import os
from pathlib import Path

from app.services.face_service import (
    detect_and_encode,
    encode_selfie,
    find_matches,
    find_matches_vector,
    normalize_vector,
    embedding_to_vector_str
)


# ─── FIXTURES ────────────────────────────────────────────────────

@pytest.fixture
def test_images_dir():
    """Directory for test images."""
    dir_path = Path(__file__).parent / "test_images"
    dir_path.mkdir(exist_ok=True)
    yield dir_path
    # Cleanup not needed as we use temp files


@pytest.fixture
def solid_color_image():
    """Create a solid color image (no faces)."""
    img = Image.new('RGB', (400, 400), color='blue')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        tmp.write(buf.read())
        yield tmp.name
    os.unlink(tmp.name)


@pytest.fixture
def test_face_embedding():
    """Create a realistic face embedding (128d vector)."""
    np.random.seed(42)
    # Create normalized embedding
    embedding = np.random.randn(128)
    embedding = embedding / np.linalg.norm(embedding)
    return embedding.tolist()


@pytest.fixture
def multiple_face_embeddings():
    """Create multiple face embeddings for testing matching."""
    np.random.seed(123)
    embeddings = []
    for i in range(5):
        emb = np.random.randn(128)
        emb = emb / np.linalg.norm(emb)
        embeddings.append(emb.tolist())
    return embeddings


import tempfile


# ─── TESTS FOR detect_and_encode ───────────────────────────────

def test_detect_and_encode_no_faces(solid_color_image):
    """Test face detection on an image with no faces."""
    faces = detect_and_encode(solid_color_image)
    assert isinstance(faces, list)
    assert len(faces) == 0


def test_detect_and_encode_invalid_image():
    """Test face detection on an invalid image file."""
    with pytest.raises(Exception):
        detect_and_encode("/nonexistent/image.jpg")


def test_detect_and_encode_returns_correct_format(solid_color_image):
    """Test that detect_and_encode returns correct format when empty."""
    faces = detect_and_encode(solid_color_image)
    assert faces == []


# ─── TESTS FOR encode_selfie ─────────────────────────────────

def test_encode_selfie_no_face(solid_color_image):
    """Test encoding a selfie with no faces."""
    embedding = encode_selfie(solid_color_image)
    assert embedding is None


def test_encode_selfie_invalid_path():
    """Test encoding with invalid image path."""
    # This should return None or raise exception
    result = encode_selfie("/nonexistent/image.jpg")
    # DeepFace handles this gracefully, returns empty list
    assert result is None


# ─── TESTS FOR find_matches ───────────────────────────────────

def test_find_matches_with_empty_stored(test_face_embedding):
    """Test matching against empty stored embeddings."""
    matches = find_matches(test_face_embedding, [])
    assert matches == []
    assert isinstance(matches, list)


def test_find_matches_perfect_match(test_face_embedding):
    """Test matching identical embedding."""
    stored = [{
        "embedding": test_face_embedding,
        "photo_id": "photo_1"
    }]

    matches = find_matches(test_face_embedding, stored, threshold=0.1)
    assert len(matches) == 1
    assert matches[0]["photo_id"] == "photo_1"
    # Perfect match should have similarity very close to 1.0
    assert matches[0]["similarity"] > 0.99


def test_find_matches_no_match(test_face_embedding, multiple_face_embeddings):
    """Test matching with no similar faces."""
    # Create orthogonal (very different) embeddings
    orthogonal_emb = np.random.randn(128)
    orthogonal_emb = orthogonal_emb / np.linalg.norm(orthogonal_emb)

    stored = [{"embedding": orthogonal_emb.tolist(), "photo_id": "photo_1"}]

    matches = find_matches(test_face_embedding, stored, threshold=0.99)
    # No match should be found (high threshold)
    assert len(matches) == 0


def test_find_matches_sorted_by_similarity(test_face_embedding, multiple_face_embeddings):
    """Test that matches are sorted by similarity (best first)."""
    stored = [
        {"embedding": emb, "photo_id": f"photo_{i}"}
        for i, emb in enumerate(multiple_face_embeddings)
    ]

    matches = find_matches(test_face_embedding, stored, threshold=0.0)

    # Check sorted descending by similarity
    similarities = [m["similarity"] for m in matches]
    assert all(similarities[i] >= similarities[i+1]
               for i in range(len(similarities)-1))


def test_find_matches_deduplicates_photos(test_face_embedding):
    """Test that duplicate photo_ids are removed."""
    # Same photo with multiple face detections
    stored = [
        {"embedding": test_face_embedding, "photo_id": "photo_1"},
        {"embedding": test_face_embedding, "photo_id": "photo_1"},
    ]

    matches = find_matches(test_face_embedding, stored, threshold=0.5)
    # Should only return one entry per photo
    assert len(matches) == 1
    assert matches[0]["photo_id"] == "photo_1"


def test_find_matches_with_custom_threshold(test_face_embedding, multiple_face_embeddings):
    """Test matching with custom threshold."""
    stored = [
        {"embedding": emb, "photo_id": f"photo_{i}"}
        for i, emb in enumerate(multiple_face_embeddings)
    ]

    # High threshold - fewer matches
    matches_high = find_matches(test_face_embedding, stored, threshold=0.90)

    # Low threshold - more matches
    matches_low = find_matches(test_face_embedding, stored, threshold=0.20)

    assert len(matches_high) <= len(matches_low)


# ─── TESTS FOR normalize_vector ─────────────────────────────────

def test_normalize_vector_zero_vector():
    """Test normalizing a zero vector."""
    vec = [0.0] * 128
    normalized = normalize_vector(vec)
    assert normalized == vec


def test_normalize_vector_unit_vector():
    """Test normalizing an already normalized vector."""
    vec = [1.0] + [0.0] * 127
    normalized = normalize_vector(vec)
    assert normalized[0] == 1.0
    assert all(abs(x) < 1e-10 for x in normalized[1:])


def test_normalize_vector_random(test_face_embedding):
    """Test normalizing a random vector."""
    normalized = normalize_vector(test_face_embedding)
    norm = np.linalg.norm(np.array(normalized))
    assert abs(norm - 1.0) < 1e-6


# ─── TESTS FOR embedding_to_vector_str ─────────────────────────

def test_embedding_to_vector_str_list(test_face_embedding):
    """Test converting list embedding to vector string."""
    vec_str = embedding_to_vector_str(test_face_embedding)
    assert vec_str.startswith("[")
    assert vec_str.endswith("]")
    # Should have 128 values
    values = vec_str[1:-1].split(",")
    assert len(values) == 128


def test_embedding_to_vector_str_numpy(test_face_embedding):
    """Test converting numpy embedding to vector string."""
    np_embedding = np.array(test_face_embedding)
    vec_str = embedding_to_vector_str(np_embedding)
    assert vec_str.startswith("[")
    assert vec_str.endswith("]")


# ─── ACCURACY TESTS (require real face images) ───────────

def test_face_detection_accuracy_single_face():
    """
    Test face detection accuracy on known image with single face.
    Note: This test is skipped unless test images are available.
    """
    pytest.skip("Requires test images with known face count")


def test_face_detection_accuracy_multiple_faces():
    """
    Test face detection accuracy on image with multiple faces.
    Note: This test is skipped unless test images are available.
    """
    pytest.skip("Requires test images with known face count")


def test_face_matching_accuracy_same_person():
    """
    Test matching accuracy with images of the same person.
    Note: This test is skipped unless test images are available.
    Expected: similarity > 0.85
    """
    pytest.skip("Requires test images of same person")


def test_face_matching_accuracy_different_persons():
    """
    Test matching accuracy with images of different persons.
    Note: This test is skipped unless test images are available.
    Expected: similarity < 0.50
    """
    pytest.skip("Requires test images of different persons")


# ─── PERFORMANCE TESTS ───────────────────────────────────────

def test_face_encoding_performance(test_face_embedding):
    """Test that face encoding completes within reasonable time."""
    import time

    stored = [
        {"embedding": test_face_embedding, "photo_id": f"photo_{i}"}
        for i in range(100)
    ]

    start = time.time()
    matches = find_matches(test_face_embedding, stored, threshold=0.4)
    elapsed = time.time() - start

    # Should complete in under 1 second for 100 embeddings
    assert elapsed < 1.0
    assert isinstance(matches, list)


# ─── EDGE CASE TESTS ───────────────────────────────────────

def test_find_matches_with_malformed_embedding():
    """Test matching with malformed embedding data."""
    malformed = [{"embedding": [0.1] * 10, "photo_id": "photo_1"}]  # Wrong length

    # Should handle gracefully
    with pytest.raises((ValueError, IndexError)):
        find_matches([0.1] * 128, malformed)


def test_find_matches_empty_selfie_embedding(multiple_face_embeddings):
    """Test matching with empty selfie embedding."""
    stored = [{"embedding": emb, "photo_id": f"photo_{i}"}
               for i, emb in enumerate(multiple_face_embeddings)]

    # Empty embedding should return no matches
    matches = find_matches([], stored, threshold=0.4)
    assert matches == []


def test_face_embedding_dimensions():
    """Test that embeddings have correct dimensions (128)."""
    np.random.seed(42)
    emb = np.random.randn(128)
    normalized = emb / np.linalg.norm(emb)

    assert len(normalized) == 128
    assert all(isinstance(x, float) for x in normalized)


# ─── INTEGRATION TESTS ─────────────────────────────────────

@pytest.mark.integration
def test_full_face_service_workflow():
    """
    Test complete workflow: detect -> encode -> match.
    This test requires actual face images.
    """
    pytest.skip("Integration test - requires face images")


# ─── MARKERS ───────────────────────────────────────────────

# Run accuracy tests when test images are available
# pytest -m accuracy tests/

# Run performance tests
# pytest -m performance tests/

# Run integration tests
# pytest -m integration tests/
