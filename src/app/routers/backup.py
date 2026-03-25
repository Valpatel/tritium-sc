# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Backup and restore API for Tritium-SC state.

Endpoints:
- POST /api/backup/create   — trigger backup, return download URL
- GET  /api/backup/list     — available backups
- POST /api/backup/restore  — upload and restore from archive
- GET  /api/backup/download/{id} — download a specific backup file
- GET  /api/backup/status   — system backup status
- POST /api/backup/schedule — configure auto-backup interval
"""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel

from app.auth import require_auth
from app.config import settings
from engine.backup.backup import BackupManager


router = APIRouter(prefix="/api/backup", tags=["backup"], dependencies=[Depends(require_auth)])


def _get_db_path() -> Path:
    """Extract SQLite file path from database URL."""
    url = settings.database_url
    if ":///" in url:
        path = url.split(":///")[-1]
        return Path(path)
    return Path("tritium.db")


def _get_manager() -> BackupManager:
    """Create a BackupManager with current settings."""
    return BackupManager(
        data_dir=Path("data"),
        backup_dir=Path("data/backups"),
        db_path=_get_db_path(),
    )


# Keep a module-level manager for the scheduler
_manager: BackupManager | None = None


def _shared_manager() -> BackupManager:
    """Get or create a shared manager instance (preserves scheduler state)."""
    global _manager
    if _manager is None:
        _manager = _get_manager()
    return _manager


# ------------------------------------------------------------------
# Request/Response models
# ------------------------------------------------------------------

class CreateBackupRequest(BaseModel):
    label: str = ""


class ScheduleRequest(BaseModel):
    interval_hours: float


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/create")
async def create_backup(body: CreateBackupRequest | None = None):
    """Trigger a backup and return download info.

    Returns the backup ID and a download URL.
    """
    mgr = _shared_manager()
    label = body.label if body else ""

    try:
        archive_path = mgr.export_state(label=label or None)
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        raise HTTPException(status_code=500, detail="Backup operation failed")

    backup_id = archive_path.stem
    return {
        "status": "created",
        "backup_id": backup_id,
        "filename": archive_path.name,
        "size_bytes": archive_path.stat().st_size,
        "download_url": f"/api/backup/download/{backup_id}",
    }


@router.get("/list")
async def list_backups():
    """List available backups, newest first."""
    mgr = _shared_manager()
    backups = mgr.list_backups()
    return {
        "backups": backups,
        "count": len(backups),
    }


MAX_BACKUP_SIZE = 500 * 1024 * 1024  # 500 MB
MAX_ZIP_ENTRIES = 10_000  # Prevent zip bomb with excessive file count


def _validate_zip_safety(zip_path: Path) -> None:
    """Validate ZIP contents for path traversal and zip bomb attacks.

    Raises HTTPException on any safety violation.
    """
    import zipfile as zf

    try:
        with zf.ZipFile(zip_path, "r") as archive:
            entries = archive.namelist()

            # Check entry count (zip bomb protection)
            if len(entries) > MAX_ZIP_ENTRIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP contains too many entries ({len(entries)} > {MAX_ZIP_ENTRIES})",
                )

            # Check for path traversal in every entry
            for entry in entries:
                # Normalize and check for traversal
                if entry.startswith("/") or ".." in entry.split("/"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"ZIP contains unsafe path: {entry}",
                    )
                # Check for absolute paths on Windows too
                if ":" in entry.split("/")[0]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"ZIP contains absolute path: {entry}",
                    )

            # Check total uncompressed size (zip bomb protection)
            total_uncompressed = sum(info.file_size for info in archive.infolist())
            if total_uncompressed > MAX_BACKUP_SIZE * 10:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP uncompressed size too large ({total_uncompressed} bytes)",
                )
    except zf.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")


@router.post("/restore")
async def restore_backup(file: UploadFile = File(...)):
    """Upload a backup archive and restore system state.

    WARNING: This overwrites current databases and state.
    The server should be restarted after restore.

    Security:
    - Max file size: 500 MB
    - File type validation: must be .zip with valid ZIP magic bytes
    - Path traversal protection: no .. or absolute paths in ZIP entries
    - Zip bomb protection: max 10,000 entries, max 5 GB uncompressed
    - Files stored in system temp directory (not user-accessible)
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")

    # Stream upload to temp file with size limit enforcement
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            total_read = 0
            chunk_size = 64 * 1024  # 64 KB chunks
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > MAX_BACKUP_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Backup file too large (max {MAX_BACKUP_SIZE // (1024*1024)} MB)",
                    )
                tmp.write(chunk)

        if total_read == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")

        # Validate ZIP magic bytes (PK header)
        with open(tmp_path, "rb") as f:
            magic = f.read(4)
        if magic[:2] != b"PK":
            raise HTTPException(status_code=400, detail="File is not a valid ZIP archive")

        # Validate ZIP safety (path traversal, zip bombs)
        _validate_zip_safety(tmp_path)

        mgr = _shared_manager()
        report = mgr.import_state(tmp_path)
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Restore validation error: {e}")
        raise HTTPException(status_code=400, detail="Invalid backup file")
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(status_code=500, detail="Restore operation failed")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return {
        "status": "restored",
        "message": "Backup imported successfully. Restart the server to apply changes.",
        "restored": report["restored"],
        "errors": report["errors"],
        "manifest": report.get("manifest"),
    }


@router.get("/download/{backup_id}")
async def download_backup(backup_id: str):
    """Download a specific backup archive by ID."""
    mgr = _shared_manager()
    path = mgr.get_backup_path(backup_id)

    if path is None:
        raise HTTPException(status_code=404, detail=f"Backup not found: {backup_id}")

    return FileResponse(
        path=str(path),
        media_type="application/zip",
        filename=path.name,
    )


@router.get("/status")
async def backup_status():
    """Get backup system status."""
    mgr = _shared_manager()
    db_path = _get_db_path()
    backups = mgr.list_backups()

    return {
        "database_exists": db_path.exists(),
        "database_size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "database_path": str(db_path),
        "amy_memory_exists": Path("data/amy/memory.json").exists(),
        "dossiers_db_exists": Path("data/dossiers.db").exists(),
        "backup_count": len(backups),
        "latest_backup": backups[0] if backups else None,
        "scheduler_active": mgr.scheduler_active,
        "backup_ready": db_path.exists(),
    }


@router.post("/schedule")
async def set_schedule(body: ScheduleRequest):
    """Configure automatic periodic backups.

    Set interval_hours > 0 to enable, or 0 to disable.
    """
    mgr = _shared_manager()

    if body.interval_hours <= 0:
        mgr.stop_schedule()
        return {"status": "disabled", "message": "Auto-backup scheduler stopped"}

    mgr.schedule(body.interval_hours)
    return {
        "status": "enabled",
        "interval_hours": body.interval_hours,
        "message": f"Auto-backup scheduled every {body.interval_hours} hours",
    }


# Legacy endpoints for backwards compatibility with existing router

@router.post("/export")
async def export_backup():
    """Legacy export endpoint — redirects to /create."""
    return await create_backup()


@router.post("/import")
async def import_backup(file: UploadFile = File(...)):
    """Legacy import endpoint — redirects to /restore."""
    return await restore_backup(file)
