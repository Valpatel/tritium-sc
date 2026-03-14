# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DashboardLayoutManager — save/load panel layouts per user/mission.

Stores named dashboard configurations containing panel visibility,
positions, sizes, and ordering. Users can switch between layouts
(e.g. "Surveillance", "Battle", "Analysis") and share them.

Usage
-----
    layouts = DashboardLayoutManager()
    layouts.save("patrol", user="operator1", panels=[...])
    config = layouts.load("patrol", user="operator1")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PanelConfig:
    """Configuration for a single dashboard panel."""

    panel_id: str
    visible: bool = True
    position: dict = field(default_factory=lambda: {"x": 0, "y": 0})
    size: dict = field(default_factory=lambda: {"width": 400, "height": 300})
    order: int = 0
    collapsed: bool = False
    settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "panel_id": self.panel_id,
            "visible": self.visible,
            "position": self.position,
            "size": self.size,
            "order": self.order,
            "collapsed": self.collapsed,
            "settings": self.settings,
        }


@dataclass
class DashboardLayout:
    """A named dashboard layout configuration."""

    name: str
    user: str = "default"
    description: str = ""
    panels: list[PanelConfig] = field(default_factory=list)
    map_settings: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "user": self.user,
            "description": self.description,
            "panels": [p.to_dict() for p in self.panels],
            "map_settings": self.map_settings,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "panel_count": len(self.panels),
        }


# Default layouts for quick start
DEFAULT_LAYOUTS = {
    "surveillance": {
        "description": "Full situational awareness — all panels visible",
        "panels": [
            {"panel_id": "map", "visible": True, "order": 0},
            {"panel_id": "targets", "visible": True, "order": 1},
            {"panel_id": "alerts", "visible": True, "order": 2},
            {"panel_id": "cameras", "visible": True, "order": 3},
            {"panel_id": "dossiers", "visible": True, "order": 4},
            {"panel_id": "timeline", "visible": True, "order": 5},
        ],
    },
    "battle": {
        "description": "Combat focus — map, targets, and Amy",
        "panels": [
            {"panel_id": "map", "visible": True, "order": 0},
            {"panel_id": "targets", "visible": True, "order": 1},
            {"panel_id": "amy", "visible": True, "order": 2},
            {"panel_id": "alerts", "visible": True, "order": 3},
        ],
    },
    "analysis": {
        "description": "Intelligence analysis — heatmaps, graphs, dossiers",
        "panels": [
            {"panel_id": "map", "visible": True, "order": 0},
            {"panel_id": "heatmap", "visible": True, "order": 1},
            {"panel_id": "network_graph", "visible": True, "order": 2},
            {"panel_id": "dossiers", "visible": True, "order": 3},
            {"panel_id": "statistics", "visible": True, "order": 4},
        ],
    },
    "minimal": {
        "description": "Minimal — map and targets only",
        "panels": [
            {"panel_id": "map", "visible": True, "order": 0},
            {"panel_id": "targets", "visible": True, "order": 1},
        ],
    },
}


class DashboardLayoutManager:
    """Manages named dashboard layouts with persistence.

    Thread-safe. Stores layouts in memory with optional file persistence.

    Parameters
    ----------
    storage_path:
        Optional path to a JSON file for persistent storage.
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        # Key: (user, name) -> DashboardLayout
        self._layouts: dict[tuple[str, str], DashboardLayout] = {}
        self._storage_path = Path(storage_path) if storage_path else None

        # Load defaults
        self._load_defaults()

        # Load from file if exists
        if self._storage_path and self._storage_path.exists():
            self._load_from_file()

    def save(
        self,
        name: str,
        user: str = "default",
        description: str = "",
        panels: list[dict] | None = None,
        map_settings: dict | None = None,
    ) -> dict:
        """Save a dashboard layout.

        Args:
            name:         Layout name (e.g. "patrol", "battle").
            user:         User who owns this layout.
            description:  Human-readable description.
            panels:       List of panel config dicts.
            map_settings: Map view settings (zoom, center, layers).

        Returns:
            The saved layout as a dict.
        """
        panel_configs = []
        if panels:
            for p in panels:
                panel_configs.append(PanelConfig(
                    panel_id=p.get("panel_id", "unknown"),
                    visible=p.get("visible", True),
                    position=p.get("position", {"x": 0, "y": 0}),
                    size=p.get("size", {"width": 400, "height": 300}),
                    order=p.get("order", 0),
                    collapsed=p.get("collapsed", False),
                    settings=p.get("settings", {}),
                ))

        layout = DashboardLayout(
            name=name,
            user=user,
            description=description,
            panels=panel_configs,
            map_settings=map_settings or {},
        )

        with self._lock:
            existing = self._layouts.get((user, name))
            if existing:
                layout.created_at = existing.created_at
            layout.updated_at = time.time()
            self._layouts[(user, name)] = layout

        self._persist()
        return layout.to_dict()

    def load(self, name: str, user: str = "default") -> dict | None:
        """Load a named layout.

        Returns the layout dict or None if not found.
        """
        with self._lock:
            layout = self._layouts.get((user, name))
            if layout is None:
                # Try default user
                layout = self._layouts.get(("default", name))
            if layout is None:
                return None
            return layout.to_dict()

    def list_layouts(self, user: str | None = None) -> list[dict]:
        """List all available layouts, optionally filtered by user.

        Always includes default layouts.
        """
        with self._lock:
            results = []
            seen = set()
            for (u, name), layout in self._layouts.items():
                if user is not None and u != user and u != "default":
                    continue
                if name not in seen:
                    results.append({
                        "name": name,
                        "user": u,
                        "description": layout.description,
                        "panel_count": len(layout.panels),
                        "updated_at": layout.updated_at,
                    })
                    seen.add(name)
        results.sort(key=lambda r: r["name"])
        return results

    def delete(self, name: str, user: str = "default") -> bool:
        """Delete a layout. Returns True if it existed."""
        with self._lock:
            removed = self._layouts.pop((user, name), None)
        if removed:
            self._persist()
        return removed is not None

    def duplicate(
        self, source_name: str, new_name: str, user: str = "default"
    ) -> dict | None:
        """Duplicate an existing layout under a new name."""
        source = self.load(source_name, user)
        if source is None:
            return None
        return self.save(
            name=new_name,
            user=user,
            description=f"Copy of {source_name}",
            panels=source.get("panels", []),
            map_settings=source.get("map_settings", {}),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_defaults(self) -> None:
        """Load default layout presets."""
        for name, config in DEFAULT_LAYOUTS.items():
            panels = [
                PanelConfig(
                    panel_id=p["panel_id"],
                    visible=p.get("visible", True),
                    order=p.get("order", 0),
                )
                for p in config["panels"]
            ]
            self._layouts[("default", name)] = DashboardLayout(
                name=name,
                user="default",
                description=config["description"],
                panels=panels,
            )

    def _persist(self) -> None:
        """Save all layouts to disk if storage_path is set."""
        if self._storage_path is None:
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    f"{u}:{n}": layout.to_dict()
                    for (u, n), layout in self._layouts.items()
                }
            self._storage_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Failed to persist dashboard layouts: %s", e)

    def _load_from_file(self) -> None:
        """Load layouts from disk."""
        try:
            data = json.loads(self._storage_path.read_text())
            for key, layout_data in data.items():
                user, name = key.split(":", 1) if ":" in key else ("default", key)
                panels = [
                    PanelConfig(**p) if isinstance(p, dict) else p
                    for p in layout_data.get("panels", [])
                ]
                self._layouts[(user, name)] = DashboardLayout(
                    name=name,
                    user=user,
                    description=layout_data.get("description", ""),
                    panels=panels,
                    map_settings=layout_data.get("map_settings", {}),
                    created_at=layout_data.get("created_at", time.time()),
                    updated_at=layout_data.get("updated_at", time.time()),
                )
        except Exception as e:
            logger.warning("Failed to load dashboard layouts: %s", e)
