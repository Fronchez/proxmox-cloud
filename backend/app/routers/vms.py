from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from app.schemas import VMCreate, VMResponse
from app.proxmox import ProxmoxAPI
from app.auth import get_current_user
from app.models import User

router = APIRouter()
proxmox = ProxmoxAPI()


@router.get("/", response_model=List[VMResponse])
async def list_vms(current_user: User = Depends(get_current_user)):
    """Получить список всех VM."""
    try:
        vms_data = await proxmox.list_vms("qemu")
        result = []
        for vm in vms_data:
            vmid = vm.get("vmid")
            config = await proxmox.get_vm_config(vmid, "qemu")
            ip = await proxmox.get_vm_ip(vmid, "qemu")
            result.append(VMResponse(
                vmid=vmid,
                name=config.get("name", f"vm-{vmid}"),
                type="qemu",
                os=config.get("ostype", "unknown"),
                cpu=config.get("cores", 1),
                memory=config.get("memory", 512),
                disk=10,  # Нужно парсить из scsi0/ide0
                ip=ip,
                status=vm.get("status", "unknown")
            ))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=VMResponse)
async def create_vm(vm: VMCreate, current_user: User = Depends(get_current_user)):
    """Создать новую VM."""
    try:
        vmid = await proxmox.create_vm(
            name=vm.name,
            os=vm.os,
            cpu=vm.cpu,
            memory=vm.memory,
            disk=vm.disk
        )
        return VMResponse(
            vmid=vmid,
            name=vm.name,
            type="qemu",
            os=vm.os,
            cpu=vm.cpu,
            memory=vm.memory,
            disk=vm.disk,
            ip=None,
            status="created"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{vmid}", response_model=VMResponse)
async def get_vm(vmid: int, current_user: User = Depends(get_current_user)):
    """Получить информацию о VM."""
    try:
        config = await proxmox.get_vm_config(vmid, "qemu")
        status_data = await proxmox.get_vm_status(vmid, "qemu")
        ip = await proxmox.get_vm_ip(vmid, "qemu")
        return VMResponse(
            vmid=vmid,
            name=config.get("name", f"vm-{vmid}"),
            type="qemu",
            os=config.get("ostype", "unknown"),
            cpu=config.get("cores", 1),
            memory=config.get("memory", 512),
            disk=10,
            ip=ip,
            status=status_data.get("status", "unknown")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vmid}/start")
async def start_vm(vmid: int, current_user: User = Depends(get_current_user)):
    """Запустить VM."""
    try:
        await proxmox.start_vm(vmid, "qemu")
        return {"status": "started", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vmid}/stop")
async def stop_vm(vmid: int, current_user: User = Depends(get_current_user)):
    """Остановить VM."""
    try:
        await proxmox.stop_vm(vmid, "qemu")
        return {"status": "stopped", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vmid}/shutdown")
async def shutdown_vm(vmid: int, current_user: User = Depends(get_current_user)):
    """Корректно завершить работу VM (требуется qemu-guest-agent)."""
    try:
        await proxmox._request("POST", f"/nodes/{proxmox.PROXMOX_NODE}/qemu/{vmid}/status/shutdown")
        return {"status": "shutting_down", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{vmid}")
async def delete_vm(vmid: int, current_user: User = Depends(get_current_user)):
    """Удалить VM."""
    try:
        await proxmox.delete_vm(vmid, "qemu")
        return {"status": "deleted", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
