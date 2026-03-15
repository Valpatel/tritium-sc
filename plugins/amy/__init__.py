# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Amy Commander plugin — wraps the existing src/amy/ AI commander
as a plugin in the plugin system."""

from .plugin import AmyCommanderPlugin

__all__ = ["AmyCommanderPlugin"]
