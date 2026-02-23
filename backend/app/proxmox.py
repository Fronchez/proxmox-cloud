import httpx
import logging
import secrets
import string
import asyncio
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


def generate_password(length: int = 12) -> str:
    """Генерация случайного пароля."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class ProxmoxAPI:
    def __init__(self):
        self.base = f"https://{settings.PROXMOX_HOST}:8006/api2/json"
        self.token = f"PVEAPIToken={settings.PROXMOX_TOKEN_ID}={settings.PROXMOX_TOKEN_SECRET}"
        self.headers = {"Authorization": self.token}

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None
    ) -> dict:
        """Универсальный метод для запросов к Proxmox API с обработкой ошибок."""
        url = f"{self.base}{endpoint}"
        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                if method == "GET":
                    response = await client.get(url, headers=self.headers)
                elif method == "POST":
                    response = await client.post(url, headers=self.headers, json=data)
                elif method == "PUT":
                    response = await client.put(url, headers=self.headers, json=data)
                elif method == "DELETE":
                    response = await client.delete(url, headers=self.headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()
                return response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Proxmox API error: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Request error: {e}")
            raise Exception(f"Failed to connect to Proxmox: {str(e)}")

    async def next_vmid(self) -> int:
        """Получить следующий свободный VMID."""
        result = await self._request("GET", "/cluster/nextid")
        # Proxmox возвращает {'data': '105'} (строка!)
        if isinstance(result, int):
            return result
        if isinstance(result, dict):
            val = result.get("data") or result.get("nextid")
            return int(val) if val else 100
        return int(result)

    async def create_vm(
        self,
        name: str,
        os: str = "ubuntu-22.04",
        cpu: int = 1,
        memory: int = 2048,
        disk: int = 10
    ) -> int:
        """Создать новую VM (QEMU)."""
        vmid = await self.next_vmid()
        await self._request("POST", f"/nodes/{settings.PROXMOX_NODE}/qemu", {
            "vmid": vmid,
            "name": name,
            "cores": cpu,
            "memory": memory,
            "scsi0": f"local-lvm:{disk}",
            "scsihw": "virtio-scsi-single",  # VirtIO SCSI контроллер
            "agent": 1,
            "ostype": "l26",
            "bios": "seabios",
        })
        return vmid

    async def create_vm_with_iso(
        self,
        name: str,
        iso_volid: str,
        cpu: int = 1,
        memory: int = 2048,
        disk: int = 10,
        enable_cloud_init: bool = True
    ) -> tuple[int, str]:
        """Создать VM с подключенным ISO образом и cloud-init.
        
        Returns:
            tuple: (vmid, сгенерированный пароль)
        """
        vmid = await self.next_vmid()
        
        # Генерируем случайный пароль
        password = generate_password(16)
        
        params = {
            "vmid": vmid,
            "name": name,
            "cores": cpu,
            "memory": memory,
            "scsi0": f"local-lvm:{disk}",
            "scsihw": "virtio-scsi-single",  # VirtIO SCSI контроллер
            "ide2": f"{iso_volid},media=cdrom",
            "agent": 1,
            "ostype": "l26",
            "bios": "seabios",
            "boot": "order=ide2;scsi0",
            "onboot": 1,
        }
        
        # Добавляем cloud-init если включено
        if enable_cloud_init:
            # Создаем cloud-init диск
            params["ide0"] = "local-lvm:cloudinit"
            # Базовые настройки cloud-init
            params["cipassword"] = password  # Случайный пароль
            params["ciuser"] = "root"  # Пользователь
            params["nameserver"] = "8.8.8.8"
            params["searchdomain"] = "local"
            # Включаем DHCP для сети (правильный формат для Proxmox)
            params["net0"] = "virtio,bridge=vmbr0"
        
        await self._request("POST", f"/nodes/{settings.PROXMOX_NODE}/qemu", params)
        return vmid, password

    async def set_cloud_init(self, vmid: int, 
                             password: str = "proxmox123",
                             user: str = "root",
                             nameserver: str = "8.8.8.8") -> dict:
        """Настроить cloud-init для VM."""
        return await self._request("PUT", f"/nodes/{settings.PROXMOX_NODE}/qemu/{vmid}/config", {
            "ide0": "local-lvm:cloudinit",
            "cipassword": password,
            "ciuser": user,
            "nameserver": nameserver,
            "net0": "virtio,bridge=vmbr0",
        })

    async def create_lxc(
        self,
        hostname: str,
        ostemplate: str = "ubuntu-22.04",
        cpu: int = 1,
        memory: int = 512,
        disk: int = 4,
        ip: str = "dhcp"  # "dhcp" или статический IP в формате "192.168.1.100/24"
    ) -> tuple[int, str]:
        """Создать новый LXC контейнер.
        
        Returns:
            tuple: (vmid, сгенерированный пароль)
        """
        vmid = await self.next_vmid()
        
        # Генерируем случайный пароль
        password = generate_password(16)
        
        # Формируем полный путь к шаблону
        if "/" in ostemplate:
            template_path = ostemplate
        else:
            template_path = f"local:vztmpl/{ostemplate}.tar.gz"
        
        # Настраиваем сеть
        if ip == "dhcp":
            net_config = "name=eth0,bridge=vmbr0"
        else:
            net_config = f"name=eth0,bridge=vmbr0,ip={ip}"
        
        await self._request("POST", f"/nodes/{settings.PROXMOX_NODE}/lxc", {
            "vmid": vmid,
            "hostname": hostname,
            "ostemplate": template_path,
            "cores": cpu,
            "memory": memory,
            "rootfs": f"local-lvm:{disk}",
            "net0": net_config,
            "password": password,  # Случайный пароль
            "onboot": 1,
            "unprivileged": 1,  # Unprivileged контейнер для безопасности
        })
        return vmid, password

    async def start_vm(self, vmid: int, type_: str = "qemu") -> dict:
        """Запустить VM или LXC."""
        return await self._request("POST", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}/status/start")

    async def stop_vm(self, vmid: int, type_: str = "qemu") -> dict:
        """Остановить VM или LXC."""
        return await self._request("POST", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}/status/stop")

    async def delete_vm(self, vmid: int, type_: str = "qemu") -> dict:
        """Удалить VM или LXC."""
        return await self._request("DELETE", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}")

    async def get_vm_status(self, vmid: int, type_: str = "qemu") -> dict:
        """Получить статус VM или LXC."""
        return await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}/status/current")

    async def get_vm_config(self, vmid: int, type_: str = "qemu") -> dict:
        """Получить конфигурацию VM или LXC."""
        return await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}/config")

    async def list_vms(self, type_: str = "qemu") -> list:
        """Получить список всех VM или LXC."""
        result = await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/{type_}")
        if not isinstance(result, list):
            return []
        
        # Для LXC дополнительно получаем IP из interfaces
        if type_ == "lxc":
            for lxc in result:
                vmid = lxc.get("vmid")
                try:
                    iface_result = await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/lxc/{vmid}/interfaces")
                    if isinstance(iface_result, list):
                        for iface in iface_result:
                            if iface.get("name") == "eth0":
                                inet = iface.get("inet", "")
                                if inet and not inet.startswith("127."):
                                    lxc["ip"] = inet.split("/")[0]
                                    break
                except Exception:
                    pass
        
        return result

    async def get_vm_ip(self, vmid: int, type_: str = "qemu", timeout: int = 10) -> Optional[str]:
        """Получить IP адрес VM или LXC.
        
        Args:
            vmid: ID виртуальной машины или контейнера
            type_: Тип (qemu или lxc)
            timeout: Максимальное время ожидания в секундах
        """
        if type_ == "lxc":
            # Для LXC получаем IP из interfaces
            try:
                result = await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/lxc/{vmid}/interfaces")
                if isinstance(result, list):
                    for iface in result:
                        if iface.get("name") == "eth0":
                            inet = iface.get("inet", "")
                            if inet and not inet.startswith("127."):
                                return inet.split("/")[0]
            except Exception as e:
                logger.debug(f"Failed to get LXC IP from interfaces: {e}")
            
            return None
        
        # Для VM используем qemu-guest-agent
        for _ in range(timeout):
            try:
                interfaces = await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}/agent/network-get-interfaces")
                result = interfaces.get("result", [])
                if result:
                    for iface in result:
                        if iface.get("name") == "eth0" and iface.get("ip-addresses"):
                            for addr in iface["ip-addresses"]:
                                if addr.get("ip-address-type") == "ipv4" and addr.get("ip-address"):
                                    ip = addr["ip-address"]
                                    # Пропускаем localhost
                                    if not ip.startswith("127."):
                                        return ip
            except Exception:
                pass
            await asyncio.sleep(1)
        return None

    async def get_iso_images(self, storage: str = "local") -> list:
        """Получить список ISO образов в хранилище."""
        try:
            result = await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/storage/{storage}/content")
            if isinstance(result, list):
                return [
                    {
                        "name": item.get("volid", "").replace(f"{storage}:iso/", ""),
                        "volid": item.get("volid"),
                        "size": item.get("size", 0),
                    }
                    for item in result
                    if item.get("content") == "iso"
                ]
            return []
        except Exception as e:
            logger.error(f"Failed to get ISO images: {e}")
            return []

    async def get_lxc_templates(self, storage: str = "local") -> list:
        """Получить список шаблонов LXC в хранилище."""
        try:
            result = await self._request("GET", f"/nodes/{settings.PROXMOX_NODE}/storage/{storage}/content")
            if isinstance(result, list):
                return [
                    {
                        "name": item.get("volid", "").replace(f"{storage}:vztmpl/", ""),
                        "volid": item.get("volid"),
                        "size": item.get("size", 0),
                    }
                    for item in result
                    if item.get("content") == "vztmpl"
                ]
            return []
        except Exception as e:
            logger.error(f"Failed to get LXC templates: {e}")
            return []

    async def restart_vm(self, vmid: int, type_: str = "qemu") -> dict:
        """Перезапустить VM или LXC."""
        return await self._request("POST", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}/status/reboot")

    async def shutdown_vm(self, vmid: int, type_: str = "qemu") -> dict:
        """Корректно завершить работу VM (требуется qemu-guest-agent)."""
        return await self._request("POST", f"/nodes/{settings.PROXMOX_NODE}/{type_}/{vmid}/status/shutdown")

    async def get_vm_full_info(self, vmid: int, type_: str = "qemu") -> dict:
        """Получить полную информацию о VM."""
        try:
            config = await self.get_vm_config(vmid, type_)
            status = await self.get_vm_status(vmid, type_)
            
            # Получаем IP только если VM запущена
            ip = None
            if status.get("status") == "running":
                try:
                    ip = await self.get_vm_ip(vmid, type_)
                except Exception:
                    pass

            # Парсим диск — может быть строкой или числом
            scsi0 = str(config.get("scsi0", config.get("ide0", "local-lvm:10")))
            disk_size = scsi0.split(":")[-1] if ":" in scsi0 else "10"
            disk_size = disk_size.replace("G", "").replace("g", "")
            try:
                disk_size = float(disk_size)
            except ValueError:
                disk_size = 10.0

            # Конвертируем значения в числа
            def to_float(val, default=0):
                if val is None:
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            return {
                "vmid": vmid,
                "name": config.get("name", f"vm-{vmid}"),
                "status": status.get("status", "unknown"),
                "cpu": config.get("cores", 1),
                "memory": to_float(config.get("memory"), 512),
                "disk": disk_size,
                "os": config.get("ostype", "unknown"),
                "ip": ip,
                "uptime": to_float(status.get("uptime"), 0),
                "cpus": to_float(status.get("cpus"), 1),
                "maxcpu": config.get("cores", 1),
                "maxmem": to_float(config.get("memory"), 512),
                "maxdisk": to_float(status.get("maxdisk"), 10 * 1024 * 1024 * 1024),
                "disk_used": to_float(status.get("disk"), 0),
                "mem_used": to_float(status.get("mem"), 0),
            }
        except Exception as e:
            logger.error(f"Failed to get VM full info: {e}")
            return {}
