# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BackupManager — export and import full Tritium-SC system state.

Handles:
- SQLite databases (tritium.db, dossiers.db)
- KuzuDB graph data (if available)
- Configuration (automation rules, geofence zones, patrol routes, threat indicators)
- Amy's memory and transcripts
- Plugin state files
- Scheduled periodic auto-backups
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


# Manifest version for backup format compatibility
MANIFEST_VERSION = "2.0"


class BackupManager:
    """Manages creation, listing, and restoration of system state backups.

    Parameters
    ----------
    data_dir : Path
        Root data directory (typically ``data/``).
    backup_dir : Path
        Directory where backup archives are stored (typically ``data/backups/``).
    db_path : Path
        Path to the primary SQLite database (tritium.db).
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        backup_dir: Path | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.data_dir = Path(data_dir or "data")
        self.backup_dir = Path(backup_dir or self.data_dir / "backups")
        self.db_path = Path(db_path or "tritium.db")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Scheduler state
        self._scheduler_thread: threading.Thread | None = None
        self._scheduler_stop = threading.Event()
        self._scheduler_interval_hours: float = 0

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_state(self, label: str | None = None) -> Path:
        """Create a ZIP archive of the full system state.

        Parameters
        ----------
        label : str, optional
            Human-readable label embedded in the filename and manifest.

        Returns
        -------
        Path
            Path to the created backup archive.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_label = ""
        if label:
            safe_label = "_" + "".join(
                c if c.isalnum() or c in "-_" else "_" for c in label
            )
        filename = f"tritium_backup_{timestamp}{safe_label}.zip"
        archive_path = self.backup_dir / filename

        manifest: dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tritium_version": "0.1.0",
            "label": label or "",
            "contents": {},
        }

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # -- Primary database --
            self._backup_sqlite(zf, self.db_path, "databases/tritium.db", manifest)

            # -- Dossiers database --
            dossier_db = self.data_dir / "dossiers.db"
            self._backup_sqlite(zf, dossier_db, "databases/dossiers.db", manifest)

            # -- KuzuDB graph directory --
            kuzu_dir = self.data_dir / "kuzu"
            if kuzu_dir.is_dir():
                count = self._backup_directory(zf, kuzu_dir, "graph/kuzu")
                manifest["contents"]["kuzu_graph"] = {
                    "path": "graph/kuzu",
                    "file_count": count,
                }

            # -- Amy memory --
            amy_mem = self.data_dir / "amy" / "memory.json"
            if amy_mem.exists():
                zf.write(str(amy_mem), "amy/memory.json")
                manifest["contents"]["amy_memory"] = {
                    "file": "amy/memory.json",
                    "size_bytes": amy_mem.stat().st_size,
                }

            # -- Amy transcripts --
            transcripts_dir = self.data_dir / "amy" / "transcripts"
            if transcripts_dir.is_dir():
                count = self._backup_directory(zf, transcripts_dir, "amy/transcripts")
                manifest["contents"]["amy_transcripts"] = {
                    "path": "amy/transcripts",
                    "file_count": count,
                }

            # -- Plugin state files --
            plugin_state = self._collect_plugin_state()
            if plugin_state:
                for rel_path, abs_path in plugin_state:
                    zf.write(str(abs_path), f"plugins/{rel_path}")
                manifest["contents"]["plugin_state"] = {
                    "path": "plugins/",
                    "file_count": len(plugin_state),
                }

            # -- Configuration exports (JSON snapshots) --
            config_data = self._collect_configuration()
            if config_data:
                config_json = json.dumps(config_data, indent=2, default=str)
                zf.writestr("config/state.json", config_json)
                manifest["contents"]["configuration"] = {
                    "file": "config/state.json",
                    "sections": list(config_data.keys()),
                }

            # -- Backstories --
            backstories = self.data_dir / "backstories"
            if backstories.is_dir():
                count = self._backup_directory(zf, backstories, "backstories")
                manifest["contents"]["backstories"] = {
                    "path": "backstories/",
                    "file_count": count,
                }

            # Write manifest last (so it includes all content info)
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        size_mb = archive_path.stat().st_size / (1024 * 1024)
        logger.info(f"Backup created: {filename} ({size_mb:.1f} MB)")
        return archive_path

    # ------------------------------------------------------------------
    # Import / Restore
    # ------------------------------------------------------------------

    def import_state(self, zip_path: Path) -> dict[str, Any]:
        """Restore system state from a backup archive.

        Parameters
        ----------
        zip_path : Path
            Path to the backup ZIP archive.

        Returns
        -------
        dict
            Restoration report with counts and status.

        Raises
        ------
        ValueError
            If the archive is invalid or has an unsupported version.
        """
        if not zip_path.exists():
            raise ValueError(f"Backup file not found: {zip_path}")

        report: dict[str, Any] = {"restored": [], "skipped": [], "errors": []}

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())

            # Defense in depth: validate no path traversal in ZIP entries
            for name in names:
                if name.startswith("/") or ".." in name.split("/"):
                    raise ValueError(f"Unsafe path in backup archive: {name}")

            # Validate manifest
            if "manifest.json" not in names:
                raise ValueError("Invalid backup: missing manifest.json")

            manifest = json.loads(zf.read("manifest.json"))
            version = manifest.get("version", "")
            if version not in ("1.0", "2.0"):
                raise ValueError(f"Unsupported backup version: {version}")

            report["manifest"] = manifest

            # -- Pre-restore safety: back up current state --
            pre_restore_dir = self.backup_dir / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            pre_restore_dir.mkdir(parents=True, exist_ok=True)

            # -- Restore databases --
            self._restore_database(zf, names, "databases/tritium.db", self.db_path, pre_restore_dir, report)
            # v1 compat: db might be at root level
            if "databases/tritium.db" not in names:
                db_name = self.db_path.name
                if db_name in names:
                    self._restore_database(zf, names, db_name, self.db_path, pre_restore_dir, report)

            dossier_db = self.data_dir / "dossiers.db"
            self._restore_database(zf, names, "databases/dossiers.db", dossier_db, pre_restore_dir, report)

            # -- Restore KuzuDB --
            kuzu_files = [n for n in names if n.startswith("graph/kuzu/")]
            if kuzu_files:
                kuzu_dir = self.data_dir / "kuzu"
                try:
                    if kuzu_dir.exists():
                        shutil.copytree(kuzu_dir, pre_restore_dir / "kuzu")
                    kuzu_dir.mkdir(parents=True, exist_ok=True)
                    for entry in kuzu_files:
                        rel = entry[len("graph/kuzu/"):]
                        if not rel:
                            continue
                        dest = kuzu_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(zf.read(entry))
                    report["restored"].append("kuzu_graph")
                except Exception as e:
                    report["errors"].append(f"kuzu_graph: {e}")

            # -- Restore Amy memory --
            if "amy/memory.json" in names:
                try:
                    amy_dir = self.data_dir / "amy"
                    amy_dir.mkdir(parents=True, exist_ok=True)
                    amy_mem = amy_dir / "memory.json"
                    if amy_mem.exists():
                        shutil.copy2(str(amy_mem), str(pre_restore_dir / "amy_memory.json"))
                    amy_mem.write_bytes(zf.read("amy/memory.json"))
                    report["restored"].append("amy_memory")
                except Exception as e:
                    report["errors"].append(f"amy_memory: {e}")

            # -- Restore Amy transcripts --
            transcript_files = [n for n in names if n.startswith("amy/transcripts/")]
            if transcript_files:
                try:
                    t_dir = self.data_dir / "amy" / "transcripts"
                    t_dir.mkdir(parents=True, exist_ok=True)
                    for entry in transcript_files:
                        rel = entry[len("amy/transcripts/"):]
                        if not rel:
                            continue
                        dest = t_dir / rel
                        dest.write_bytes(zf.read(entry))
                    report["restored"].append("amy_transcripts")
                except Exception as e:
                    report["errors"].append(f"amy_transcripts: {e}")

            # -- Restore plugin state --
            plugin_files = [n for n in names if n.startswith("plugins/")]
            if plugin_files:
                try:
                    for entry in plugin_files:
                        rel = entry[len("plugins/"):]
                        if not rel:
                            continue
                        dest = self.data_dir / "plugins" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(zf.read(entry))
                    report["restored"].append("plugin_state")
                except Exception as e:
                    report["errors"].append(f"plugin_state: {e}")

            # -- Restore configuration --
            if "config/state.json" in names:
                try:
                    config_dest = self.data_dir / "config_restored.json"
                    config_dest.write_bytes(zf.read("config/state.json"))
                    report["restored"].append("configuration")
                except Exception as e:
                    report["errors"].append(f"configuration: {e}")

            # -- Restore backstories --
            backstory_files = [n for n in names if n.startswith("backstories/")]
            if backstory_files:
                try:
                    bs_dir = self.data_dir / "backstories"
                    bs_dir.mkdir(parents=True, exist_ok=True)
                    for entry in backstory_files:
                        rel = entry[len("backstories/"):]
                        if not rel:
                            continue
                        dest = bs_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(zf.read(entry))
                    report["restored"].append("backstories")
                except Exception as e:
                    report["errors"].append(f"backstories: {e}")

        logger.info(
            f"Backup restored: {len(report['restored'])} items, "
            f"{len(report['errors'])} errors"
        )
        return report

    # ------------------------------------------------------------------
    # List backups
    # ------------------------------------------------------------------

    def list_backups(self) -> list[dict[str, Any]]:
        """List available backups in the backup directory.

        Returns
        -------
        list[dict]
            Backup metadata sorted by creation time (newest first).
        """
        backups = []
        for path in sorted(self.backup_dir.glob("tritium_backup_*.zip"), reverse=True):
            entry: dict[str, Any] = {
                "id": path.stem,
                "filename": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "created_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            # Try to read manifest for extra metadata
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    if "manifest.json" in zf.namelist():
                        manifest = json.loads(zf.read("manifest.json"))
                        entry["label"] = manifest.get("label", "")
                        entry["version"] = manifest.get("version", "")
                        entry["contents"] = list(manifest.get("contents", {}).keys())
            except Exception:
                entry["label"] = ""
                entry["version"] = "unknown"
                entry["contents"] = []

            backups.append(entry)
        return backups

    def get_backup_path(self, backup_id: str) -> Path | None:
        """Resolve a backup ID to its file path.

        Parameters
        ----------
        backup_id : str
            The backup stem name (filename without .zip).

        Returns
        -------
        Path or None
            Path to the backup file, or None if not found.
        """
        path = self.backup_dir / f"{backup_id}.zip"
        return path if path.exists() else None

    # ------------------------------------------------------------------
    # Scheduled auto-backup
    # ------------------------------------------------------------------

    def schedule(self, interval_hours: float) -> None:
        """Start periodic auto-backup on a background thread.

        Parameters
        ----------
        interval_hours : float
            Hours between automatic backups. Must be > 0.
        """
        if interval_hours <= 0:
            raise ValueError("interval_hours must be positive")

        self.stop_schedule()
        self._scheduler_interval_hours = interval_hours
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="backup-scheduler",
        )
        self._scheduler_thread.start()
        logger.info(f"Backup scheduler started (every {interval_hours}h)")

    def stop_schedule(self) -> None:
        """Stop the periodic auto-backup scheduler."""
        self._scheduler_stop.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=5)
            self._scheduler_thread = None
            logger.info("Backup scheduler stopped")

    @property
    def scheduler_active(self) -> bool:
        """Whether the auto-backup scheduler is currently running."""
        return (
            self._scheduler_thread is not None
            and self._scheduler_thread.is_alive()
        )

    def _scheduler_loop(self) -> None:
        """Background loop that creates backups at fixed intervals."""
        interval_seconds = self._scheduler_interval_hours * 3600
        while not self._scheduler_stop.wait(timeout=interval_seconds):
            try:
                self.export_state(label="auto")
                self._prune_old_backups(keep=10)
            except Exception:
                logger.exception("Auto-backup failed")

    def _prune_old_backups(self, keep: int = 10) -> None:
        """Remove oldest auto-backups beyond the retention limit."""
        auto_backups = sorted(
            self.backup_dir.glob("tritium_backup_*_auto.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in auto_backups[keep:]:
            try:
                old.unlink()
                logger.info(f"Pruned old backup: {old.name}")
            except Exception:
                logger.warning(f"Failed to prune backup: {old.name}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _backup_sqlite(
        self,
        zf: zipfile.ZipFile,
        db_path: Path,
        archive_name: str,
        manifest: dict,
    ) -> None:
        """Safely backup a SQLite database using the backup API."""
        if not db_path.exists():
            return

        key = Path(archive_name).stem
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Use SQLite backup API for a consistent snapshot
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(tmp_path)
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()

            zf.write(tmp_path, archive_name)
            manifest["contents"][key] = {
                "file": archive_name,
                "size_bytes": Path(tmp_path).stat().st_size,
            }
        except Exception as e:
            logger.warning(f"Failed to backup {db_path}: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _backup_directory(
        self, zf: zipfile.ZipFile, src_dir: Path, archive_prefix: str
    ) -> int:
        """Recursively add a directory to the ZIP archive."""
        count = 0
        for file_path in src_dir.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(src_dir)
                zf.write(str(file_path), f"{archive_prefix}/{rel}")
                count += 1
        return count

    def _collect_plugin_state(self) -> list[tuple[str, Path]]:
        """Collect plugin state files (JSON, DB) from the plugins data directory."""
        results: list[tuple[str, Path]] = []
        plugin_data = self.data_dir / "plugins"
        if plugin_data.is_dir():
            for f in plugin_data.rglob("*"):
                if f.is_file():
                    results.append((str(f.relative_to(plugin_data)), f))
        return results

    def _collect_configuration(self) -> dict[str, Any]:
        """Collect exportable configuration state from known locations."""
        config: dict[str, Any] = {}

        # Automation rules
        auto_rules = self.data_dir / "automation_rules.json"
        if auto_rules.exists():
            try:
                config["automation_rules"] = json.loads(auto_rules.read_text())
            except Exception:
                pass

        # Geofence zones
        geo_zones = self.data_dir / "geofence_zones.json"
        if geo_zones.exists():
            try:
                config["geofence_zones"] = json.loads(geo_zones.read_text())
            except Exception:
                pass

        # Patrol routes
        patrol_routes = self.data_dir / "patrol_routes.json"
        if patrol_routes.exists():
            try:
                config["patrol_routes"] = json.loads(patrol_routes.read_text())
            except Exception:
                pass

        # Threat indicators
        threat_indicators = self.data_dir / "threat_indicators.json"
        if threat_indicators.exists():
            try:
                config["threat_indicators"] = json.loads(threat_indicators.read_text())
            except Exception:
                pass

        # Dashboard layouts
        layouts = self.data_dir / "dashboard_layouts.json"
        if layouts.exists():
            try:
                config["dashboard_layouts"] = json.loads(layouts.read_text())
            except Exception:
                pass

        return config

    def _restore_database(
        self,
        zf: zipfile.ZipFile,
        names: set[str],
        archive_name: str,
        dest_path: Path,
        pre_restore_dir: Path,
        report: dict,
    ) -> None:
        """Restore a single database from the archive."""
        if archive_name not in names:
            return

        key = Path(archive_name).stem
        try:
            # Safety: back up current database
            if dest_path.exists():
                backup_name = f"{dest_path.stem}_backup{dest_path.suffix}"
                shutil.copy2(str(dest_path), str(pre_restore_dir / backup_name))

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(zf.read(archive_name))
            report["restored"].append(key)
        except Exception as e:
            report["errors"].append(f"{key}: {e}")
