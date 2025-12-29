from pathlib import Path
import json
from typing import List, Tuple

import torch
import faiss
import numpy as np
from PIL import Image
import clip

import sys

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

MODEL = None
PREPROCESS = None
CURRENT_MODEL_NAME = None
INDEX = None
NAMES: List[str] = []

def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def load_resources(db_dir: Path):
    global MODEL, PREPROCESS, INDEX, NAMES, CURRENT_MODEL_NAME
    
    index_path = db_dir / "stickers.faiss"
    with open(index_path, "rb") as f:
        INDEX = faiss.deserialize_index(np.frombuffer(f.read(), dtype=np.uint8))

    # 根据索引维度自动选择模型
    dim = INDEX.d
    if dim == 768:
        model_name = "ViT-L/14"
    elif dim == 512:
        model_name = "ViT-B/32"
    else:
        # 默认回退
        model_name = "ViT-B/32"
        print(f"Warning: Unknown index dimension {dim}, defaulting to ViT-B/32")

    if MODEL is None or PREPROCESS is None or CURRENT_MODEL_NAME != model_name:
        print(f"[search] Loading model {model_name} on {DEVICE} (Index dim: {dim})...")
        model_dir = get_project_root() / "models"
        import os
        os.makedirs(model_dir, exist_ok=True)
        MODEL, PREPROCESS = clip.load(model_name, device=DEVICE, download_root=str(model_dir))
        MODEL.eval()
        CURRENT_MODEL_NAME = model_name

    names_path = db_dir / "stickers.json"
    with open(names_path, "r", encoding="utf-8") as f:
        NAMES = json.load(f)

def encode_image(img: Image.Image):
    x = PREPROCESS(img.convert("RGB")).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        feats = MODEL.encode_image(x)
    feats = feats / feats.norm(dim=1, keepdim=True)
    return feats.cpu().numpy().astype("float32")

def switch_database(db_dir: Path):
    """安全切换到新数据库，重新加载索引和名称"""
    global INDEX, NAMES
    INDEX = None
    NAMES = []
    load_resources(db_dir)


def find_sticker(image_path: str, db_dir: Path, topk: int = 5) -> List[Tuple[str, float]]:
    if INDEX is None or not NAMES:
        load_resources(db_dir)
    img = Image.open(image_path)
    feats = encode_image(img)
    k = min(topk, len(NAMES))
    distances, indices = INDEX.search(feats, k)
    results = [(NAMES[idx], 1.0/(1.0+float(d))) for d, idx in zip(distances[0], indices[0])]
    results.sort(key=lambda x: x[1], reverse=True)
    return results
