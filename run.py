#!/usr/bin/env python3
"""TRITIUM - Security Camera Intelligence Platform

Run script for development and production.
"""

import argparse
import os
import sys
from pathlib import Path

# Add src/ to PYTHONPATH for app/amy imports
_src = str(Path(__file__).parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import uvicorn
from loguru import logger

# Configure loguru
logger.remove()
logger.add(
    sys.stderr,
    format="<cyan>{time:HH:mm:ss}</cyan> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
)


def main():
    parser = argparse.ArgumentParser(
        description="TRITIUM - Security Camera Intelligence Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                     # Run with defaults
  python run.py --port 8080         # Custom port
  python run.py --reload            # Development mode with auto-reload
  python run.py --workers 4         # Production mode with 4 workers
        """,
    )

    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level (default: info)",
    )

    args = parser.parse_args()

    # Banner
    print("\n" + "=" * 60)
    print("  ███████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗     ")
    print("  ██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║     ")
    print("  ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║     ")
    print("  ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║     ")
    print("  ███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗")
    print("  ╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝")
    print("=" * 60)
    print("  Security Camera Intelligence Platform v0.1.0")
    print("=" * 60 + "\n")

    logger.info(f"Starting TRITIUM on http://{args.host}:{args.port}")
    logger.info(f"Log level: {args.log_level.upper()}")

    if args.reload:
        logger.info("Development mode: auto-reload enabled")
    elif args.workers > 1:
        logger.info(f"Production mode: {args.workers} workers")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1 if args.reload else args.workers,
        log_level=args.log_level,
        access_log=True,
    )


if __name__ == "__main__":
    main()
