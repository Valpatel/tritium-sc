"""CoT type data registry -- curated subset of MIL-STD-2525 type codes."""

from .registry import all_codes, describe, lookup, reverse_lookup, swap_affiliation

__all__ = [
    "lookup",
    "swap_affiliation",
    "describe",
    "reverse_lookup",
    "all_codes",
]
