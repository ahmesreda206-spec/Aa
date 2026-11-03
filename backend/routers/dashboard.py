from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import AuthContext, get_auth_context
from ..models import Device, Telemetry
from ..schemas import AlertOut, DashboardMetrics, DashboardSummary, TelemetryOut
from .iot import device_out

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def reading_alerts(device: Device, reading: Telemetry | None) -> list[AlertOut]:
    if reading is None:
        return [
            AlertOut(
                id=f"{device.id}:no-data",
                device_id=device.id,
                device_name=device.name,
                severity="warning",
                message="No telemetry has been received",
                created_at=device.created_at,
            )
        ]
    checks = [
        ("temperature", reading.temperature_c > 38 or reading.temperature_c < 0, "critical", f"Temperature is {reading.temperature_c:.1f} °C"),
        ("soil", reading.soil_moisture_pct < 15, "warning", f"Soil moisture is low at {reading.soil_moisture_pct:.0f}%"),
        ("water", reading.water_level_pct < 20, "critical", f"Water reserve is low at {reading.water_level_pct:.0f}%"),
        ("battery", reading.battery_v < 3.4, "warning", f"Battery voltage is low at {reading.battery_v:.2f} V"),
    ]
    return [
        AlertOut(
            id=f"{device.id}:{key}",
            device_id=device.id,
            device_name=device.name,
            severity=severity,
            message=message,
            created_at=reading.recorded_at,
        )
        for key, triggered, severity, message in checks
        if triggered
    ]


@router.get("/summary", response_model=DashboardSummary)
def summary(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
) -> DashboardSummary:
    devices = list(db.scalars(select(Device).order_by(Device.zone, Device.name)).all())
    latest: list[Telemetry] = []
    alerts: list[AlertOut] = []
    for device in devices:
        reading = db.scalar(
            select(Telemetry)
            .where(Telemetry.device_id == device.id)
            .order_by(Telemetry.recorded_at.desc())
            .limit(1)
        )
        if reading:
            latest.append(reading)
        alerts.extend(reading_alerts(device, reading))
    readings = list(
        db.scalars(select(Telemetry).order_by(Telemetry.recorded_at.desc()).limit(100)).all()
    )
    readings.reverse()
    count = len(latest)
    average = lambda attribute: (  # noqa: E731
        round(sum(getattr(reading, attribute) for reading in latest) / count, 1) if count else None
    )
    device_outputs = [device_out(device) for device in devices]
    return DashboardSummary(
        metrics=DashboardMetrics(
            total_devices=len(devices),
            online_devices=sum(device.online for device in device_outputs),
            active_alerts=len(alerts),
            average_temperature_c=average("temperature_c"),
            average_soil_moisture_pct=average("soil_moisture_pct"),
            average_water_level_pct=average("water_level_pct"),
        ),
        devices=device_outputs,
        alerts=sorted(alerts, key=lambda alert: alert.created_at, reverse=True),
        readings=[TelemetryOut.model_validate(reading) for reading in readings],
        generated_at=datetime.now(timezone.utc),
    )
