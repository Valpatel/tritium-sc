"""Visual embeddings for similarity search using CLIP."""

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

try:
    import torch
    from PIL import Image
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from transformers import CLIPProcessor, CLIPModel
    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False
    logger.warning("CLIP not available. Run: pip install transformers")


class EmbeddingGenerator:
    """Generates visual embeddings for similarity search."""

    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        device: Optional[str] = None,
    ):
        """Initialize CLIP model for embeddings.

        Args:
            model_name: HuggingFace model name for CLIP
            device: Device to run on ('cuda', 'cpu', or None for auto)
        """
        if not CLIP_AVAILABLE or not TORCH_AVAILABLE:
            raise RuntimeError("CLIP not available. Install: pip install transformers torch")

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        logger.info(f"Loading CLIP model: {model_name}")
        self.model = CLIPModel.from_pretrained(model_name).to(self.device)
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model.eval()

        logger.info(f"CLIP model loaded on {self.device}")

    def embed_image(self, image: np.ndarray) -> list[float]:
        """Generate embedding for a single image.

        Args:
            image: BGR image as numpy array

        Returns:
            Embedding vector as list of floats
        """
        # Convert BGR to RGB
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)

        # Process image
        inputs = self.processor(images=pil_image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Generate embedding
        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
            embedding = outputs.cpu().numpy()[0]

            # Normalize
            embedding = embedding / np.linalg.norm(embedding)

        return embedding.tolist()

    def embed_images_batch(self, images: list[np.ndarray], batch_size: int = 32) -> list[list[float]]:
        """Generate embeddings for multiple images.

        Args:
            images: List of BGR images
            batch_size: Batch size for processing

        Returns:
            List of embedding vectors
        """
        embeddings = []

        for i in range(0, len(images), batch_size):
            batch = images[i:i + batch_size]

            # Convert to PIL images
            pil_images = []
            for img in batch:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                pil_images.append(Image.fromarray(rgb))

            # Process batch
            inputs = self.processor(images=pil_images, return_tensors="pt", padding=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self.model.get_image_features(**inputs)
                batch_embeddings = outputs.cpu().numpy()

                # Normalize each embedding
                for emb in batch_embeddings:
                    emb = emb / np.linalg.norm(emb)
                    embeddings.append(emb.tolist())

        return embeddings

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for text query.

        Args:
            text: Text description to embed

        Returns:
            Embedding vector as list of floats
        """
        inputs = self.processor(text=[text], return_tensors="pt", padding=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model.get_text_features(**inputs)
            embedding = outputs.cpu().numpy()[0]
            embedding = embedding / np.linalg.norm(embedding)

        return embedding.tolist()


class VectorStore:
    """Simple file-based vector store for similarity search."""

    def __init__(self, store_path: Path):
        """Initialize vector store.

        Args:
            store_path: Path to JSON file for storing embeddings
        """
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self):
        """Load existing embeddings from disk."""
        if self.store_path.exists():
            with open(self.store_path) as f:
                self.data = json.load(f)
        else:
            self.data = {"embeddings": [], "metadata": []}

    def _save(self):
        """Save embeddings to disk."""
        with open(self.store_path, "w") as f:
            json.dump(self.data, f)

    def add(self, embedding: list[float], metadata: dict):
        """Add an embedding with metadata.

        Args:
            embedding: Vector to store
            metadata: Associated metadata (thumbnail_id, type, timestamp, etc.)
        """
        self.data["embeddings"].append(embedding)
        self.data["metadata"].append(metadata)
        self._save()

    def add_batch(self, embeddings: list[list[float]], metadatas: list[dict]):
        """Add multiple embeddings.

        Args:
            embeddings: List of vectors
            metadatas: List of metadata dicts
        """
        self.data["embeddings"].extend(embeddings)
        self.data["metadata"].extend(metadatas)
        self._save()

    def search(
        self,
        query_embedding: list[float],
        k: int = 10,
        target_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[tuple[dict, float]]:
        """Search for similar embeddings.

        Args:
            query_embedding: Query vector
            k: Number of results to return
            target_type: Filter by type ("person", "vehicle", etc.)
            date_from: Filter by start date (YYYY-MM-DD)
            date_to: Filter by end date (YYYY-MM-DD)

        Returns:
            List of (metadata, similarity_score) tuples
        """
        if not self.data["embeddings"]:
            return []

        query = np.array(query_embedding)
        embeddings = np.array(self.data["embeddings"])

        # Calculate cosine similarity (embeddings are normalized)
        similarities = np.dot(embeddings, query)

        # Get indices sorted by similarity
        indices = np.argsort(similarities)[::-1]

        results = []
        for idx in indices:
            meta = self.data["metadata"][idx]

            # Apply filters
            if target_type and meta.get("target_type") != target_type:
                continue

            if date_from:
                ts = meta.get("timestamp", "")[:10]
                if ts < date_from:
                    continue

            if date_to:
                ts = meta.get("timestamp", "")[:10]
                if ts > date_to:
                    continue

            results.append((meta, float(similarities[idx])))

            if len(results) >= k:
                break

        return results

    def search_by_thumbnail(
        self,
        thumbnail_id: str,
        k: int = 10,
        **filters,
    ) -> list[tuple[dict, float]]:
        """Find similar objects to a given thumbnail.

        Args:
            thumbnail_id: ID of reference thumbnail
            k: Number of results
            **filters: Additional filters

        Returns:
            List of (metadata, similarity_score) tuples
        """
        # Find the thumbnail's embedding
        for i, meta in enumerate(self.data["metadata"]):
            if meta.get("thumbnail_id") == thumbnail_id:
                query_embedding = self.data["embeddings"][i]
                results = self.search(query_embedding, k + 1, **filters)
                # Remove the query itself from results
                return [(m, s) for m, s in results if m.get("thumbnail_id") != thumbnail_id][:k]

        return []

    def get_all(
        self,
        target_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Get all thumbnails with optional filters.

        Args:
            target_type: Filter by type
            date_from: Start date filter
            date_to: End date filter
            limit: Max results
            offset: Skip first N results

        Returns:
            List of metadata dicts
        """
        results = []

        for meta in self.data["metadata"]:
            if target_type and meta.get("target_type") != target_type:
                continue

            if date_from:
                ts = meta.get("timestamp", "")[:10]
                if ts < date_from:
                    continue

            if date_to:
                ts = meta.get("timestamp", "")[:10]
                if ts > date_to:
                    continue

            results.append(meta)

        # Sort by timestamp descending (most recent first)
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return results[offset:offset + limit]

    @property
    def count(self) -> int:
        """Total number of stored embeddings."""
        return len(self.data["embeddings"])

    def stats(self) -> dict:
        """Get statistics about stored embeddings."""
        type_counts = {}
        for meta in self.data["metadata"]:
            obj_type = meta.get("target_type", "unknown")
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

        return {
            "total": self.count,
            "by_type": type_counts,
        }
