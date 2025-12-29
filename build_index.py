import os
import json
import time
import shutil
from pathlib import Path
from typing import List

import sys
import torch
import faiss
from PIL import Image
import clip
from tqdm import tqdm  # 命令行进度条

BATCH_SIZE = 32

def list_images(sticker_dir: Path) -> List[Path]:
    exts = {".png", ".jpg", ".jpeg"}
    files = [Path(root)/fn for root, _, fns in os.walk(sticker_dir)
             for fn in fns if Path(fn).suffix.lower() in exts]
    files.sort()
    return files

def build_index_gui(sticker_dir: Path, db_name: str, device=None):
    """
    建库函数，可选择 device: "cuda" 或 "cpu"
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model_name = "ViT-L/14" if device=="cuda" else "ViT-B/32"

    print(f"[build_index] Using device: {device}, model: {model_name}")

    start = time.time()
    if getattr(sys, "frozen", False):
        project_root = Path(sys.executable).resolve().parent
    else:
        project_root = Path(__file__).resolve().parent
    db_dir = project_root / "databases" / db_name
    db_sticker_dir = db_dir / "stickers"
    os.makedirs(db_sticker_dir, exist_ok=True)

    for item in sticker_dir.iterdir():
        if item.is_file() and item.suffix.lower() in {".png",".jpg",".jpeg"}:
            shutil.copy2(item, db_sticker_dir)

    index_path = db_dir / "stickers.faiss"
    names_path = db_dir / "stickers.json"

    torch.set_grad_enabled(False)
    
    model_dir = project_root / "models"
    os.makedirs(model_dir, exist_ok=True)
    model, preprocess = clip.load(model_name, device=device, download_root=str(model_dir))
    model.eval()

    files = list_images(db_sticker_dir)
    if not files:
        raise RuntimeError(f"No images found in {db_sticker_dir}.")

    names = [str(f.relative_to(db_sticker_dir)) for f in files]

    features_list = []

    print(f"Building index for {len(files)} images on {device} using {model_name}...")
    for i in tqdm(range(0, len(files), BATCH_SIZE), desc="Processing batches"):
        batch_files = files[i:i+BATCH_SIZE]
        images = [preprocess(Image.open(fp).convert("RGB")) for fp in batch_files]
        image_tensor = torch.stack(images).to(device)
        with torch.no_grad():
            feats = model.encode_image(image_tensor)
        feats = feats / feats.norm(dim=1, keepdim=True)
        features_list.append(feats.cpu())

    features = torch.cat(features_list, dim=0).numpy().astype("float32")
    dim = features.shape[1]

    index = faiss.IndexFlatL2(dim)
    index.add(features)

    # 序列化保存
    with open(index_path, "wb") as f:
        f.write(faiss.serialize_index(index))
    with open(names_path, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=2)

    print(f"Indexed {len(files)} stickers @ dim={dim}")
    print(f"Database saved to {db_dir}")
    print(f"Build time: {time.time()-start:.2f}s")
    return db_dir
