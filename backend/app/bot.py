import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from app.config import settings
from app.proxmox import ProxmoxAPI
from app.database import SessionLocal
from app.models import VM

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(settings.TELEGRAM_TOKEN)
dp = Dispatcher()
proxmox = ProxmoxAPI()


# === Машина состояний для создания VM ===
class VMCreate(StatesGroup):
    waiting_for_name = State()
    waiting_for_iso = State()
    waiting_for_cpu = State()
    waiting_for_memory = State()
    waiting_for_disk = State()


# === Машина состояний для создания LXC ===
class LXCCreate(StatesGroup):
    waiting_for_name = State()
    waiting_for_template = State()
    waiting_for_cpu = State()
    waiting_for_memory = State()
    waiting_for_disk = State()


# === Данные для текущей VM ===
vm_data = {}
# Хранилище шаблонов для LXC (временное)
lxc_templates_cache = {}


# === Клавиатуры ===
def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Список VM", callback_data="list_vms"),
                InlineKeyboardButton(text="➕ Создать VM", callback_data="create_vm_start"),
            ],
            [
                InlineKeyboardButton(text="📦 Список LXC", callback_data="list_lxc"),
                InlineKeyboardButton(text="🐳 Создать LXC", callback_data="create_lxc_start"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh"),
            ],
        ]
    )


async def get_iso_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с ISO образами."""
    isos = await proxmox.get_iso_images("local")
    
    if not isos:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Нет ISO образов", callback_data="no_iso")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create")],
            ]
        )
    
    keyboard = []
    for iso in isos:
        name = iso["name"][:30]  # Обрезаем длинные имена
        keyboard.append([InlineKeyboardButton(text=f"💿 {name}", callback_data=f"iso_{iso['volid']}")])
    
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def get_lxc_template_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с шаблонами LXC."""
    global lxc_templates_cache
    
    templates = await proxmox.get_lxc_templates("local")
    
    # Очищаем кэш
    lxc_templates_cache = {}
    
    if not templates:
        # Шаблоны по умолчанию
        default_templates = [
            ("🐧 Ubuntu 22.04", "ubuntu-22.04"),
            ("🐧 Ubuntu 20.04", "ubuntu-20.04"),
            ("🐧 Debian 11", "debian-11"),
            ("🐧 Debian 12", "debian-12"),
            ("🟠 Alpine 3.18", "alpine-3.18"),
            ("🟠 Alpine 3.19", "alpine-3.19"),
            ("🐍 CentOS 7", "centos-7"),
            ("🎩 Rocky Linux 9", "rockylinux-9"),
        ]
        keyboard = []
        for idx, (name, tmpl) in enumerate(default_templates):
            lxc_templates_cache[str(idx)] = tmpl
            keyboard.append([InlineKeyboardButton(text=name, callback_data=f"lxc_tmpl_{idx}")])
        keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    keyboard = []
    for idx, tmpl in enumerate(templates):
        name = tmpl["name"][:30]
        lxc_templates_cache[str(idx)] = tmpl["volid"]
        keyboard.append([InlineKeyboardButton(text=f"📦 {name}", callback_data=f"lxc_tmpl_{idx}")])
    
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_vm_keyboard(vmid: int, vm_type: str = "qemu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Start", callback_data=f"vm_start_{vmid}"),
                InlineKeyboardButton(text="⏹️ Stop", callback_data=f"vm_stop_{vmid}"),
            ],
            [
                InlineKeyboardButton(text="🔄 Restart", callback_data=f"vm_restart_{vmid}"),
                InlineKeyboardButton(text="🗑️ Delete", callback_data=f"vm_delete_{vmid}"),
            ],
            [
                InlineKeyboardButton(text="☁️ Cloud-Init", callback_data=f"vm_cloudinit_{vmid}"),
                InlineKeyboardButton(text="🔄 Обновить IP", callback_data=f"vm_refresh_ip_{vmid}"),
            ],
            [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="list_vms")],
        ]
    )


def get_lxc_keyboard(vmid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Start", callback_data=f"lxc_start_{vmid}"),
                InlineKeyboardButton(text="⏹️ Stop", callback_data=f"lxc_stop_{vmid}"),
            ],
            [
                InlineKeyboardButton(text="🔄 Restart", callback_data=f"lxc_restart_{vmid}"),
                InlineKeyboardButton(text="🗑️ Delete", callback_data=f"lxc_delete_{vmid}"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить IP", callback_data=f"lxc_refresh_ip_{vmid}"),
                InlineKeyboardButton(text="🔑 Пароль", callback_data=f"lxc_password_{vmid}"),
            ],
            [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="list_lxc")],
        ]
    )


def get_vm_list_keyboard(vms: list) -> InlineKeyboardMarkup:
    """Клавиатура со списком VM для выбора."""
    keyboard = []
    for vm in vms[:10]:  # Максимум 10 VM
        vmid = vm.get("vmid", 0)
        name = vm.get("name", f"vm-{vmid}")
        status = vm.get("status", "unknown")
        status_icon = "🟢" if status == "running" else "🔴"
        keyboard.append([
            InlineKeyboardButton(text=f"{status_icon} {vmid} | {name}", callback_data=f"vm_info_{vmid}")
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="refresh")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_lxc_list_keyboard(lxc_list: list) -> InlineKeyboardMarkup:
    """Клавиатура со списком LXC для выбора."""
    keyboard = []
    for lxc in lxc_list[:10]:  # Максимум 10 LXC
        vmid = lxc.get("vmid", 0)
        name = lxc.get("name", f"lxc-{vmid}")
        status = lxc.get("status", "unknown")
        status_icon = "🟢" if status == "running" else "🔴"
        keyboard.append([
            InlineKeyboardButton(text=f"{status_icon} {vmid} | {name}", callback_data=f"lxc_info_{vmid}")
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="refresh")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create")]
        ]
    )


# === Проверка админа ===
async def is_admin(user_id: int) -> bool:
    admin_ids = [x.strip() for x in str(settings.ADMIN_TELEGRAM_ID).split(",")]
    return str(user_id) in admin_ids


async def show_access_denied(target):
    if isinstance(target, Message):
        await target.answer("⛔️ Access denied.")
    elif isinstance(target, CallbackQuery):
        await target.answer("⛔️ Access denied", show_alert=True)


# === Команды ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n"
        "Я Proxmox Cloud Bot для управления VM.\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )


# === Главное меню ===
@dp.callback_query(F.data == "refresh")
async def cb_refresh(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    await callback.message.delete()
    await callback.message.answer(
        f"👋 Привет, {callback.from_user.first_name}!\n"
        "Я Proxmox Cloud Bot для управления VM.\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# === Список VM ===
@dp.callback_query(F.data == "list_vms")
async def cb_list_vms(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    try:
        vms = await proxmox.list_vms("qemu")
        if not vms:
            await callback.message.answer("📭 Нет активных VM.")
            await callback.answer()
            return

        # Формируем текст списка
        text = "📋 <b>Список VM:</b>\n\n"
        for vm in vms:
            vmid = vm.get("vmid", "?")
            name = vm.get("name", f"vm-{vmid}")
            status = vm.get("status", "unknown")
            status_icon = "🟢" if status == "running" else "🔴"
            text += f"{status_icon} <code>{vmid}</code> - {name} ({status})\n"

        text += "\n<b>Нажмите на VM для подробной информации:</b>"

        # Клавиатура со списком VM
        await callback.message.answer(text, parse_mode="HTML", reply_markup=get_vm_list_keyboard(vms))
    except Exception as e:
        logger.error(f"Failed to list VMs: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    finally:
        await callback.answer()


# === Информация о VM ===
@dp.callback_query(F.data.startswith("vm_info_"))
async def cb_vm_info(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("vm_info_", ""))
    
    try:
        info = await proxmox.get_vm_full_info(vmid, "qemu")
        
        if not info:
            await callback.message.answer("❌ Не удалось получить информацию о VM")
            await callback.answer()
            return

        # Форматируем uptime
        uptime_seconds = int(info.get("uptime", 0))
        uptime_str = ""
        if uptime_seconds > 0:
            days = uptime_seconds // 86400
            hours = (uptime_seconds % 86400) // 3600
            mins = (uptime_seconds % 3600) // 60
            if days > 0:
                uptime_str = f"{days}д {hours}ч {mins}м"
            else:
                uptime_str = f"{hours}ч {mins}м"

        # Форматируем использование ресурсов
        # Proxmox возвращает память в байтах, диск в байтах
        mem_used = float(info.get("mem_used", 0)) / (1024 * 1024)  # MB
        mem_total = float(info.get("maxmem", 0)) / (1024 * 1024)  # MB
        
        # Если maxmem = 0, берем из config
        if mem_total == 0:
            mem_total = float(info.get("memory", 512))
        
        disk_used = float(info.get("disk_used", 0)) / (1024 * 1024 * 1024)  # GB
        disk_total = float(info.get("maxdisk", 0)) / (1024 * 1024 * 1024)  # GB
        
        # Если maxdisk = 0, берем из config
        if disk_total == 0:
            disk_total = float(info.get("disk", 10))

        status_icon = "🟢" if info.get("status") == "running" else "🔴"

        report = (
            f"📊 <b>Информация о VM</b>\n\n"
            f"🆔 VMID: <code>{vmid}</code>\n"
            f"📛 Имя: {info.get('name', 'N/A')}\n"
            f"{status_icon} Статус: <b>{info.get('status', 'unknown').upper()}</b>\n\n"
            f"🖥️ <b>Ресурсы:</b>\n"
            f"   CPU: {info.get('cpu', 1)} яд(ер)\n"
            f"   RAM: {mem_used:.0f} / {mem_total:.0f} MB\n"
            f"   Диск: {disk_used:.1f} / {disk_total:.1f} GB\n\n"
        )

        if info.get("status") == "running":
            report += (
                f"🌐 <b>Сеть:</b>\n"
                f"   IP: {info.get('ip') or 'Не получен'}\n\n"
                f"⏱️ <b>Uptime:</b> {uptime_str or 'VM выключена'}\n\n"
                f"🔑 <b>SSH доступ:</b>\n"
                f"<code>ssh root@{info.get('ip') or 'VM_IP'}</code>\n"
            )
        else:
            report += "⏹️ VM выключена\n\n"
            report += "▶️ Запустите VM для получения IP и SSH доступа\n"

        await callback.message.answer(report, parse_mode="HTML", reply_markup=get_vm_keyboard(vmid))
    except Exception as e:
        logger.error(f"Failed to get VM info: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


# === Начало создания VM ===
@dp.callback_query(F.data == "create_vm_start")
async def cb_create_vm_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vm_data[callback.from_user.id] = {}
    await state.set_state(VMCreate.waiting_for_name)
    await callback.message.answer(
        "📝 Введите <b>имя VM</b>:\n"
        "(например: web-server, db, test-vm)",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


# === Ввод имени ===
@dp.message(VMCreate.waiting_for_name)
async def vm_name_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание VM отменено.")
        return

    vm_data[message.from_user.id]["name"] = message.text
    await state.set_state(VMCreate.waiting_for_iso)
    
    # Загружаем ISO образы
    iso_keyboard = await get_iso_keyboard()
    await message.answer(
        "💿 Выберите <b>ISO образ</b> для установки:",
        parse_mode="HTML",
        reply_markup=iso_keyboard
    )


# === Выбор ISO ===
@dp.callback_query(VMCreate.waiting_for_iso, F.data.startswith("iso_"))
async def vm_iso_select(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    iso_volid = callback.data.replace("iso_", "")
    iso_name = iso_volid.split("/")[-1] if "/" in iso_volid else iso_volid
    vm_data[callback.from_user.id]["iso"] = iso_volid
    
    await state.set_state(VMCreate.waiting_for_cpu)
    await callback.message.answer(
        f"✅ ISO: {iso_name}\n\n"
        "🖥️ Введите количество <b>CPU ядер</b>:\n"
        "(например: 1, 2, 4)",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@dp.callback_query(VMCreate.waiting_for_iso, F.data == "no_iso")
async def vm_iso_no_iso(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "❌ В хранилище нет ISO образов.\n"
        "Загрузите ISO образ в Proxmox (local storage) и попробуйте снова."
    )
    await callback.answer()


# === Ввод CPU ===
@dp.message(VMCreate.waiting_for_cpu)
async def vm_cpu_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание VM отменено.")
        return

    try:
        cpu = int(message.text)
        if cpu < 1 or cpu > 128:
            raise ValueError()
        vm_data[message.from_user.id]["cpu"] = cpu
        await state.set_state(VMCreate.waiting_for_memory)
        await message.answer(
            f"✅ CPU: {cpu} яд(ер)\n\n"
            "💾 Введите объем <b>RAM (MB)</b>:\n"
            "(например: 512, 1024, 2048, 4096)",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите число от 1 до 128")


# === Ввод RAM ===
@dp.message(VMCreate.waiting_for_memory)
async def vm_memory_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание VM отменено.")
        return

    try:
        memory = int(message.text)
        if memory < 256 or memory > 262144:
            raise ValueError()
        vm_data[message.from_user.id]["memory"] = memory
        await state.set_state(VMCreate.waiting_for_disk)
        await message.answer(
            f"✅ RAM: {memory} MB\n\n"
            "💽 Введите размер <b>диска (GB)</b>:\n"
            "(например: 10, 20, 50, 100)",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите число от 256 до 262144")


# === Ввод диска и создание VM ===
@dp.message(VMCreate.waiting_for_disk)
async def vm_disk_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание VM отменено.")
        return

    try:
        disk = int(message.text)
        if disk < 4 or disk > 10240:
            raise ValueError()
        vm_data[message.from_user.id]["disk"] = disk

        # Создаём VM
        data = vm_data[message.from_user.id]
        await message.answer(f"⏳ Создаю VM '{data['name']}'...")

        vmid, password = await proxmox.create_vm_with_iso(
            name=data["name"],
            iso_volid=data["iso"],
            cpu=data["cpu"],
            memory=data["memory"],
            disk=data["disk"]
        )

        # Автозапуск
        await message.answer(f"✅ VM создана! VMID: <code>{vmid}</code>\n⏳ Запускаю...")
        await proxmox.start_vm(vmid, "qemu")

        # Ждём запуска
        await asyncio.sleep(5)

        # Получаем информацию
        ip = await proxmox.get_vm_ip(vmid, "qemu")

        # Формируем отчет
        report = (
            f"✅ <b>VM создана и запущена!</b>\n\n"
            f"🆔 VMID: <code>{vmid}</code>\n"
            f"📛 Имя: {data['name']}\n"
            f"💿 ISO: {data['iso'].split('/')[-1]}\n"
            f"🖥️ CPU: {data['cpu']} яд(ер)\n"
            f"💾 RAM: {data['memory']} MB\n"
            f"💽 Диск: {data['disk']} GB\n"
            f"🌐 IP: {ip or 'Ожидание...'}\n\n"
            f"☁️ <b>Cloud-Init настроен:</b>\n"
            f"   Пользователь: <code>root</code>\n"
            f"   🔑 Пароль: <code>{password}</code>\n\n"
            f"🔑 <b>SSH доступ:</b>\n"
            f"<code>ssh root@{ip or 'VM_IP'}</code>\n\n"
            f"⚠️ Для установки ОС:\n"
            f"1. Откройте консоль в Proxmox\n"
            f"2. Пройдите установку ОС\n"
            f"3. После перезагрузки cloud-init применит настройки\n\n"
            f"🔐 <b>Сохраните пароль!</b> Он показывается только один раз."
        )

        await message.answer(report, parse_mode="HTML", reply_markup=get_vm_keyboard(vmid))

        await state.clear()
        vm_data.pop(message.from_user.id, None)

    except ValueError:
        await message.answer("❌ Введите число от 4 до 10240")
    except Exception as e:
        logger.error(f"Failed to create VM: {e}")
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()
        vm_data.pop(message.from_user.id, None)


# === Отмена создания ===
@dp.callback_query(F.data == "cancel_create")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    vm_data.pop(callback.from_user.id, None)
    await callback.message.answer("❌ Создание VM отменено.")
    await callback.answer()


# === Управление VM ===
@dp.callback_query(F.data.startswith("vm_start_"))
async def cb_vm_start(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("vm_start_", ""))
    try:
        await callback.answer("⏳ Запускаю...")
        await proxmox.start_vm(vmid, "qemu")
        
        # Ждём получения IP
        await callback.answer("🌐 Получаю IP...")
        await asyncio.sleep(3)
        ip = await proxmox.get_vm_ip(vmid, "qemu", timeout=10)
        
        if ip:
            await callback.message.answer(
                f"✅ VM {vmid} запущена!\n\n"
                f"🌐 <b>IP адрес:</b>\n"
                f"<code>{ip}</code>\n\n"
                f"🔑 <b>SSH доступ:</b>\n"
                f"<code>ssh root@{ip}</code>"
            )
        else:
            await callback.message.answer(
                f"✅ VM {vmid} запущена!\n\n"
                f"⏳ <b>Ожидание IP адреса...</b>\n\n"
                f"💡 Нажмите '🔄 Обновить IP' через несколько секунд"
            )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("vm_stop_"))
async def cb_vm_stop(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("vm_stop_", ""))
    try:
        await proxmox.stop_vm(vmid, "qemu")
        await callback.message.answer(f"⏹️ VM {vmid} остановлена!")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("vm_restart_"))
async def cb_vm_restart(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("vm_restart_", ""))
    try:
        await proxmox.restart_vm(vmid, "qemu")
        await callback.message.answer(f"🔄 VM {vmid} перезапущена!")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("vm_delete_"))
async def cb_vm_delete(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("vm_delete_", ""))
    try:
        await proxmox.delete_vm(vmid, "qemu")
        await callback.message.answer(f"🗑️ VM {vmid} удалена!")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("vm_cloudinit_"))
async def cb_vm_cloudinit(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("vm_cloudinit_", ""))
    
    report = (
        f"☁️ <b>Cloud-Init для VM {vmid}</b>\n\n"
        f"👤 Пользователь: <code>root</code>\n"
        f"🔑 Пароль: <b>сгенерирован при создании</b>\n"
        f"🌐 Сеть: DHCP (vmbr0)\n"
        f"📶 DNS: 8.8.8.8\n\n"
        f"⚙️ <b>Настройки:</b>\n"
        f"• Пароль устанавливается при первом запуске\n"
        f"• SSH ключи можно добавить через Proxmox\n"
        f"• Сеть настраивается автоматически\n\n"
        f"💡 <b>Совет:</b>\n"
        f"После установки ОС перезагрузите VM для применения cloud-init\n\n"
        f"🔐 Пароль можно изменить в Proxmox: VM → Cloud-Init"
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"vm_info_{vmid}")],
        ]
    )
    
    await callback.message.answer(report, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("vm_refresh_ip_"))
async def cb_vm_refresh_ip(callback: CallbackQuery):
    """Обновить IP адрес VM."""
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("vm_refresh_ip_", ""))
    
    try:
        # Ждём немного для получения IP
        await callback.answer("⏳ Получаю IP адрес...")
        await asyncio.sleep(2)
        
        ip = await proxmox.get_vm_ip(vmid, "qemu")
        
        if ip:
            report = (
                f"🌐 <b>IP адрес обновлён!</b>\n\n"
                f"🆔 VMID: <code>{vmid}</code>\n"
                f"📛 Имя: {(await proxmox.get_vm_config(vmid, 'qemu')).get('name', f'vm-{vmid}')}\n"
                f"🔑 <b>SSH доступ:</b>\n"
                f"<code>ssh root@{ip}</code>\n\n"
                f"✅ IP: {ip}"
            )
        else:
            report = (
                f"⏳ <b>Ожидание IP адреса...</b>\n\n"
                f"🆔 VMID: <code>{vmid}</code>\n\n"
                f"💡 <b>Совет:</b>\n"
                f"• Убедитесь, что VM запущена\n"
                f"• Проверьте, что установлен qemu-guest-agent\n"
                f"• Дождитесь получения IP через DHCP\n\n"
                f"🔄 Попробуйте снова через несколько секунд"
            )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад к VM", callback_data=f"vm_info_{vmid}")],
            ]
        )
        
        await callback.message.answer(report, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Failed to refresh IP: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("lxc_refresh_ip_"))
async def cb_lxc_refresh_ip(callback: CallbackQuery):
    """Обновить IP адрес LXC."""
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("lxc_refresh_ip_", ""))
    
    try:
        await callback.answer("⏳ Получаю IP адрес...")
        await asyncio.sleep(2)
        
        ip = await proxmox.get_vm_ip(vmid, "lxc")
        
        if ip:
            report = (
                f"🌐 <b>IP адрес обновлён!</b>\n\n"
                f"🆔 VMID: <code>{vmid}</code>\n"
                f"📛 Имя: {(await proxmox.get_vm_config(vmid, 'lxc')).get('hostname', f'lxc-{vmid}')}\n"
                f"🔑 <b>SSH доступ:</b>\n"
                f"<code>ssh root@{ip}</code>\n\n"
                f"✅ IP: {ip}"
            )
        else:
            report = (
                f"⏳ <b>Ожидание IP адреса...</b>\n\n"
                f"🆔 VMID: <code>{vmid}</code>\n\n"
                f"💡 <b>Совет:</b>\n"
                f"• Убедитесь, что контейнер запущен\n"
                f"• Дождитесь получения IP через DHCP\n\n"
                f"🔄 Попробуйте снова через несколько секунд"
            )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад к LXC", callback_data=f"lxc_info_{vmid}")],
            ]
        )
        
        await callback.message.answer(report, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Failed to refresh IP: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("lxc_password_"))
async def cb_lxc_password(callback: CallbackQuery):
    """Показать пароль LXC."""
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("lxc_password_", ""))
    
    try:
        # Пробуем получить пароль из БД
        try:
            async with SessionLocal() as db:
                result = await db.execute(select(VM).where(VM.vmid == vmid))
                vm = result.scalar_one_or_none()
            password = vm.password if vm and vm.password else None
        except Exception:
            password = None
        
        config = await proxmox.get_vm_config(vmid, 'lxc')
        name = config.get('hostname', f'lxc-{vmid}')
        
        if password:
            report = (
                f"🔑 <b>Доступ к LXC {vmid}</b>\n\n"
                f"📛 Имя: {name}\n"
                f"👤 Пользователь: <code>root</code>\n"
                f"🔑 Пароль: <code>{password}</code>\n\n"
                f"🔑 <b>SSH доступ:</b>\n"
                f"<code>ssh root@LXC_IP</code>"
            )
        else:
            report = (
                f"🔑 <b>Доступ к LXC {vmid}</b>\n\n"
                f"📛 Имя: {name}\n"
                f"👤 Пользователь: <code>root</code>\n"
                f"🔑 Пароль: <b>не найден в БД</b>\n\n"
                f"⚠️ <b>Важно:</b>\n"
                f"• Пароль устанавливается при создании\n"
                f"• Для сброса используйте консоль Proxmox\n"
                f"• Команда: <code>passwd root</code>"
            )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад к LXC", callback_data=f"lxc_info_{vmid}")],
            ]
        )
        
        await callback.message.answer(report, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Failed to get LXC password: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


# ==================== LXC КОНТЕЙНЕРЫ ====================

# === Список LXC ===
@dp.callback_query(F.data == "list_lxc")
async def cb_list_lxc(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    try:
        lxc_list = await proxmox.list_vms("lxc")
        if not lxc_list:
            await callback.message.answer("📭 Нет активных LXC контейнеров.")
            await callback.answer()
            return

        text = "📦 <b>Список LXC:</b>\n\n"
        for lxc in lxc_list:
            vmid = lxc.get("vmid", "?")
            name = lxc.get("name", f"lxc-{vmid}")
            status = lxc.get("status", "unknown")
            status_icon = "🟢" if status == "running" else "🔴"
            text += f"{status_icon} <code>{vmid}</code> - {name} ({status})\n"

        text += "\n<b>Нажмите на контейнер для подробной информации:</b>"

        await callback.message.answer(text, parse_mode="HTML", reply_markup=get_lxc_list_keyboard(lxc_list))
    except Exception as e:
        logger.error(f"Failed to list LXC: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    finally:
        await callback.answer()


# === Информация о LXC ===
@dp.callback_query(F.data.startswith("lxc_info_"))
async def cb_lxc_info(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("lxc_info_", ""))

    try:
        info = await proxmox.get_vm_full_info(vmid, "lxc")
        
        # Пробуем получить пароль из БД
        password = "Не найден"
        try:
            async with SessionLocal() as db:
                result = await db.execute(select(VM).where(VM.vmid == vmid))
                vm = result.scalar_one_or_none()
            if vm and vm.password:
                password = vm.password
        except Exception:
            password = "БД недоступна"

        if not info:
            await callback.message.answer("❌ Не удалось получить информацию о LXC")
            await callback.answer()
            return

        uptime_seconds = int(info.get("uptime", 0))
        uptime_str = ""
        if uptime_seconds > 0:
            days = uptime_seconds // 86400
            hours = (uptime_seconds % 86400) // 3600
            mins = (uptime_seconds % 3600) // 60
            if days > 0:
                uptime_str = f"{days}д {hours}ч {mins}м"
            else:
                uptime_str = f"{hours}ч {mins}м"

        mem_used = float(info.get("mem_used", 0)) / (1024 * 1024)
        mem_total = float(info.get("maxmem", 0)) / (1024 * 1024)
        if mem_total == 0:
            mem_total = float(info.get("memory", 512))

        disk_used = float(info.get("disk_used", 0)) / (1024 * 1024 * 1024)
        disk_total = float(info.get("maxdisk", 0)) / (1024 * 1024 * 1024)
        if disk_total == 0:
            disk_total = float(info.get("disk", 10))

        status_icon = "🟢" if info.get("status") == "running" else "🔴"

        report = (
            f"📊 <b>Информация о LXC</b>\n\n"
            f"🆔 VMID: <code>{vmid}</code>\n"
            f"📛 Имя: {info.get('name', 'N/A')}\n"
            f"{status_icon} Статус: <b>{info.get('status', 'unknown').upper()}</b>\n\n"
            f"🖥️ <b>Ресурсы:</b>\n"
            f"   CPU: {info.get('cpu', 1)} яд(ер)\n"
            f"   RAM: {mem_used:.0f} / {mem_total:.0f} MB\n"
            f"   Диск: {disk_used:.1f} / {disk_total:.1f} GB\n\n"
            f"🔑 <b>Доступ:</b>\n"
            f"   Пользователь: <code>root</code>\n"
            f"   Пароль: <code>{password}</code>\n\n"
        )

        if info.get("status") == "running":
            report += (
                f"🌐 <b>Сеть:</b>\n"
                f"   IP: {info.get('ip') or 'Не получен'}\n\n"
                f"⏱️ <b>Uptime:</b> {uptime_str or 'Контейнер выключен'}\n\n"
                f"🔑 <b>SSH доступ:</b>\n"
                f"<code>ssh root@{info.get('ip') or 'LXC_IP'}</code>\n"
            )
        else:
            report += "⏹️ Контейнер выключен\n\n"
            report += "▶️ Запустите контейнер для получения IP и SSH доступа\n"

        await callback.message.answer(report, parse_mode="HTML", reply_markup=get_lxc_keyboard(vmid))
    except Exception as e:
        logger.error(f"Failed to get LXC info: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


# === Начало создания LXC ===
@dp.callback_query(F.data == "create_lxc_start")
async def cb_create_lxc_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vm_data[callback.from_user.id] = {}
    await state.set_state(LXCCreate.waiting_for_name)
    await callback.message.answer(
        "📝 Введите <b>имя LXC контейнера</b>:\n"
        "(например: web-container, db-lxc, test)",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


# === Ввод имени LXC ===
@dp.message(LXCCreate.waiting_for_name)
async def lxc_name_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание LXC отменено.")
        return

    vm_data[message.from_user.id]["name"] = message.text
    await state.set_state(LXCCreate.waiting_for_template)
    
    template_keyboard = await get_lxc_template_keyboard()
    await message.answer(
        "📦 Выберите <b>шаблон ОС</b>:",
        parse_mode="HTML",
        reply_markup=template_keyboard
    )


# === Выбор шаблона LXC ===
@dp.callback_query(LXCCreate.waiting_for_template, F.data.startswith("lxc_tmpl_"))
async def lxc_template_select(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    template_idx = callback.data.replace("lxc_tmpl_", "")
    # Получаем шаблон из кэша
    template = lxc_templates_cache.get(template_idx, "ubuntu-22.04")
    
    vm_data[callback.from_user.id]["template"] = template
    template_name = template.split("/")[-1].replace(".tar.gz", "")
    
    await state.set_state(LXCCreate.waiting_for_cpu)
    await callback.message.answer(
        f"✅ Шаблон: {template_name}\n\n"
        "🖥️ Введите количество <b>CPU ядер</b>:\n"
        "(например: 1, 2, 4)",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


# === Ввод CPU для LXC ===
@dp.message(LXCCreate.waiting_for_cpu)
async def lxc_cpu_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание LXC отменено.")
        return

    try:
        cpu = int(message.text)
        if cpu < 1 or cpu > 128:
            raise ValueError()
        vm_data[message.from_user.id]["cpu"] = cpu
        await state.set_state(LXCCreate.waiting_for_memory)
        await message.answer(
            f"✅ CPU: {cpu} яд(ер)\n\n"
            "💾 Введите объем <b>RAM (MB)</b>:\n"
            "(например: 512, 1024, 2048)",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите число от 1 до 128")


# === Ввод RAM для LXC ===
@dp.message(LXCCreate.waiting_for_memory)
async def lxc_memory_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание LXC отменено.")
        return

    try:
        memory = int(message.text)
        if memory < 128 or memory > 65536:
            raise ValueError()
        vm_data[message.from_user.id]["memory"] = memory
        await state.set_state(LXCCreate.waiting_for_disk)
        await message.answer(
            f"✅ RAM: {memory} MB\n\n"
            "💽 Введите размер <b>диска (GB)</b>:\n"
            "(например: 4, 8, 16, 32)",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите число от 128 до 65536")


# === Ввод диска и создание LXC ===
@dp.message(LXCCreate.waiting_for_disk)
async def lxc_disk_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await show_access_denied(message)

    if message.text == "❌ Отмена":
        await state.clear()
        vm_data.pop(message.from_user.id, None)
        await message.answer("Создание LXC отменено.")
        return

    try:
        disk = int(message.text)
        if disk < 2 or disk > 1024:
            raise ValueError()
        vm_data[message.from_user.id]["disk"] = disk

        data = vm_data[message.from_user.id]
        await message.answer(f"⏳ Создаю LXC '{data['name']}'...")

        vmid, password = await proxmox.create_lxc(
            hostname=data["name"],
            ostemplate=data["template"],
            cpu=data["cpu"],
            memory=data["memory"],
            disk=data["disk"]
        )

        # Сохраняем пароль в БД
        async with SessionLocal() as db:
            vm = VM(vmid=vmid, name=data["name"], type="lxc", password=password)
            db.add(vm)
            await db.commit()

        await message.answer(f"✅ LXC создан! VMID: <code>{vmid}</code>\n⏳ Запускаю...")
        await proxmox.start_vm(vmid, "lxc")
        await asyncio.sleep(3)

        ip = await proxmox.get_vm_ip(vmid, "lxc")

        report = (
            f"✅ <b>LXC создан и запущен!</b>\n\n"
            f"🆔 VMID: <code>{vmid}</code>\n"
            f"📛 Имя: {data['name']}\n"
            f"📦 Шаблон: {data['template'].split('/')[-1].replace('.tar.gz', '')}\n"
            f"🖥️ CPU: {data['cpu']} яд(ер)\n"
            f"💾 RAM: {data['memory']} MB\n"
            f"💽 Диск: {data['disk']} GB\n"
            f"🌐 IP: {ip or 'Ожидание...'}\n\n"
            f"🔑 <b>Доступ:</b>\n"
            f"   Пользователь: <code>root</code>\n"
            f"   🔑 Пароль: <code>{password}</code>\n\n"
            f"🔑 <b>SSH доступ:</b>\n"
            f"<code>ssh root@{ip or 'LXC_IP'}</code>\n\n"
            f"🔐 Пароль можно посмотреть в информации о LXC"
        )

        await message.answer(report, parse_mode="HTML", reply_markup=get_lxc_keyboard(vmid))

        await state.clear()
        vm_data.pop(message.from_user.id, None)

    except ValueError:
        await message.answer("❌ Введите число от 2 до 1024")
    except Exception as e:
        logger.error(f"Failed to create LXC: {e}")
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()
        vm_data.pop(message.from_user.id, None)


# === Управление LXC ===
@dp.callback_query(F.data.startswith("lxc_start_"))
async def cb_lxc_start(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("lxc_start_", ""))
    try:
        await callback.answer("⏳ Запускаю...")
        await proxmox.start_vm(vmid, "lxc")
        
        # Ждём получения IP
        await callback.answer("🌐 Получаю IP...")
        await asyncio.sleep(3)
        ip = await proxmox.get_vm_ip(vmid, "lxc", timeout=10)
        
        if ip:
            await callback.message.answer(
                f"✅ LXC {vmid} запущен!\n\n"
                f"🌐 <b>IP адрес:</b>\n"
                f"<code>{ip}</code>\n\n"
                f"🔑 <b>SSH доступ:</b>\n"
                f"<code>ssh root@{ip}</code>"
            )
        else:
            await callback.message.answer(
                f"✅ LXC {vmid} запущен!\n\n"
                f"⏳ <b>Ожидание IP адреса...</b>\n\n"
                f"💡 Нажмите '🔄 Обновить IP' через несколько секунд"
            )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("lxc_stop_"))
async def cb_lxc_stop(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("lxc_stop_", ""))
    try:
        await proxmox.stop_vm(vmid, "lxc")
        await callback.message.answer(f"⏹️ LXC {vmid} остановлен!")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("lxc_restart_"))
async def cb_lxc_restart(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("lxc_restart_", ""))
    try:
        await proxmox.restart_vm(vmid, "lxc")
        await callback.message.answer(f"🔄 LXC {vmid} перезапущен!")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


@dp.callback_query(F.data.startswith("lxc_delete_"))
async def cb_lxc_delete(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await show_access_denied(callback)

    vmid = int(callback.data.replace("lxc_delete_", ""))
    try:
        await proxmox.delete_vm(vmid, "lxc")
        await callback.message.answer(f"🗑️ LXC {vmid} удален!")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


# === Запуск ===
async def main():
    logger.info("Starting bot...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot error: {e}")
        raise
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
