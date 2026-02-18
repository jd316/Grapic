"""Pytest configuration and fixtures."""

import pytest
import os
import tempfile
from pathlib import Path


@pytest.fixture
def temp_upload_dir():
    """Create a temporary upload directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_dir = os.environ.get("UPLOAD_DIR")
        os.environ["UPLOAD_DIR"] = tmpdir
        yield tmpdir
        if old_dir:
            os.environ["UPLOAD_DIR"] = old_dir
        else:
            os.environ.pop("UPLOAD_DIR", None)


@pytest.fixture
def test_image(temp_upload_dir):
    """Create a test image file."""
    from PIL import Image
    import io

    # Create a simple test image
    img = Image.new('RGB', (100, 100), color='red')
    img_path = Path(temp_upload_dir) / "test_image.jpg"
    img.save(img_path)

    return str(img_path)


@pytest.fixture
def mock_db():
    """Mock database connection for testing."""
    # This would typically use pytest-mock or similar
    pass


@pytest.fixture(autouse=True)
def set_test_env():
    """Set test environment variables."""
    os.environ["GRAPIC_ENV"] = "test"
    os.environ["USE_SELF_HOSTED_PG"] = "false"
    os.environ["USE_SUPABASE"] = "false"
    yield
    # Cleanup
    os.environ.pop("GRAPIC_ENV", None)
