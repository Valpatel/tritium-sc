# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for app.ai.embeddings -- EmbeddingGenerator and VectorStore.

Mocks torch, transformers, cv2, and PIL to avoid heavy GPU/model dependencies.
Uses tempfile.TemporaryDirectory for VectorStore disk persistence verification.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_torch(cuda_available: bool = False):
    """Build a mock torch module with cuda availability control."""
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = cuda_available
    mock_torch.no_grad.return_value.__enter__ = MagicMock()
    mock_torch.no_grad.return_value.__exit__ = MagicMock(return_value=False)
    return mock_torch


def _make_mock_model():
    """Build a mock CLIPModel with get_image_features/get_text_features."""
    model = MagicMock()
    model.to.return_value = model
    model.eval.return_value = None

    # get_image_features returns a tensor-like object
    img_output = MagicMock()
    img_output.cpu.return_value.numpy.return_value = np.array([[0.5, 0.5, 0.5, 0.5]])
    model.get_image_features.return_value = img_output

    # get_text_features returns a tensor-like object
    txt_output = MagicMock()
    txt_output.cpu.return_value.numpy.return_value = np.array([[0.3, 0.4, 0.5, 0.6]])
    model.get_text_features.return_value = txt_output

    return model


def _make_mock_processor():
    """Build a mock CLIPProcessor."""
    processor = MagicMock()
    # Return dict-like inputs with .to() on each value
    mock_tensor = MagicMock()
    mock_tensor.to.return_value = mock_tensor
    processor.return_value = {"pixel_values": mock_tensor}
    return processor


def _normalized(vec: list[float]) -> list[float]:
    """Normalize a vector for test comparison."""
    arr = np.array(vec)
    return (arr / np.linalg.norm(arr)).tolist()


# ---------------------------------------------------------------------------
# EmbeddingGenerator.__init__
# ---------------------------------------------------------------------------

class TestEmbeddingGeneratorInit:
    """Constructor: model loading, device selection, error handling."""

    def test_raises_when_clip_unavailable(self):
        """RuntimeError when CLIP_AVAILABLE or TORCH_AVAILABLE is False."""
        with patch("app.ai.embeddings.CLIP_AVAILABLE", False), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True):
            from app.ai.embeddings import EmbeddingGenerator
            with pytest.raises(RuntimeError, match="CLIP not available"):
                EmbeddingGenerator()

    def test_raises_when_torch_unavailable(self):
        """RuntimeError when TORCH_AVAILABLE is False."""
        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", False):
            from app.ai.embeddings import EmbeddingGenerator
            with pytest.raises(RuntimeError, match="CLIP not available"):
                EmbeddingGenerator()

    def test_raises_when_both_unavailable(self):
        """RuntimeError when both are False."""
        with patch("app.ai.embeddings.CLIP_AVAILABLE", False), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", False):
            from app.ai.embeddings import EmbeddingGenerator
            with pytest.raises(RuntimeError):
                EmbeddingGenerator()

    def test_auto_device_cpu_when_no_cuda(self):
        """Defaults to cpu when torch.cuda.is_available() is False."""
        mock_torch = _make_mock_torch(cuda_available=False)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator()
            assert gen.device == "cpu"

    def test_auto_device_cuda_when_available(self):
        """Defaults to cuda when torch.cuda.is_available() is True."""
        mock_torch = _make_mock_torch(cuda_available=True)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator()
            assert gen.device == "cuda"

    def test_explicit_device_overrides_auto(self):
        """Explicit device= parameter overrides auto-detection."""
        mock_torch = _make_mock_torch(cuda_available=True)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator(device="cpu")
            assert gen.device == "cpu"

    def test_custom_model_name(self):
        """Custom model_name is passed to from_pretrained."""
        mock_torch = _make_mock_torch(cuda_available=False)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            EmbeddingGenerator(model_name="openai/clip-vit-large-patch14")

            MockCLIP.from_pretrained.assert_called_once_with("openai/clip-vit-large-patch14")
            MockProc.from_pretrained.assert_called_once_with("openai/clip-vit-large-patch14")

    def test_model_set_to_eval(self):
        """Model is put in eval mode after loading."""
        mock_torch = _make_mock_torch(cuda_available=False)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            EmbeddingGenerator()

            mock_model.eval.assert_called_once()

    def test_model_moved_to_device(self):
        """Model.to(device) is called with the resolved device."""
        mock_torch = _make_mock_torch(cuda_available=False)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            EmbeddingGenerator(device="cpu")

            mock_model.to.assert_called_with("cpu")


# ---------------------------------------------------------------------------
# EmbeddingGenerator.embed_image
# ---------------------------------------------------------------------------

class TestEmbedImage:
    """Tests for single image embedding generation."""

    def _make_generator(self):
        """Create an EmbeddingGenerator with fully mocked internals."""
        mock_torch = _make_mock_torch(cuda_available=False)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator(device="cpu")

        # Reassign mocks so they stay accessible after the with block
        gen._mock_torch = mock_torch
        gen._mock_model = mock_model
        gen._mock_processor = mock_processor
        return gen

    def test_returns_list_of_floats(self):
        gen = self._make_generator()
        image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            result = gen.embed_image(image)

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_embedding_is_normalized(self):
        gen = self._make_generator()
        image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            result = gen.embed_image(image)

        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"

    def test_bgr_to_rgb_conversion(self):
        gen = self._make_generator()
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.cv2") as mock_cv2, \
             patch("app.ai.embeddings.Image") as MockImage:
            mock_cv2.cvtColor.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
            mock_cv2.COLOR_BGR2RGB = 4  # OpenCV constant
            MockImage.fromarray.return_value = MagicMock()
            gen.embed_image(image)

            mock_cv2.cvtColor.assert_called_once()
            args = mock_cv2.cvtColor.call_args
            np.testing.assert_array_equal(args[0][0], image)

    def test_processor_called_with_pil_image(self):
        gen = self._make_generator()
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            mock_pil = MagicMock()
            MockImage.fromarray.return_value = mock_pil
            gen.embed_image(image)

            gen.processor.assert_called_once()
            call_kwargs = gen.processor.call_args
            assert call_kwargs[1]["images"] is mock_pil
            assert call_kwargs[1]["return_tensors"] == "pt"

    def test_model_get_image_features_called(self):
        gen = self._make_generator()
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            gen.embed_image(image)

            gen.model.get_image_features.assert_called_once()

    def test_embedding_length_matches_model_output(self):
        """Embedding length should match the model output dimension."""
        gen = self._make_generator()
        # Set model output to 8-dim vector
        output = MagicMock()
        output.cpu.return_value.numpy.return_value = np.array([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]])
        gen.model.get_image_features.return_value = output

        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            result = gen.embed_image(image)

        assert len(result) == 8


# ---------------------------------------------------------------------------
# EmbeddingGenerator.embed_images_batch
# ---------------------------------------------------------------------------

class TestEmbedImagesBatch:
    """Tests for batch image embedding generation."""

    def _make_generator(self):
        mock_torch = _make_mock_torch(cuda_available=False)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator(device="cpu")

        gen._mock_torch = mock_torch
        return gen

    def test_empty_list_returns_empty(self):
        gen = self._make_generator()

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image"):
            result = gen.embed_images_batch([])

        assert result == []

    def test_single_image_batch(self):
        gen = self._make_generator()
        images = [np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)]

        # Model returns 1-row output
        output = MagicMock()
        output.cpu.return_value.numpy.return_value = np.array([[0.5, 0.5, 0.5, 0.5]])
        gen.model.get_image_features.return_value = output

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            result = gen.embed_images_batch(images)

        assert len(result) == 1
        assert isinstance(result[0], list)

    def test_multiple_images(self):
        gen = self._make_generator()
        images = [
            np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
            for _ in range(3)
        ]

        # Model returns 3-row output
        output = MagicMock()
        output.cpu.return_value.numpy.return_value = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ])
        gen.model.get_image_features.return_value = output

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            result = gen.embed_images_batch(images)

        assert len(result) == 3

    def test_batching_splits_large_input(self):
        """With batch_size=2 and 5 images, should call model 3 times."""
        gen = self._make_generator()
        images = [
            np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
            for _ in range(5)
        ]

        call_count = 0

        def fake_get_features(**kwargs):
            nonlocal call_count
            call_count += 1
            # Return appropriate sized output based on call
            # Batch sizes: 2, 2, 1
            sizes = [2, 2, 1]
            n = sizes[call_count - 1] if call_count <= len(sizes) else 1
            out = MagicMock()
            out.cpu.return_value.numpy.return_value = np.random.randn(n, 4)
            return out

        gen.model.get_image_features.side_effect = fake_get_features

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            result = gen.embed_images_batch(images, batch_size=2)

        assert call_count == 3
        assert len(result) == 5

    def test_each_embedding_is_normalized(self):
        gen = self._make_generator()
        images = [np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8) for _ in range(2)]

        output = MagicMock()
        output.cpu.return_value.numpy.return_value = np.array([
            [3.0, 4.0, 0.0, 0.0],
            [0.0, 5.0, 12.0, 0.0],
        ])
        gen.model.get_image_features.return_value = output

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            result = gen.embed_images_batch(images)

        for emb in result:
            norm = np.linalg.norm(emb)
            assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"

    def test_processor_called_with_padding(self):
        gen = self._make_generator()
        images = [np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)]

        output = MagicMock()
        output.cpu.return_value.numpy.return_value = np.array([[1.0, 0.0, 0.0, 0.0]])
        gen.model.get_image_features.return_value = output

        with patch("app.ai.embeddings.torch", gen._mock_torch), \
             patch("app.ai.embeddings.Image") as MockImage:
            MockImage.fromarray.return_value = MagicMock()
            gen.embed_images_batch(images)

        call_kwargs = gen.processor.call_args[1]
        assert call_kwargs["padding"] is True
        assert call_kwargs["return_tensors"] == "pt"


# ---------------------------------------------------------------------------
# EmbeddingGenerator.embed_text
# ---------------------------------------------------------------------------

class TestEmbedText:
    """Tests for text embedding generation."""

    def _make_generator(self):
        mock_torch = _make_mock_torch(cuda_available=False)
        mock_model = _make_mock_model()
        mock_processor = _make_mock_processor()

        with patch("app.ai.embeddings.CLIP_AVAILABLE", True), \
             patch("app.ai.embeddings.TORCH_AVAILABLE", True), \
             patch("app.ai.embeddings.torch", mock_torch), \
             patch("app.ai.embeddings.CLIPModel") as MockCLIP, \
             patch("app.ai.embeddings.CLIPProcessor") as MockProc:
            MockCLIP.from_pretrained.return_value = mock_model
            MockProc.from_pretrained.return_value = mock_processor

            from app.ai.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator(device="cpu")

        gen._mock_torch = mock_torch
        return gen

    def test_returns_list_of_floats(self):
        gen = self._make_generator()

        with patch("app.ai.embeddings.torch", gen._mock_torch):
            result = gen.embed_text("a person walking")

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_embedding_is_normalized(self):
        gen = self._make_generator()

        with patch("app.ai.embeddings.torch", gen._mock_torch):
            result = gen.embed_text("a red car")

        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-5

    def test_processor_called_with_text_list(self):
        gen = self._make_generator()

        with patch("app.ai.embeddings.torch", gen._mock_torch):
            gen.embed_text("hello world")

        call_kwargs = gen.processor.call_args[1]
        assert call_kwargs["text"] == ["hello world"]
        assert call_kwargs["padding"] is True

    def test_model_get_text_features_called(self):
        gen = self._make_generator()

        with patch("app.ai.embeddings.torch", gen._mock_torch):
            gen.embed_text("test query")

        gen.model.get_text_features.assert_called_once()


# ---------------------------------------------------------------------------
# VectorStore.__init__ and persistence
# ---------------------------------------------------------------------------

class TestVectorStoreInit:
    """Constructor, load, and save behavior."""

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "nested" / "deep" / "store.json"
            from app.ai.embeddings import VectorStore
            VectorStore(store_path)
            assert store_path.parent.exists()

    def test_initializes_empty_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)
            assert vs.data == {"embeddings": [], "metadata": []}

    def test_loads_existing_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            existing = {
                "embeddings": [[0.1, 0.2]],
                "metadata": [{"id": "test"}],
            }
            store_path.write_text(json.dumps(existing))

            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)
            assert vs.data["embeddings"] == [[0.1, 0.2]]
            assert vs.data["metadata"] == [{"id": "test"}]

    def test_store_path_converted_to_pathlib(self):
        """String paths are converted to Path objects."""
        with tempfile.TemporaryDirectory() as tmp:
            store_path = str(Path(tmp) / "store.json")
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)
            assert isinstance(vs.store_path, Path)


# ---------------------------------------------------------------------------
# VectorStore.add
# ---------------------------------------------------------------------------

class TestVectorStoreAdd:
    """Single embedding addition and disk persistence."""

    def test_add_single_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add([0.1, 0.2, 0.3], {"thumbnail_id": "t1", "target_type": "person"})

            assert len(vs.data["embeddings"]) == 1
            assert vs.data["metadata"][0]["thumbnail_id"] == "t1"

    def test_add_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add([0.5, 0.5], {"thumbnail_id": "t1"})

            # Read back from disk
            with open(store_path) as f:
                data = json.load(f)
            assert len(data["embeddings"]) == 1

    def test_add_multiple_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add([0.1], {"id": "a"})
            vs.add([0.2], {"id": "b"})
            vs.add([0.3], {"id": "c"})

            assert len(vs.data["embeddings"]) == 3
            assert vs.data["metadata"][2]["id"] == "c"


# ---------------------------------------------------------------------------
# VectorStore.add_batch
# ---------------------------------------------------------------------------

class TestVectorStoreAddBatch:
    """Batch embedding addition."""

    def test_add_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            embeddings = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
            metas = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
            vs.add_batch(embeddings, metas)

            assert len(vs.data["embeddings"]) == 3
            assert len(vs.data["metadata"]) == 3

    def test_add_batch_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add_batch([[1.0], [2.0]], [{"x": 1}, {"x": 2}])

            with open(store_path) as f:
                data = json.load(f)
            assert len(data["embeddings"]) == 2

    def test_add_batch_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add([0.1], {"id": "existing"})
            vs.add_batch([[0.2], [0.3]], [{"id": "b1"}, {"id": "b2"}])

            assert len(vs.data["embeddings"]) == 3

    def test_add_batch_empty_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add_batch([], [])
            assert vs.count == 0


# ---------------------------------------------------------------------------
# VectorStore.search
# ---------------------------------------------------------------------------

class TestVectorStoreSearch:
    """Similarity search with cosine distance and filtering."""

    def _make_store(self, tmp: str):
        store_path = Path(tmp) / "store.json"
        from app.ai.embeddings import VectorStore
        return VectorStore(store_path)

    def test_empty_store_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            results = vs.search([0.1, 0.2, 0.3])
            assert results == []

    def test_returns_most_similar_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            # Normalized vectors
            v1 = _normalized([1.0, 0.0, 0.0])
            v2 = _normalized([0.0, 1.0, 0.0])
            v3 = _normalized([0.9, 0.1, 0.0])

            vs.add(v1, {"thumbnail_id": "exact", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v2, {"thumbnail_id": "orthogonal", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v3, {"thumbnail_id": "close", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            query = _normalized([1.0, 0.0, 0.0])
            results = vs.search(query, k=3)

            assert len(results) == 3
            # First result should be the exact match
            assert results[0][0]["thumbnail_id"] == "exact"
            # Second should be close
            assert results[1][0]["thumbnail_id"] == "close"
            # Third should be orthogonal
            assert results[2][0]["thumbnail_id"] == "orthogonal"

    def test_respects_k_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            for i in range(10):
                v = [0.0] * 4
                v[i % 4] = 1.0
                vs.add(_normalized(v), {"thumbnail_id": f"t{i}", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search(_normalized([1.0, 0.0, 0.0, 0.0]), k=3)
            assert len(results) == 3

    def test_filter_by_target_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "p1", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v, {"thumbnail_id": "c1", "target_type": "car", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v, {"thumbnail_id": "p2", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search(v, k=10, target_type="person")
            assert len(results) == 2
            assert all(r[0]["target_type"] == "person" for r in results)

    def test_filter_by_date_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "old", "target_type": "person", "timestamp": "2025-12-01T10:00:00"})
            vs.add(v, {"thumbnail_id": "new", "target_type": "person", "timestamp": "2026-02-15T10:00:00"})

            results = vs.search(v, k=10, date_from="2026-01-01")
            assert len(results) == 1
            assert results[0][0]["thumbnail_id"] == "new"

    def test_filter_by_date_to(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "old", "target_type": "person", "timestamp": "2025-12-01T10:00:00"})
            vs.add(v, {"thumbnail_id": "new", "target_type": "person", "timestamp": "2026-02-15T10:00:00"})

            results = vs.search(v, k=10, date_to="2026-01-01")
            assert len(results) == 1
            assert results[0][0]["thumbnail_id"] == "old"

    def test_filter_by_date_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "too_old", "target_type": "person", "timestamp": "2025-06-01T10:00:00"})
            vs.add(v, {"thumbnail_id": "in_range", "target_type": "person", "timestamp": "2026-01-15T10:00:00"})
            vs.add(v, {"thumbnail_id": "too_new", "target_type": "person", "timestamp": "2026-06-01T10:00:00"})

            results = vs.search(v, k=10, date_from="2026-01-01", date_to="2026-02-01")
            assert len(results) == 1
            assert results[0][0]["thumbnail_id"] == "in_range"

    def test_combined_type_and_date_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "p_old", "target_type": "person", "timestamp": "2025-06-01T00:00:00"})
            vs.add(v, {"thumbnail_id": "p_new", "target_type": "person", "timestamp": "2026-02-01T00:00:00"})
            vs.add(v, {"thumbnail_id": "c_new", "target_type": "car", "timestamp": "2026-02-01T00:00:00"})

            results = vs.search(v, k=10, target_type="person", date_from="2026-01-01")
            assert len(results) == 1
            assert results[0][0]["thumbnail_id"] == "p_new"

    def test_similarity_score_is_float(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "t1", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search(v, k=1)
            assert len(results) == 1
            meta, score = results[0]
            assert isinstance(score, float)
            # Identical normalized vectors should have similarity ~1.0
            assert abs(score - 1.0) < 1e-5

    def test_missing_timestamp_in_metadata(self):
        """Entries with missing timestamp should still be searchable (date filter skips them)."""
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "no_ts", "target_type": "person"})

            # Without date filters, should be found
            results = vs.search(v, k=10)
            assert len(results) == 1

            # With date_from filter, timestamp="" < "2026-..." so it gets excluded
            results = vs.search(v, k=10, date_from="2026-01-01")
            assert len(results) == 0


# ---------------------------------------------------------------------------
# VectorStore.search_by_thumbnail
# ---------------------------------------------------------------------------

class TestVectorStoreSearchByThumbnail:
    """Search using an existing thumbnail as query."""

    def _make_store(self, tmp: str):
        store_path = Path(tmp) / "store.json"
        from app.ai.embeddings import VectorStore
        return VectorStore(store_path)

    def test_finds_similar_thumbnails(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v1 = _normalized([1.0, 0.0, 0.0])
            v2 = _normalized([0.9, 0.1, 0.0])
            v3 = _normalized([0.0, 1.0, 0.0])

            vs.add(v1, {"thumbnail_id": "query_thumb", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v2, {"thumbnail_id": "similar", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v3, {"thumbnail_id": "different", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search_by_thumbnail("query_thumb", k=2)

            # Should not include the query itself
            ids = [r[0]["thumbnail_id"] for r in results]
            assert "query_thumb" not in ids
            assert "similar" in ids

    def test_excludes_query_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "self", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v, {"thumbnail_id": "other", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search_by_thumbnail("self", k=5)
            ids = [r[0]["thumbnail_id"] for r in results]
            assert "self" not in ids

    def test_nonexistent_thumbnail_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "exists", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search_by_thumbnail("does_not_exist", k=5)
            assert results == []

    def test_passes_filters_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "q", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v, {"thumbnail_id": "p1", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add(v, {"thumbnail_id": "c1", "target_type": "car", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search_by_thumbnail("q", k=10, target_type="car")
            assert len(results) == 1
            assert results[0][0]["target_type"] == "car"

    def test_respects_k_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)

            v = _normalized([1.0, 0.0])
            vs.add(v, {"thumbnail_id": "q", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            for i in range(10):
                vs.add(v, {"thumbnail_id": f"t{i}", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            results = vs.search_by_thumbnail("q", k=3)
            assert len(results) == 3


# ---------------------------------------------------------------------------
# VectorStore.get_all
# ---------------------------------------------------------------------------

class TestVectorStoreGetAll:
    """Metadata retrieval with filtering, sorting, pagination."""

    def _make_store(self, tmp: str):
        store_path = Path(tmp) / "store.json"
        from app.ai.embeddings import VectorStore
        return VectorStore(store_path)

    def test_empty_store_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            assert vs.get_all() == []

    def test_returns_all_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            vs.add([0.1], {"thumbnail_id": "a", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add([0.2], {"thumbnail_id": "b", "target_type": "car", "timestamp": "2026-01-02T00:00:00"})

            results = vs.get_all()
            assert len(results) == 2

    def test_filter_by_target_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            vs.add([0.1], {"thumbnail_id": "p1", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})
            vs.add([0.2], {"thumbnail_id": "c1", "target_type": "car", "timestamp": "2026-01-01T00:00:00"})

            results = vs.get_all(target_type="person")
            assert len(results) == 1
            assert results[0]["target_type"] == "person"

    def test_filter_by_date_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            vs.add([0.1], {"thumbnail_id": "old", "timestamp": "2025-06-01T00:00:00"})
            vs.add([0.2], {"thumbnail_id": "new", "timestamp": "2026-02-01T00:00:00"})

            results = vs.get_all(date_from="2026-01-01")
            assert len(results) == 1
            assert results[0]["thumbnail_id"] == "new"

    def test_filter_by_date_to(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            vs.add([0.1], {"thumbnail_id": "old", "timestamp": "2025-06-01T00:00:00"})
            vs.add([0.2], {"thumbnail_id": "new", "timestamp": "2026-02-01T00:00:00"})

            results = vs.get_all(date_to="2025-12-31")
            assert len(results) == 1
            assert results[0]["thumbnail_id"] == "old"

    def test_sorted_by_timestamp_descending(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            vs.add([0.1], {"thumbnail_id": "mid", "timestamp": "2026-01-15T00:00:00"})
            vs.add([0.2], {"thumbnail_id": "old", "timestamp": "2026-01-01T00:00:00"})
            vs.add([0.3], {"thumbnail_id": "new", "timestamp": "2026-02-01T00:00:00"})

            results = vs.get_all()
            ids = [r["thumbnail_id"] for r in results]
            assert ids == ["new", "mid", "old"]

    def test_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            for i in range(10):
                vs.add([float(i)], {"thumbnail_id": f"t{i}", "timestamp": f"2026-01-{i+1:02d}T00:00:00"})

            results = vs.get_all(limit=3)
            assert len(results) == 3

    def test_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            for i in range(5):
                vs.add([float(i)], {"thumbnail_id": f"t{i}", "timestamp": f"2026-01-{i+1:02d}T00:00:00"})

            all_results = vs.get_all()
            offset_results = vs.get_all(offset=2)
            assert len(offset_results) == 3
            assert offset_results[0] == all_results[2]

    def test_limit_and_offset_combined(self):
        with tempfile.TemporaryDirectory() as tmp:
            vs = self._make_store(tmp)
            for i in range(10):
                vs.add([float(i)], {"thumbnail_id": f"t{i}", "timestamp": f"2026-01-{i+1:02d}T00:00:00"})

            results = vs.get_all(limit=2, offset=3)
            assert len(results) == 2


# ---------------------------------------------------------------------------
# VectorStore.count
# ---------------------------------------------------------------------------

class TestVectorStoreCount:
    """Count property."""

    def test_empty_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)
            assert vs.count == 0

    def test_count_after_adds(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add([0.1], {"id": "a"})
            vs.add([0.2], {"id": "b"})
            assert vs.count == 2

    def test_count_after_batch_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add_batch([[0.1], [0.2], [0.3]], [{"id": "a"}, {"id": "b"}, {"id": "c"}])
            assert vs.count == 3


# ---------------------------------------------------------------------------
# VectorStore.stats
# ---------------------------------------------------------------------------

class TestVectorStoreStats:
    """Statistics about stored embeddings."""

    def test_empty_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            stats = vs.stats()
            assert stats["total"] == 0
            assert stats["by_type"] == {}

    def test_stats_by_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add([0.1], {"target_type": "person"})
            vs.add([0.2], {"target_type": "person"})
            vs.add([0.3], {"target_type": "car"})
            vs.add([0.4], {"target_type": "dog"})

            stats = vs.stats()
            assert stats["total"] == 4
            assert stats["by_type"]["person"] == 2
            assert stats["by_type"]["car"] == 1
            assert stats["by_type"]["dog"] == 1

    def test_stats_unknown_type(self):
        """Entries without target_type are counted as 'unknown'."""
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore
            vs = VectorStore(store_path)

            vs.add([0.1], {"thumbnail_id": "no_type"})

            stats = vs.stats()
            assert stats["by_type"]["unknown"] == 1


# ---------------------------------------------------------------------------
# VectorStore persistence across instances
# ---------------------------------------------------------------------------

class TestVectorStorePersistence:
    """Verify data survives re-instantiation from disk."""

    def test_data_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore

            vs1 = VectorStore(store_path)
            vs1.add([0.1, 0.2], {"thumbnail_id": "persist_test", "target_type": "person"})
            vs1.add_batch([[0.3, 0.4]], [{"thumbnail_id": "batch_test", "target_type": "car"}])

            # Create new instance from same path
            vs2 = VectorStore(store_path)
            assert vs2.count == 2
            assert vs2.data["metadata"][0]["thumbnail_id"] == "persist_test"
            assert vs2.data["metadata"][1]["thumbnail_id"] == "batch_test"

    def test_search_works_after_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            from app.ai.embeddings import VectorStore

            vs1 = VectorStore(store_path)
            v = _normalized([1.0, 0.0])
            vs1.add(v, {"thumbnail_id": "t1", "target_type": "person", "timestamp": "2026-01-01T00:00:00"})

            vs2 = VectorStore(store_path)
            results = vs2.search(v, k=1)
            assert len(results) == 1
            assert results[0][0]["thumbnail_id"] == "t1"


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    """TORCH_AVAILABLE and CLIP_AVAILABLE module-level flags."""

    def test_torch_available_is_bool(self):
        from app.ai.embeddings import TORCH_AVAILABLE
        assert isinstance(TORCH_AVAILABLE, bool)

    def test_clip_available_is_bool(self):
        from app.ai.embeddings import CLIP_AVAILABLE
        assert isinstance(CLIP_AVAILABLE, bool)
