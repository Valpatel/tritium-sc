"""Asset management and tasking API endpoints.

Assets are autonomous operational units (ground/aerial) that can be
assigned tasks such as patrol, tracking, engagement, and observation.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.database import get_db
from app.models import Asset, AssetTask, AssetTelemetry

router = APIRouter(prefix="/api/assets", tags=["assets"])


# ==================
# Request/Response Models
# ==================

class AssetCreate(BaseModel):
    """Create a new asset."""
    asset_id: str = Field(..., description="Unique identifier (e.g., UNIT-01)")
    name: str = Field(..., description="Display name")
    asset_type: str = Field(..., description="ground, aerial, fixed")
    asset_class: str = Field(default="patrol", description="patrol, interceptor, observation, transport")
    capabilities: list[str] = Field(default=["patrol", "loiter", "recall"])
    connection_url: Optional[str] = None
    camera_url: Optional[str] = None
    home_x: Optional[float] = 0
    home_y: Optional[float] = 0


class AssetUpdate(BaseModel):
    """Update an asset."""
    name: Optional[str] = None
    status: Optional[str] = None
    battery_level: Optional[float] = None
    ammo_level: Optional[float] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    heading: Optional[float] = None
    speed: Optional[float] = None
    enabled: Optional[bool] = None
    connection_url: Optional[str] = None
    camera_url: Optional[str] = None


class AssetResponse(BaseModel):
    """Asset response model."""
    id: int
    asset_id: str
    name: str
    asset_type: str
    asset_class: str
    status: str
    battery_level: Optional[float]
    ammo_level: Optional[float]
    position_x: Optional[float]
    position_y: Optional[float]
    heading: Optional[float]
    speed: Optional[float]
    home_x: Optional[float]
    home_y: Optional[float]
    capabilities: list[str]
    connection_url: Optional[str]
    camera_url: Optional[str]
    enabled: bool
    last_heartbeat: Optional[datetime]
    current_task: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    """Create a new task for an asset."""
    task_type: str = Field(..., description="patrol, track, engage, loiter, recall, rearm, investigate")
    priority: int = Field(default=5, ge=1, le=10)
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    waypoints: Optional[list[list[float]]] = None  # [[x,y], [x,y], ...]
    parameters: Optional[dict] = None


class CommandRequest(BaseModel):
    """Send a command to an asset."""
    command: str = Field(..., description="Command: stop, resume, return_home, emergency_stop, set_speed, rotate")
    parameters: Optional[dict] = None


class TaskResponse(BaseModel):
    """Task response model."""
    id: int
    task_id: str
    asset_id: str
    task_type: str
    priority: int
    status: str
    target_type: Optional[str]
    target_id: Optional[str]
    waypoints: Optional[list[list[float]]]
    parameters: Optional[dict]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result: Optional[str]
    created_at: datetime


class TelemetryUpdate(BaseModel):
    """Telemetry update from asset."""
    position_x: float
    position_y: float
    heading: Optional[float] = None
    speed: Optional[float] = None
    battery_level: Optional[float] = None
    status: Optional[str] = None


# ==================
# Asset CRUD
# ==================

@router.get("", response_model=list[AssetResponse])
async def list_assets(
    asset_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all assets, optionally filtered."""
    query = select(Asset).order_by(Asset.asset_id)

    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if status:
        query = query.where(Asset.status == status)

    result = await db.execute(query)
    assets = result.scalars().all()

    response = []
    for asset in assets:
        # Get current active task
        task_query = select(AssetTask).where(
            AssetTask.asset_id == asset.id,
            AssetTask.status == "active"
        ).order_by(desc(AssetTask.priority))
        task_result = await db.execute(task_query)
        current_task = task_result.scalar_one_or_none()

        asset_dict = {
            "id": asset.id,
            "asset_id": asset.asset_id,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "asset_class": asset.asset_class,
            "status": asset.status,
            "battery_level": asset.battery_level,
            "ammo_level": asset.ammo_level,
            "position_x": asset.position_x,
            "position_y": asset.position_y,
            "heading": asset.heading,
            "speed": asset.speed,
            "home_x": asset.home_x,
            "home_y": asset.home_y,
            "capabilities": json.loads(asset.capabilities) if asset.capabilities else [],
            "connection_url": asset.connection_url,
            "camera_url": asset.camera_url,
            "enabled": asset.enabled,
            "last_heartbeat": asset.last_heartbeat,
            "current_task": {
                "task_id": current_task.task_id,
                "task_type": current_task.task_type,
                "status": current_task.status,
            } if current_task else None,
        }
        response.append(asset_dict)

    return response


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific asset by ID."""
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get current task
    task_query = select(AssetTask).where(
        AssetTask.asset_id == asset.id,
        AssetTask.status == "active"
    )
    task_result = await db.execute(task_query)
    current_task = task_result.scalar_one_or_none()

    return {
        **asset.__dict__,
        "capabilities": json.loads(asset.capabilities) if asset.capabilities else [],
        "current_task": {
            "task_id": current_task.task_id,
            "task_type": current_task.task_type,
            "status": current_task.status,
        } if current_task else None,
    }


@router.post("", response_model=AssetResponse)
async def create_asset(asset: AssetCreate, db: AsyncSession = Depends(get_db)):
    """Register a new asset."""
    # Check if asset_id exists
    existing = await db.execute(select(Asset).where(Asset.asset_id == asset.asset_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Asset ID already exists")

    db_asset = Asset(
        asset_id=asset.asset_id,
        name=asset.name,
        asset_type=asset.asset_type,
        asset_class=asset.asset_class,
        capabilities=json.dumps(asset.capabilities),
        connection_url=asset.connection_url,
        camera_url=asset.camera_url,
        home_x=asset.home_x,
        home_y=asset.home_y,
        position_x=asset.home_x,
        position_y=asset.home_y,
        status="standby",
    )

    db.add(db_asset)
    await db.flush()
    await db.refresh(db_asset)

    logger.info(f"Asset registered: {asset.asset_id} ({asset.name})")

    return {
        **db_asset.__dict__,
        "capabilities": asset.capabilities,
        "current_task": None,
    }


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: str,
    update: AssetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update asset properties."""
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(asset, field, value)

    await db.flush()
    await db.refresh(asset)

    return {
        **asset.__dict__,
        "capabilities": json.loads(asset.capabilities) if asset.capabilities else [],
        "current_task": None,
    }


@router.delete("/{asset_id}")
async def delete_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    """Remove an asset from the system."""
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    await db.delete(asset)
    logger.info(f"Asset deleted: {asset_id}")

    return {"status": "deleted", "asset_id": asset_id}


# ==================
# Asset Tasking
# ==================

@router.post("/{asset_id}/task", response_model=TaskResponse)
async def assign_task(
    asset_id: str,
    task: TaskCreate,
    db: AsyncSession = Depends(get_db),
):
    """Assign a task to an asset."""
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if not asset.enabled:
        raise HTTPException(status_code=400, detail="Asset is disabled")

    # Validate task type against capabilities
    capabilities = json.loads(asset.capabilities) if asset.capabilities else []
    if task.task_type not in capabilities:
        raise HTTPException(
            status_code=400,
            detail=f"Asset does not support task type '{task.task_type}'. Capabilities: {capabilities}"
        )

    # Create task
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    db_task = AssetTask(
        task_id=task_id,
        asset_id=asset.id,
        task_type=task.task_type,
        priority=task.priority,
        status="pending",
        target_type=task.target_type,
        target_id=task.target_id,
        waypoints_json=json.dumps(task.waypoints) if task.waypoints else None,
        parameters_json=json.dumps(task.parameters) if task.parameters else None,
    )

    db.add(db_task)

    # Update asset status
    asset.status = "tasked"

    await db.flush()
    await db.refresh(db_task)

    logger.info(f"Task assigned: {task_id} -> {asset_id} ({task.task_type})")

    return TaskResponse(
        id=db_task.id,
        task_id=db_task.task_id,
        asset_id=asset_id,
        task_type=db_task.task_type,
        priority=db_task.priority,
        status=db_task.status,
        target_type=db_task.target_type,
        target_id=db_task.target_id,
        waypoints=task.waypoints,
        parameters=task.parameters,
        started_at=db_task.started_at,
        completed_at=db_task.completed_at,
        result=db_task.result,
        created_at=db_task.created_at,
    )


@router.get("/{asset_id}/tasks", response_model=list[TaskResponse])
async def list_asset_tasks(
    asset_id: str,
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List tasks for an asset."""
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    query = select(AssetTask).where(AssetTask.asset_id == asset.id)
    if status:
        query = query.where(AssetTask.status == status)
    query = query.order_by(desc(AssetTask.created_at)).limit(limit)

    task_result = await db.execute(query)
    tasks = task_result.scalars().all()

    return [
        TaskResponse(
            id=t.id,
            task_id=t.task_id,
            asset_id=asset_id,
            task_type=t.task_type,
            priority=t.priority,
            status=t.status,
            target_type=t.target_type,
            target_id=t.target_id,
            waypoints=json.loads(t.waypoints_json) if t.waypoints_json else None,
            parameters=json.loads(t.parameters_json) if t.parameters_json else None,
            started_at=t.started_at,
            completed_at=t.completed_at,
            result=t.result,
            created_at=t.created_at,
        )
        for t in tasks
    ]


@router.post("/{asset_id}/task/{task_id}/start")
async def start_task(
    asset_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Start executing a pending task."""
    result = await db.execute(
        select(AssetTask).join(Asset).where(
            Asset.asset_id == asset_id,
            AssetTask.task_id == task_id,
        )
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "pending":
        raise HTTPException(status_code=400, detail=f"Task is {task.status}, not pending")

    task.status = "active"
    task.started_at = datetime.now(timezone.utc)

    await db.flush()

    logger.info(f"Task started: {task_id}")

    return {"status": "started", "task_id": task_id}


@router.post("/{asset_id}/task/{task_id}/complete")
async def complete_task(
    asset_id: str,
    task_id: str,
    result: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Mark a task as completed."""
    db_result = await db.execute(
        select(AssetTask).join(Asset).where(
            Asset.asset_id == asset_id,
            AssetTask.task_id == task_id,
        )
    )
    task = db_result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "completed"
    task.completed_at = datetime.now(timezone.utc)
    task.result = result

    # Update asset status
    asset_result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if asset:
        asset.status = "standby"

    await db.flush()

    logger.info(f"Task completed: {task_id}")

    return {"status": "completed", "task_id": task_id}


@router.post("/{asset_id}/task/{task_id}/cancel")
async def cancel_task(
    asset_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a task."""
    result = await db.execute(
        select(AssetTask).join(Asset).where(
            Asset.asset_id == asset_id,
            AssetTask.task_id == task_id,
        )
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "cancelled"
    task.completed_at = datetime.now(timezone.utc)

    # Update asset status
    asset_result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if asset:
        asset.status = "standby"

    await db.flush()

    logger.info(f"Task cancelled: {task_id}")

    return {"status": "cancelled", "task_id": task_id}


# ==================
# Telemetry & Control
# ==================

@router.post("/{asset_id}/telemetry")
async def update_telemetry(
    asset_id: str,
    telemetry: TelemetryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Receive telemetry update from an asset."""
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Update asset state
    asset.position_x = telemetry.position_x
    asset.position_y = telemetry.position_y
    asset.heading = telemetry.heading
    asset.speed = telemetry.speed
    asset.battery_level = telemetry.battery_level
    asset.last_heartbeat = datetime.now(timezone.utc)

    if telemetry.status:
        asset.status = telemetry.status

    # Store telemetry history
    db_telemetry = AssetTelemetry(
        asset_id=asset.id,
        timestamp=datetime.now(timezone.utc),
        position_x=telemetry.position_x,
        position_y=telemetry.position_y,
        heading=telemetry.heading,
        speed=telemetry.speed,
        battery_level=telemetry.battery_level,
        status=telemetry.status,
    )
    db.add(db_telemetry)

    await db.flush()

    return {"status": "ok", "asset_id": asset_id}


@router.get("/{asset_id}/telemetry")
async def get_telemetry_history(
    asset_id: str,
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Get telemetry history for an asset."""
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    telemetry_result = await db.execute(
        select(AssetTelemetry)
        .where(AssetTelemetry.asset_id == asset.id)
        .order_by(desc(AssetTelemetry.timestamp))
        .limit(limit)
    )
    telemetry = telemetry_result.scalars().all()

    return [
        {
            "timestamp": t.timestamp.isoformat(),
            "position_x": t.position_x,
            "position_y": t.position_y,
            "heading": t.heading,
            "speed": t.speed,
            "battery_level": t.battery_level,
            "status": t.status,
        }
        for t in telemetry
    ]


@router.post("/{asset_id}/command")
async def send_command(
    asset_id: str,
    request: CommandRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a direct command to an asset.

    Commands: stop, resume, return_home, emergency_stop, set_speed, rotate, etc.
    """
    command = request.command
    parameters = request.parameters
    result = await db.execute(select(Asset).where(Asset.asset_id == asset_id))
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # In a real system, this would forward to the asset's control endpoint
    # For now, we just log and update status as needed

    logger.info(f"Command sent to {asset_id}: {command} {parameters}")

    if command == "stop":
        asset.status = "standby"
        asset.speed = 0
    elif command == "return_home":
        asset.status = "returning"
    elif command == "emergency_stop":
        asset.status = "stopped"
        asset.speed = 0

    await db.flush()

    return {
        "status": "sent",
        "asset_id": asset_id,
        "command": command,
        "parameters": parameters,
    }


# ==================
# Quick Actions
# ==================

@router.post("/{asset_id}/patrol")
async def quick_patrol(
    asset_id: str,
    waypoints: list[list[float]],
    db: AsyncSession = Depends(get_db),
):
    """Quick action: Start a patrol with given waypoints."""
    return await assign_task(
        asset_id,
        TaskCreate(task_type="patrol", waypoints=waypoints),
        db,
    )


@router.post("/{asset_id}/recall")
async def quick_recall(asset_id: str, db: AsyncSession = Depends(get_db)):
    """Quick action: Recall asset to home position."""
    return await assign_task(
        asset_id,
        TaskCreate(task_type="recall", priority=1),
        db,
    )


@router.post("/{asset_id}/track")
async def quick_track(
    asset_id: str,
    target_type: str,
    target_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Quick action: Track a specific target."""
    return await assign_task(
        asset_id,
        TaskCreate(
            task_type="track",
            priority=2,
            target_type=target_type,
            target_id=target_id,
        ),
        db,
    )
