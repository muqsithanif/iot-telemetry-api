"""Device registry. Creating and deleting devices is an admin action."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import generate_api_key, get_current_user, hash_api_key, require_admin
from app.database import get_db
from app.models import Device, User
from app.schemas import DeviceCreate, DeviceCreated, DeviceOut

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("", response_model=DeviceCreated, status_code=status.HTTP_201_CREATED)
def register_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> DeviceCreated:
    if db.query(Device).filter(Device.name == payload.name).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Device name already registered"
        )

    api_key = generate_api_key()
    device = Device(
        name=payload.name,
        location=payload.location,
        api_key_hash=hash_api_key(api_key),
    )
    db.add(device)
    db.commit()
    db.refresh(device)

    # The plaintext key is shown here and never again — only its hash is stored,
    # so a database dump does not hand over working device credentials.
    return DeviceCreated(
        id=device.id,
        name=device.name,
        location=device.location,
        created_at=device.created_at,
        api_key=api_key,
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[Device]:
    return db.query(Device).order_by(Device.id).all()


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(
    device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    device_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> None:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    db.delete(device)  # readings cascade
    db.commit()
