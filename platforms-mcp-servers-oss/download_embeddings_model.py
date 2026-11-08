"""
Download the embeddings model and save it locally under embeddings_assets/model.
"""

from pathlib import Path
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent / "embeddings_assets"
MODEL_DIR = BASE_DIR / "model" / "all-MiniLM-L6-v2"

MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)

print(f"Downloading/loading model into: {MODEL_DIR}")
model = SentenceTransformer("all-MiniLM-L6-v2")
model.save(str(MODEL_DIR))
print("Model saved locally.")