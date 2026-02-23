from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from app.schemas import VMCreate, VMResponse
from app.proxmox import ProxmoxAPI
from app.auth import get_current_user
from app.models import User

router = APIRouter()
proxmox = ProxmoxAPI()


@router.get("/", response_model=List[VMResponse])
async def list_lxc(current_user: User = Depends(get_current_user)):
    """Получить список всех LXC контейнеров."""
    try:
        vms_data = await proxmox.list_vms("lxc")
        result = []
        for vm in vms_data:
            vmid = vm.get("vmid")
            config = await proxmox.get_vm_config(vmid, "lxc")
            ip = await proxmox.get_vm_ip(vmid, "lxc")
            result.append(VMResponse(
                vmid=vmid,
                name=config.get("hostname", f"lxc-{vmid}"),
                type="lxc",
                os=config.get("ostemplate", "unknown").split("/")[-1].replace(".tar.gz", ""),
                cpu=config.get("cores", 1),
                memory=config.get("memory", 512),
                disk=4,  # Нужно парсить из rootfs
                ip=ip,
                status=vm.get("status", "unknown")
            ))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=VMResponse)
async def create_lxc(vm: VMCreate, current_user: User = Depends(get_current_user)):
    """Создать новый LXC контейнер."""
    try:
        vmid = await proxmox.create_lxc(
            hostname=vm.name,
            ostemplate=vm.os,
            cpu=vm.cpu,
            memory=vm.memory,
            disk=vm.disk
        )
        return VMResponse(
            vmid=vmid,
            name=vm.name,
            type="lxc",
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
async def get_lxc(vmid: int, current_user: User = Depends(get_current_user)):
    """Получить информацию о LXC контейнере."""
    try:
        config = await proxmox.get_vm_config(vmid, "lxc")
        status_data = await proxmox.get_vm_status(vmid, "lxc")
        ip = await proxmox.get_vm_ip(vmid, "lxc")
        return VMResponse(
            vmid=vmid,
            name=config.get("hostname", f"lxc-{vmid}"),
            type="lxc",
            os=config.get("ostemplate", "unknown").split("/")[-1].replace(".tar.gz", ""),
            cpu=config.get("cores", 1),
            memory=config.get("memory", 512),
            disk=4,
            ip=ip,
            status=status_data.get("status", "unknown")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vmid}/start")
async def start_lxc(vmid: int, current_user: User = Depends(get_current_user)):
    """Запустить LXC контейнер."""
    try:
        await proxmox.start_vm(vmid, "lxc")
        return {"status": "started", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vmid}/stop")
async def stop_lxc(vmid: int, current_user: User = Depends(get_current_user)):
    """Остановить LXC контейнер."""
    try:
        await proxmox.stop_vm(vmid, "lxc")
        return {"status": "stopped", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vmid}/shutdown")
async def shutdown_lxc(vmid: int, current_user: User = Depends(get_current_user)):
    """Корректно завершить работу LXC контейнера."""
    try:
        await proxmox._request("POST", f"/nodes/{proxmox.PROXMOX_NODE}/lxc/{vmid}/status/shutdown")
        return {"status": "shutting_down", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{vmid}")
async def delete_lxc(vmid: int, current_user: User = Depends(get_current_user)):
    """Удалить LXC контейнер."""
    try:
        await proxmox.delete_vm(vmid, "lxc")
        return {"status": "deleted", "vmid": vmid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
