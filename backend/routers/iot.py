import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import AuthContext, get_auth_context, require_admin
from ..models import Device, Telemetry
from ..rate_limit import limiter
from ..schemas import DeviceCreate, DeviceOut, DeviceTokenResponse, TelemetryCreate, TelemetryOut
from ..security import device_token_matches, hash_device_token, new_device_credentials
from ..services.audit import audit

router = APIRouter(prefix="/api/iot", tags=["iot"])


def aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def device_out(device: Device) -> DeviceOut:
    last_seen = aware(device.last_seen)
    online = bool(last_seen and last_seen >= datetime.now(timezone.utc) - timedelta(minutes=5))
    return DeviceOut(
        id=device.id,
        name=device.name,
        zone=device.zone,
        latitude=device.latitude,
        longitude=device.longitude,
        active=device.active,
        created_at=device.created_at,
        last_seen=last_seen,
        online=online,
    )


@router.post("/devices", response_model=DeviceTokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def register_device(
    payload: DeviceCreate,
    request: Request,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeviceTokenResponse:
    device_id, token = new_device_credentials()
    device = Device(
        id=device_id,
        name=payload.name,
        zone=payload.zone,
        latitude=payload.latitude,
        longitude=payload.longitude,
        token_hash=hash_device_token(token),
    )
    db.add(device)
    audit(db, request, context.user.username, f"device_registered:{device_id}")
    db.commit()
    return DeviceTokenResponse(device=device_out(device), token=token)


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
) -> list[DeviceOut]:
    devices = db.scalars(select(Device).order_by(Device.zone, Device.name)).all()
    return [device_out(device) for device in devices]


@router.delete("/devices/{device_id}", response_model=DeviceOut)
@limiter.limit("10/minute")
def deactivate_device(
    device_id: str,
    request: Request,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeviceOut:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    device.active = False
    audit(db, request, context.user.username, f"device_deactivated:{device_id}")
    db.commit()
    return device_out(device)


@router.post("/telemetry", response_model=TelemetryOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
def ingest_telemetry(
    payload: TelemetryCreate,
    request: Request,
    x_iot_token: str = Header(default="", min_length=20, max_length=256),
    db: Session = Depends(get_db),
) -> Telemetry:
    if not secrets.compare_digest(x_iot_token.split(".", 1)[0], payload.device_id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device credentials")
    device = db.scalar(select(Device).where(Device.id == payload.device_id, Device.active.is_(True)))
    if not device or not device_token_matches(x_iot_token, device.token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device credentials")
    reading = Telemetry(
        device_id=device.id,
        recorded_at=payload.recorded_at or datetime.now(timezone.utc),
        temperature_c=payload.temperature_c,
        humidity_pct=payload.humidity_pct,
        soil_moisture_pct=payload.soil_moisture_pct,
        water_level_pct=payload.water_level_pct,
        battery_v=payload.battery_v,
        rssi_dbm=payload.rssi_dbm,
    )
    device.last_seen = datetime.now(timezone.utc)
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


@router.get("/telemetry", response_model=list[TelemetryOut])
def telemetry_history(
    device_id: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[Telemetry]:
    query = select(Telemetry)
    if device_id:
        query = query.where(Telemetry.device_id == device_id)
    return list(db.scalars(query.order_by(Telemetry.recorded_at.desc()).limit(limit)).all())
