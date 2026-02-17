"""Pre-generate high-quality images for scenario visualization.

Uses Stable Diffusion on CPU to generate realistic room backgrounds
and person sprites, then stores them in amy/scenarios/cache/ for
use by FrameGenerator during scenario runs.

Usage:
    .venv/bin/python3 -m amy.scenarios.pregen [--steps N] [--model MODEL]

Generated images:
    cache/backgrounds/room_00.jpg ... room_03.jpg   (CCTV-style room images)
    cache/people/person_00.png   ... person_04.png  (RGBA person sprites)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

CACHE_DIR = Path(__file__).parent / "cache"
BG_DIR = CACHE_DIR / "backgrounds"
PEOPLE_DIR = CACHE_DIR / "people"

# --- Prompts ---------------------------------------------------------------

BACKGROUND_PROMPTS = [
    (
        "security camera CCTV footage of an empty dark office room at night, "
        "wall mounted camera angle, dim overhead fluorescent lighting, "
        "desk and chair visible, realistic grainy low resolution, "
        "no people, surveillance footage"
    ),
    (
        "security camera CCTV footage of an empty hallway corridor, "
        "wall mounted camera looking down hallway, dim lighting, "
        "industrial carpet floor, realistic grainy, surveillance camera, "
        "no people, nighttime"
    ),
    (
        "security camera view of empty warehouse room, "
        "overhead mounted CCTV camera, concrete floor, "
        "dim single light, shadows, realistic surveillance footage, "
        "no people, grainy low quality"
    ),
    (
        "security camera CCTV footage of an empty break room, "
        "wall mounted camera angle, dim lighting, "
        "table and vending machine visible, realistic grainy, "
        "no people, surveillance footage, nighttime"
    ),
    (
        "security camera CCTV footage of an empty server room, "
        "wall mounted camera high angle, blinking rack LEDs, "
        "cable trays overhead, cold lighting, realistic grainy, "
        "no people, surveillance footage"
    ),
    (
        "security camera CCTV footage of an empty reception lobby, "
        "wall mounted camera angle, glass doors visible, "
        "front desk and waiting chairs, dim after hours lighting, "
        "no people, surveillance footage, nighttime"
    ),
]

PERSON_PROMPTS = [
    (
        "full body photograph of a young man standing upright facing camera, "
        "casual clothes jeans and t-shirt, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
    (
        "full body photograph of a woman standing facing camera, "
        "business casual outfit, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
    (
        "full body photograph of a man in dark hoodie and jeans "
        "standing facing camera, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
    (
        "full body photograph of an older man standing facing camera, "
        "work clothes and boots, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
    (
        "full body photograph of a young woman standing facing camera, "
        "athletic wear, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
    (
        "full body photograph of a woman in lab coat standing facing camera, "
        "professional attire, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
    (
        "full body photograph of a tall man in security uniform standing "
        "facing camera, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
    (
        "full body photograph of a young person in casual streetwear "
        "standing facing camera, backpack, solid bright green background, "
        "studio lighting, sharp focus, full body from head to feet"
    ),
]

NEGATIVE_PROMPT = (
    "cartoon, anime, drawing, painting, sketch, illustration, "
    "blurry, deformed, disfigured, bad anatomy, extra limbs, "
    "text, watermark, signature, low quality"
)


def _load_pipeline(model: str):
    """Load Stable Diffusion pipeline on CPU."""
    import torch
    from diffusers import StableDiffusionPipeline

    print(f"Loading model: {model}")
    print("  (first run downloads ~4GB, subsequent runs use cache)")

    pipe = StableDiffusionPipeline.from_pretrained(
        model,
        torch_dtype=torch.float32,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe = pipe.to("cpu")

    # Optimize for CPU
    pipe.enable_attention_slicing()

    return pipe


def _generate_backgrounds(pipe, steps: int) -> None:
    """Generate CCTV-style room backgrounds."""
    BG_DIR.mkdir(parents=True, exist_ok=True)

    for i, prompt in enumerate(BACKGROUND_PROMPTS):
        out_path = BG_DIR / f"room_{i:02d}.jpg"
        if out_path.exists():
            print(f"  [skip] background {i} already exists: {out_path.name}")
            continue

        print(f"  Generating background {i + 1}/{len(BACKGROUND_PROMPTS)} "
              f"({steps} steps)...")
        t0 = time.time()
        result = pipe(
            prompt,
            negative_prompt=NEGATIVE_PROMPT,
            num_inference_steps=steps,
            guidance_scale=7.5,
            width=640,
            height=480,
        )
        img = result.images[0]
        img.save(out_path, quality=90)
        dt = time.time() - t0
        print(f"    Saved {out_path.name} ({dt:.1f}s)")


def _generate_people(pipe, steps: int) -> None:
    """Generate person images and remove background to create RGBA sprites."""
    PEOPLE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from rembg import remove as rembg_remove
        has_rembg = True
    except ImportError:
        print("  WARNING: rembg not installed, using green-screen removal")
        has_rembg = False

    for i, prompt in enumerate(PERSON_PROMPTS):
        out_path = PEOPLE_DIR / f"person_{i:02d}.png"
        if out_path.exists():
            print(f"  [skip] person {i} already exists: {out_path.name}")
            continue

        print(f"  Generating person {i + 1}/{len(PERSON_PROMPTS)} "
              f"({steps} steps)...")
        t0 = time.time()
        result = pipe(
            prompt,
            negative_prompt=NEGATIVE_PROMPT,
            num_inference_steps=steps,
            guidance_scale=7.5,
            width=512,
            height=768,
        )
        img = result.images[0]

        # Remove background
        if has_rembg:
            print("    Removing background with rembg...")
            img_rgba = rembg_remove(img)
        else:
            img_rgba = _greenscreen_remove(img)

        img_rgba.save(out_path)
        dt = time.time() - t0
        print(f"    Saved {out_path.name} ({dt:.1f}s)")


def _greenscreen_remove(img: Image.Image) -> Image.Image:
    """Fallback green-screen removal using HSV thresholding."""
    arr = np.array(img)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)

    # Green range in HSV
    lower_green = np.array([35, 40, 40])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # Invert: person = white, background = black
    mask = cv2.bitwise_not(mask)

    # Clean up edges
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    # Slight feathering for smooth edges
    mask = cv2.GaussianBlur(mask, (3, 3), 0)

    # Create RGBA
    rgba = np.dstack([arr, mask])
    return Image.fromarray(rgba)


def generate(model: str = "runwayml/stable-diffusion-v1-5", steps: int = 20) -> None:
    """Run full pre-generation pipeline."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    pipe = _load_pipeline(model)

    print("\n--- Generating backgrounds ---")
    _generate_backgrounds(pipe, steps)

    print("\n--- Generating people ---")
    _generate_people(pipe, steps)

    # Count results
    n_bg = len(list(BG_DIR.glob("*.jpg"))) if BG_DIR.exists() else 0
    n_ppl = len(list(PEOPLE_DIR.glob("*.png"))) if PEOPLE_DIR.exists() else 0
    print(f"\nDone! {n_bg} backgrounds + {n_ppl} people in {CACHE_DIR}")


def main():
    parser = argparse.ArgumentParser(
        description="Pre-generate scenario images with Stable Diffusion"
    )
    parser.add_argument(
        "--model",
        default="runwayml/stable-diffusion-v1-5",
        help="HuggingFace model ID (default: runwayml/stable-diffusion-v1-5)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=20,
        help="Inference steps per image (default: 20, more = higher quality)",
    )
    args = parser.parse_args()
    generate(model=args.model, steps=args.steps)


if __name__ == "__main__":
    main()
