#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CLI tool for generating synthetic audio effects.

Usage:
    python scripts/gen_synthetic_audio.py --all              # Generate everything
    python scripts/gen_synthetic_audio.py --category combat   # Just combat sounds
    python scripts/gen_synthetic_audio.py --effect nerf_shot  # Single effect
    python scripts/gen_synthetic_audio.py --list             # Show library
    python scripts/gen_synthetic_audio.py --play nerf_shot   # Generate and play (if aplay available)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

# Ensure project root is on sys.path
_project_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from engine.audio.audio_library import AudioLibrary, _EFFECT_CATALOG


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def cmd_list(lib: AudioLibrary) -> None:
    """List all available effects."""
    print("\n  TRITIUM-SC SYNTHETIC AUDIO LIBRARY")
    print("  " + "=" * 50)

    categories = lib.categories()
    for cat in categories:
        effects = lib.effects_in_category(cat)
        print(f"\n  [{cat.upper()}]")
        for name in effects:
            _, _, duration, _ = _EFFECT_CATALOG[name]
            path = lib._effect_path(name)
            if path.exists():
                size = _format_size(path.stat().st_size)
                status = f"  [{size}]"
            else:
                status = "  [not generated]"
            print(f"    {name:<35} {duration:>5.2f}s{status}")

    total = len(_EFFECT_CATALOG)
    generated = sum(1 for name in _EFFECT_CATALOG if lib._effect_path(name).exists())
    print(f"\n  {generated}/{total} effects generated")
    print(f"  Library path: {lib.library_path}")
    print()


def cmd_generate_all(lib: AudioLibrary) -> None:
    """Generate all effects."""
    print("\n  Generating all sound effects...")
    t0 = time.time()
    result = lib.generate_all()
    elapsed = time.time() - t0

    total_size = 0
    for name, path in sorted(result.items()):
        size = path.stat().st_size
        total_size += size
        print(f"    {name:<35} -> {_format_size(size)}")

    print(f"\n  {len(result)} effects generated in {elapsed:.2f}s")
    print(f"  Total size: {_format_size(total_size)}")
    print(f"  Library path: {lib.library_path}")
    print()


def cmd_generate_category(lib: AudioLibrary, category: str) -> None:
    """Generate effects in a specific category."""
    effects = lib.effects_in_category(category)
    if not effects:
        print(f"  Unknown category: {category}")
        print(f"  Available: {', '.join(lib.categories())}")
        sys.exit(1)

    print(f"\n  Generating [{category.upper()}] effects...")
    for name in effects:
        path = lib.get_effect(name)
        size = _format_size(path.stat().st_size)
        print(f"    {name:<35} -> {size}")
    print(f"\n  {len(effects)} effects generated")
    print()


def cmd_generate_effect(lib: AudioLibrary, effect_name: str) -> None:
    """Generate a single effect."""
    if effect_name not in _EFFECT_CATALOG:
        print(f"  Unknown effect: {effect_name}")
        print(f"  Available: {', '.join(sorted(_EFFECT_CATALOG.keys()))}")
        sys.exit(1)

    path = lib.get_effect(effect_name)
    size = _format_size(path.stat().st_size)
    print(f"  Generated: {effect_name} -> {path} ({size})")


def cmd_play(lib: AudioLibrary, effect_name: str) -> None:
    """Generate and play an effect."""
    if effect_name not in _EFFECT_CATALOG:
        print(f"  Unknown effect: {effect_name}")
        sys.exit(1)

    path = lib.get_effect(effect_name)
    print(f"  Playing: {effect_name} ({path})")

    # Try aplay (ALSA), then paplay (PulseAudio), then ffplay
    for player in ["aplay", "paplay", "ffplay"]:
        if shutil.which(player):
            try:
                args = [player, str(path)]
                if player == "ffplay":
                    args = [player, "-nodisp", "-autoexit", str(path)]
                subprocess.run(args, check=True, timeout=15)
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue

    print("  No audio player found (tried: aplay, paplay, ffplay)")
    print(f"  WAV file available at: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TRITIUM-SC Synthetic Audio Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/gen_synthetic_audio.py --all
    python scripts/gen_synthetic_audio.py --category combat
    python scripts/gen_synthetic_audio.py --effect nerf_shot
    python scripts/gen_synthetic_audio.py --list
    python scripts/gen_synthetic_audio.py --play nerf_shot
        """,
    )

    parser.add_argument("--all", action="store_true",
                        help="Generate all sound effects")
    parser.add_argument("--category", type=str,
                        help="Generate effects in category (combat/ambient/alerts/game)")
    parser.add_argument("--effect", type=str,
                        help="Generate a single named effect")
    parser.add_argument("--list", action="store_true",
                        help="List all available effects")
    parser.add_argument("--play", type=str,
                        help="Generate and play a named effect")
    parser.add_argument("--output", type=str, default="data/synthetic/audio",
                        help="Library output path (default: data/synthetic/audio)")

    args = parser.parse_args()

    lib = AudioLibrary(library_path=args.output)

    if args.list:
        cmd_list(lib)
    elif args.all:
        cmd_generate_all(lib)
    elif args.category:
        cmd_generate_category(lib, args.category)
    elif args.effect:
        cmd_generate_effect(lib, args.effect)
    elif args.play:
        cmd_play(lib, args.play)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
