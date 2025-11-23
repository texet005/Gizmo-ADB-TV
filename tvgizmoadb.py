import os
import sys
import time
import subprocess
import json
import threading
from typing import Optional, Callable

import httpx
from dotenv import load_dotenv

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from tkinter import messagebox as mb

# -------------------------------------------------
# Цвета темы для панели
# -------------------------------------------------
DARK_PALETTE = {
    "BG": "#1e1e1e",
    "PANEL": "#2a2a2a",
    "FG": "#ffffff",
    "ACCENT": "#4e8cff",
    "WARN": "#ffaa00",
    "OK": "#5cd65c",
    "ERR": "#ff4d4d",
    "LOG_BG": "#1f1f1f",
    "LOG_FG": "#dcdcdc",
}

LIGHT_PALETTE = {
    "BG": "#f0f0f0",
    "PANEL": "#ffffff",
    "FG": "#000000",
    "ACCENT": "#0066cc",
    "WARN": "#ff9900",
    "OK": "#2e8b57",
    "ERR": "#cc0000",
    "LOG_BG": "#ffffff",
    "LOG_FG": "#000000",
}


def apply_custom_style(root: tk.Tk, palette: dict):
    """Настройка темы ttk по палитре."""
    style = ttk.Style(root)

    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=palette["BG"])

    style.configure(
        ".",
        background=palette["BG"],
        foreground=palette["FG"],
        fieldbackground=palette["PANEL"],
        bordercolor=palette["PANEL"],
    )

    style.configure("TLabel", background=palette["BG"], foreground=palette["FG"])
    style.configure(
        "Header.TLabel",
        font=("Segoe UI", 12, "bold"),
        background=palette["BG"],
        foreground=palette["ACCENT"],
    )

    # Карточки
    style.configure(
        "Card.TLabelframe",
        background=palette["PANEL"],
        foreground=palette["ACCENT"],
        bordercolor=palette["ACCENT"],
        relief="solid",
        borderwidth=1,
        padding=10,
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=palette["PANEL"],
        foreground=palette["ACCENT"],
        font=("Segoe UI", 11, "bold"),
    )

    # Кнопки
    style.configure(
        "TButton",
        background=palette["ACCENT"],
        foreground="white",
        padding=6,
        font=("Segoe UI", 10, "bold"),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("active", "#6fa4ff")],
        foreground=[("disabled", "#aaaaaa")],
    )

    # Notebook
    style.configure(
        "TNotebook",
        background=palette["BG"],
        borderwidth=0,
    )
    style.configure(
        "TNotebook.Tab",
        font=("Segoe UI", 10),
        padding=(10, 4, 10, 4),
    )

    # Фрейм логов
    style.configure("Log.TFrame", background=palette["PANEL"])


# -------------------------------------------------
# ПУТИ 
# -------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
env_path = os.path.join(BASE_DIR, "config.env")
if os.path.exists(env_path):
    load_dotenv(env_path)

CONFIG_FILE = os.path.join(BASE_DIR, "tvgizmo_settings.json")
LOG_FILE = os.path.join(BASE_DIR, "tvgizmo.log")

TVPSV2_PY = os.path.join(BASE_DIR, "tvpsv2.py")
TVPSV2_EXE = os.path.join(BASE_DIR, "tvpsv2.exe")

# Базовый API Gizmo (дефолты из .env)
API_BASE = os.getenv("API_BASE", "https://URL/api")
GIZMO_ADMIN_USERNAME = os.getenv("GIZMO_ADMIN_USERNAME", "ADMIN")
GIZMO_ADMIN_PASSWORD = os.getenv("GIZMO_ADMIN_PASSWORD", "ADMIN")

HOST_ID = int(os.getenv("GIZMO_HOST_ID", "7"))

ADB_PATH = os.getenv("ADB_PATH", ".\\adb\\adb.exe")
TV_ADB_TARGET = os.getenv("TV_ADB_TARGET", "192.168.11.166:5555")

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "5"))

VERIFY_SSL = False

admin_token: Optional[str] = None

def adb_connect(target: str, log: Optional[Callable[[str], None]] = None) -> bool:
    """Подключаемся к телеку по ADB. Возвращает True/False."""
    try:
        cmd = f'"{ADB_PATH}" connect {target}'
        if log:
            log(f"[ADB] {cmd}")
        else:
            print(f"[ADB] {cmd}")
        res = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            encoding="utf-8",
        )
        out = res.stdout.strip()
        err = res.stderr.strip()
        if log:
            log("[ADB] connect stdout: " + out)
            if err:
                log("[ADB] connect stderr: " + err)
        else:
            print("[ADB] connect stdout:", out)
            if err:
                print("[ADB] connect stderr:", err)

        if "connected" in out.lower() or "already connected" in out.lower():
            return True
        return res.returncode == 0
    except Exception as e:
        msg = f"[ADB] Ошибка при connect: {e}"
        if log:
            log(msg)
        else:
            print(msg)
        return False


def adb_power_toggle(target: str, log: Optional[Callable[[str], None]] = None) -> bool:
    """Отправляем keyevent 26 (вкл/выкл). Возвращает True/False."""
    try:
        cmd = f'"{ADB_PATH}" -s {target} shell input keyevent 26'
        if log:
            log(f"[ADB] {cmd}")
        else:
            print(f"[ADB] {cmd}")
        res = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            encoding="utf-8",
        )
        out = res.stdout.strip()
        err = res.stderr.strip()
        if log:
            log("[ADB] keyevent stdout: " + out)
            if err:
                log("[ADB] keyevent stderr: " + err)
        else:
            print("[ADB] keyevent stdout:", out)
            if err:
                print("[ADB] keyevent stderr:", err)
        return res.returncode == 0
    except Exception as e:
        msg = f"[ADB] Ошибка при отправке keyevent 26: {e}"
        if log:
            log(msg)
        else:
            print(msg)
        return False


def turn_off_tv(log: Optional[Callable[[str], None]] = None) -> None:
    """Выключение телика через ADB: connect + keyevent 26."""
    msg = "[TV] Попытка выключить телевизор через ADB..."
    if log:
        log(msg)
    else:
        print(msg)

    adb_connect(TV_ADB_TARGET, log=log)
    time.sleep(0.5)
    success = adb_power_toggle(TV_ADB_TARGET, log=log)

    if success:
        msg = "[TV] Команда выключения отправлена."
    else:
        msg = "[TV] Не удалось корректно отправить команду выключения."

    if log:
        log(msg)
    else:
        print(msg)

def login_admin_sync(log: Optional[Callable[[str], None]] = None) -> bool:
    """Логин админа Gizmo, использует глобальные API_BASE/GIZMO_ADMIN_*."""
    global admin_token, API_BASE, GIZMO_ADMIN_USERNAME, GIZMO_ADMIN_PASSWORD, VERIFY_SSL
    url = f"{API_BASE}/v2.0/auth/accesstoken"
    params = {"Username": GIZMO_ADMIN_USERNAME, "Password": GIZMO_ADMIN_PASSWORD}

    msg = (
        f"[API] Логин админа по адресу {url} (user={GIZMO_ADMIN_USERNAME}, "
        f"verify_ssl={VERIFY_SSL})..."
    )
    if log:
        log(msg)
    else:
        print(msg)

    try:
        with httpx.Client(verify=VERIFY_SSL, timeout=10.0) as client:
            r = client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                admin_token = data["result"]["token"]
                msg = "[API] ✅ Админ авторизован"
                if log:
                    log(msg)
                else:
                    print(msg)
                return True
            else:
                msg = (
                    f"[API] ❌ Не удалось авторизовать админа. "
                    f"Код: {r.status_code}, ответ: {r.text}"
                )
                if log:
                    log(msg)
                else:
                    print(msg)
                return False
    except Exception as e:
        msg = f"[API] ❌ Ошибка при авторизации админа: {e}"
        if log:
            log(msg)
        else:
            print(msg)
        return False


def get_active_sessions(log: Optional[Callable[[str], None]] = None) -> list:
    """Получение списка активных сессий /usersessions/activeinfo."""
    global admin_token, API_BASE, VERIFY_SSL
    if not admin_token:
        if not login_admin_sync(log=log):
            return []

    headers = {"Authorization": f"Bearer {admin_token}"}
    url = f"{API_BASE}/usersessions/activeinfo"

    try:
        with httpx.Client(verify=VERIFY_SSL, timeout=10.0) as client:
            r = client.get(url, headers=headers)

            if r.status_code == 401:
                msg = "[API] Токен протух, пробуем авторизоваться заново..."
                if log:
                    log(msg)
                else:
                    print(msg)

                if not login_admin_sync(log=log):
                    return []
                headers = {"Authorization": f"Bearer {admin_token}"}
                r = client.get(url, headers=headers)

            if r.status_code != 200:
                msg = (
                    f"[API] ❌ Ошибка при запросе activeinfo: "
                    f"{r.status_code}, {r.text}"
                )
                if log:
                    log(msg)
                else:
                    print(msg)
                return []
            data = r.json()
            result = data.get("result", [])
            if not isinstance(result, list):
                msg = "[API] ⚠️ result не список, сырой ответ: " + str(data)
                if log:
                    log(msg)
                else:
                    print(msg)
                return []
            return result
    except Exception as e:
        msg = f"[API] ❌ Ошибка при получении activeinfo: {e}"
        if log:
            log(msg)
        else:
            print(msg)
        return []


def get_session_for_host(
    host_id: int, log: Optional[Callable[[str], None]] = None
) -> Optional[dict]:
    """Ищем сессию для конкретного hostId."""
    sessions = get_active_sessions(log=log)
    for s in sessions:
        if s.get("hostId") == host_id:
            return s
    return None

class GizmoTVWatcher(threading.Thread):
    """Фоновый поток, который опрашивает Gizmo и управляет ТВ."""

    def __init__(
        self,
        host_id: int,
        poll_interval: int,
        log_callback: Callable[[str], None],
        state_callback: Callable[[dict], None],
        tv_off_callback: Optional[Callable[[], None]] = None,
    ):
        super().__init__(daemon=True)
        self.host_id = host_id
        self.poll_interval = poll_interval
        self.log_callback = log_callback
        self.state_callback = state_callback
        self.tv_off_callback = tv_off_callback
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def _update_state(self, **kwargs):
        if self.state_callback:
            self.state_callback(kwargs)

    def run(self):
        global API_BASE, ADB_PATH, TV_ADB_TARGET, VERIFY_SSL
        self._log("==========================================")
        self._log("  TVGIZMOADB by TeXeT_killer (GUI режим)")
        self._log("==========================================")
        self._log(f"API_BASE        : {API_BASE}")
        self._log(f"GIZMO_HOST_ID   : {self.host_id}")
        self._log(f"TV_ADB_TARGET   : {TV_ADB_TARGET}")
        self._log(f"ADB_PATH        : {ADB_PATH}")
        self._log(f"POLL_INTERVAL   : {self.poll_interval} сек")
        self._log(f"VERIFY_SSL      : {VERIFY_SSL}")
        self._log("==========================================\n")

        if not login_admin_sync(log=self._log):
            self._log(
                "[MAIN] Не удалось авторизоваться в Gizmo. "
                "Проверь URL, логин/пароль и SSL."
            )
            self._update_state(running=False, session_active=False, session=None)
            return

        last_session_active = False

        while not self._stop_event.is_set():
            session = get_session_for_host(self.host_id, log=self._log)
            is_active = session is not None

            # 🟢 Сессия появилась
            if is_active and not last_session_active:
                last_session_active = True
                self._log(
                    f"\n[MAIN] 🟢 Обнаружена новая сессия на хосте {self.host_id}"
                )
                try:
                    pretty = json.dumps(session, ensure_ascii=False, indent=2)
                    self._log("[MAIN] Данные сессии:\n" + pretty)
                except Exception:
                    self._log("[MAIN] (не удалось красиво вывести JSON)")
                self._update_state(
                    running=True, session_active=True, session=session
                )

            # 🔴 Сессия исчезла
            elif not is_active and last_session_active:
                self._log(
                    f"\n[MAIN] 🔴 Сессия на хосте {self.host_id} закончилась."
                )
                self._log("[MAIN] Отправляем команду выключения телевизора.")
                turn_off_tv(log=self._log)
                if self.tv_off_callback:
                    try:
                        self.tv_off_callback()
                    except Exception:
                        pass
                last_session_active = False
                self._update_state(
                    running=True, session_active=False, session=None
                )

            # Нет сессии и не было — обновим статус
            if not is_active and not last_session_active:
                self._update_state(
                    running=True, session_active=False, session=None
                )

            # Пауза между опросами
            for _ in range(self.poll_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        self._log("[MAIN] Остановка мониторинга.")
        self._update_state(running=False, session_active=False, session=None)


# -------------------------------------------------
# GUI
# -------------------------------------------------
class TVGizmoGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TVGIZMOADB by TeXeT_killer")
        self.root.geometry("900x600")
        self.root.minsize(780, 500)

        # текущая палитра / тема
        self.palette = DARK_PALETTE.copy()

        # профили
        self.profiles: dict = {}

        # переменные
        self.var_api = tk.StringVar(value=API_BASE)
        self.var_api_user = tk.StringVar(value=GIZMO_ADMIN_USERNAME)
        self.var_api_pass = tk.StringVar(value=GIZMO_ADMIN_PASSWORD)

        self.var_host_id = tk.StringVar(value=str(HOST_ID))
        self.var_poll = tk.StringVar(value=str(POLL_INTERVAL_SEC))
        self.var_adb_path = tk.StringVar(value=ADB_PATH)
        self.var_tv_target = tk.StringVar(value=TV_ADB_TARGET)

        self.var_status = tk.StringVar(value="Остановлено")
        self.var_session = tk.StringVar(value="Нет активной сессии")
        self.var_theme = tk.StringVar(value="Тёмная")
        self.var_diag_status = tk.StringVar(value="")
        self.var_autostart = tk.BooleanVar(value=False)
        self.var_profile = tk.StringVar(value="По умолчанию")

        # галочка "не проверять SSL"
        self.var_no_ssl_check = tk.BooleanVar(value=not VERIFY_SSL)

        self.watcher: Optional[GizmoTVWatcher] = None

        apply_custom_style(self.root, self.palette)
        self._build_ui()
        self.load_config()  # загрузим сохранённые настройки (если есть)

        # автозапуск мониторинга при старте, если включён
        if self.var_autostart.get():
            self.start_watcher()

    # ---- конфиг GUI / профили ----
    def _update_profile_combobox(self):
        names = list(self.profiles.keys())
        self.combo_profile["values"] = names

    def apply_profile_settings(self, prof: dict):
        self.var_api.set(prof.get("api_base", self.var_api.get()))
        self.var_api_user.set(prof.get("api_user", self.var_api_user.get()))
        self.var_api_pass.set(prof.get("api_password", self.var_api_pass.get()))

        self.var_host_id.set(str(prof.get("host_id", self.var_host_id.get())))
        self.var_poll.set(str(prof.get("poll_interval", self.var_poll.get())))
        self.var_adb_path.set(prof.get("adb_path", self.var_adb_path.get()))
        self.var_tv_target.set(prof.get("tv_target", self.var_tv_target.get()))
        self.var_autostart.set(bool(prof.get("autostart", False)))

        verify_ssl = prof.get("verify_ssl", False)
        self.var_no_ssl_check.set(not verify_ssl)

        theme_mode = prof.get("theme", "dark")
        if theme_mode == "light":
            self.var_theme.set("Светлая")
            self.apply_theme("light")
        else:
            self.var_theme.set("Тёмная")
            self.apply_theme("dark")

    def load_config(self):
        """Загрузить настройки GUI из JSON (если есть)."""
        if not os.path.exists(CONFIG_FILE):
            # если файла нет — создаём дефолтный профиль из текущих значений
            self.profiles = {
                "По умолчанию": self._collect_current_profile_data()
            }
            self.var_profile.set("По умолчанию")
            self._update_profile_combobox()
            return

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            self._append_log(f"[CONFIG] Ошибка чтения {CONFIG_FILE}: {e}")
            return

        profiles = cfg.get("profiles")
        active_profile = cfg.get("active_profile", "По умолчанию")

        if isinstance(profiles, dict) and profiles:
            self.profiles = profiles
            if active_profile not in self.profiles:
                active_profile = list(self.profiles.keys())[0]
            self.var_profile.set(active_profile)
            self._update_profile_combobox()
            self.apply_profile_settings(self.profiles[active_profile])
        else:
            # старый формат: плоские ключи
            prof = {
                "api_base": cfg.get("api_base", self.var_api.get()),
                "api_user": cfg.get("api_user", self.var_api_user.get()),
                "api_password": cfg.get("api_password", self.var_api_pass.get()),
                "host_id": cfg.get("host_id", self.var_host_id.get()),
                "poll_interval": cfg.get("poll_interval", self.var_poll.get()),
                "adb_path": cfg.get("adb_path", self.var_adb_path.get()),
                "tv_target": cfg.get("tv_target", self.var_tv_target.get()),
                "theme": cfg.get("theme", "dark"),
                "autostart": cfg.get("autostart", False),
                "verify_ssl": cfg.get("verify_ssl", False),
            }
            self.profiles = {"По умолчанию": prof}
            self.var_profile.set("По умолчанию")
            self._update_profile_combobox()
            self.apply_profile_settings(prof)

        self._append_log(f"[CONFIG] Настройки загружены из {CONFIG_FILE}")

    def _collect_current_profile_data(self) -> dict:
        return {
            "api_base": self.var_api.get(),
            "api_user": self.var_api_user.get(),
            "api_password": self.var_api_pass.get(),
            "host_id": self.var_host_id.get(),
            "poll_interval": self.var_poll.get(),
            "adb_path": self.var_adb_path.get(),
            "tv_target": self.var_tv_target.get(),
            "theme": "dark" if self.var_theme.get() == "Тёмная" else "light",
            "autostart": bool(self.var_autostart.get()),
            "verify_ssl": not self.var_no_ssl_check.get(),
        }

    def save_config(self):
        """Сохранить настройки GUI в JSON."""
        profile_name = self.var_profile.get().strip() or "По умолчанию"
        self.profiles[profile_name] = self._collect_current_profile_data()

        active = self.profiles[profile_name]
        data = {
            "active_profile": profile_name,
            "profiles": self.profiles,
            # плоские поля для совместимости с tvpsv2.py
            "api_base": active.get("api_base"),
            "api_user": active.get("api_user"),
            "api_password": active.get("api_password"),
            "host_id": active.get("host_id"),
            "poll_interval": active.get("poll_interval"),
            "adb_path": active.get("adb_path"),
            "tv_target": active.get("tv_target"),
            "theme": active.get("theme"),
            "autostart": active.get("autostart"),
            "verify_ssl": active.get("verify_ssl"),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._append_log(f"[CONFIG] Настройки сохранены в {CONFIG_FILE}")
        except Exception as e:
            self._append_log(f"[CONFIG] Ошибка сохранения {CONFIG_FILE}: {e}")

    # ---- смена темы ----
    def apply_theme(self, mode: str):
        if mode == "light":
            self.palette = LIGHT_PALETTE.copy()
        else:
            self.palette = DARK_PALETTE.copy()

        apply_custom_style(self.root, self.palette)

        self.root.configure(bg=self.palette["BG"])
        if hasattr(self, "status_canvas"):
            self.status_canvas.configure(bg=self.palette["BG"])
        if hasattr(self, "text_log"):
            self.text_log.configure(
                bg=self.palette["LOG_BG"],
                fg=self.palette["LOG_FG"],
                insertbackground=self.palette["FG"],
            )

    # ---- построение UI ----
    def _build_ui(self):
        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        tab_monitor = ttk.Frame(self.notebook)
        tab_diag = ttk.Frame(self.notebook)

        self.notebook.add(tab_monitor, text="Мониторинг")
        self.notebook.add(tab_diag, text="Диагностика")

        # ---------- вкладка Мониторинг ----------
        top = ttk.LabelFrame(
            tab_monitor,
            text="Настройки подключения к API и ADB",
            style="Card.TLabelframe",
        )
        top.pack(fill="x", padx=10, pady=10)

        # API base
        ttk.Label(top, text="API base:", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        entry_api = ttk.Entry(
            top, textvariable=self.var_api, width=50
        )
        entry_api.grid(
            row=0, column=1, columnspan=3, sticky="we", padx=(6, 0), pady=(0, 6)
        )

        # Тема
        ttk.Label(top, text="Тема:").grid(row=0, column=4, sticky="e", padx=(10, 4))
        self.combo_theme = ttk.Combobox(
            top,
            values=["Тёмная", "Светлая"],
            width=10,
            state="readonly",
            textvariable=self.var_theme,
        )
        self.combo_theme.grid(row=0, column=5, sticky="e")
        self.combo_theme.bind("<<ComboboxSelected>>", self.on_theme_change)

        # Host ID
        ttk.Label(top, text="Gizmo Host ID:").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Entry(top, textvariable=self.var_host_id, width=8).grid(
            row=1, column=1, sticky="w", pady=(4, 0), padx=(6, 20)
        )

        # Poll interval
        ttk.Label(top, text="Интервал опроса (сек):").grid(
            row=1, column=2, sticky="w", pady=(4, 0)
        )
        ttk.Entry(top, textvariable=self.var_poll, width=8).grid(
            row=1, column=3, sticky="w", pady=(4, 0), padx=(6, 0)
        )

        # Профили
        ttk.Label(top, text="Профиль:").grid(
            row=1, column=4, sticky="e", padx=(10, 4)
        )
        self.combo_profile = ttk.Combobox(
            top,
            width=14,
            textvariable=self.var_profile,
        )
        self.combo_profile.grid(row=1, column=5, sticky="e")
        self.combo_profile.bind("<<ComboboxSelected>>", self.on_profile_selected)

        # ADB path
        ttk.Label(top, text="ADB path (exe):").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Entry(top, textvariable=self.var_adb_path, width=30).grid(
            row=2, column=1, sticky="we", pady=(6, 0), padx=(6, 20)
        )

        # TV target
        ttk.Label(top, text="TV ADB target (IP:PORT):").grid(
            row=2, column=2, sticky="w", pady=(6, 0)
        )
        ttk.Entry(top, textvariable=self.var_tv_target, width=18).grid(
            row=2, column=3, sticky="w", pady=(6, 0), padx=(6, 0)
        )

        # Логин/пароль админа API
        ttk.Label(top, text="API логин:").grid(
            row=3, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Entry(top, textvariable=self.var_api_user, width=18).grid(
            row=3, column=1, sticky="w", pady=(6, 0), padx=(6, 20)
        )

        ttk.Label(top, text="API пароль:").grid(
            row=3, column=2, sticky="w", pady=(6, 0)
        )
        ttk.Entry(top, textvariable=self.var_api_pass, width=18, show="*").grid(
            row=3, column=3, sticky="w", pady=(6, 0), padx=(6, 0)
        )

        # Галочка "не проверять SSL"
        chk_ssl = ttk.Checkbutton(
            top,
            text="Не проверять SSL (доверять self-signed сертификату)",
            variable=self.var_no_ssl_check,
            command=self.save_config,
        )
        chk_ssl.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # Кнопки управления профилями
        btn_save_prof = ttk.Button(
            top, text="Сохранить профиль", command=self.save_profile
        )
        btn_save_prof.grid(row=4, column=4, sticky="we", padx=(10, 4), pady=(6, 0))

        btn_del_prof = ttk.Button(
            top, text="Удалить профиль", command=self.delete_profile
        )
        btn_del_prof.grid(row=4, column=5, sticky="we", pady=(6, 0))

        for i in range(6):
            top.columnconfigure(i, weight=1)

        # Блок управления
        ctrl = ttk.LabelFrame(
            tab_monitor,
            text="Управление",
            style="Card.TLabelframe",
        )
        ctrl.pack(fill="x", padx=10, pady=(0, 10))

        btn_start = ttk.Button(
            ctrl, text="▶ Старт мониторинга", command=self.start_watcher
        )
        btn_start.grid(row=0, column=0, padx=5, pady=(0, 4))

        btn_stop = ttk.Button(ctrl, text="⏹ Стоп", command=self.stop_watcher)
        btn_stop.grid(row=0, column=1, padx=5, pady=(0, 4))

        btn_off_now = ttk.Button(
            ctrl,
            text="⏻ Выключить ТВ сейчас",
            command=self.turn_off_now,
        )
        btn_off_now.grid(row=0, column=2, padx=5, pady=(0, 4))

        # Статус и индикатор
        ttk.Label(ctrl, text="Статус:", style="Header.TLabel").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Label(ctrl, textvariable=self.var_status).grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )

        self.status_canvas = tk.Canvas(
            ctrl,
            width=18,
            height=18,
            bg=self.palette["BG"],
            highlightthickness=0,
            bd=0,
        )
        self.status_canvas.grid(row=1, column=2, sticky="w", padx=(6, 0))
        self.status_dot = self.status_canvas.create_oval(
            3, 3, 15, 15, fill="gray", outline=""
        )

        ttk.Label(ctrl, text="Сессия:", style="Header.TLabel").grid(
            row=2, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(ctrl, textvariable=self.var_session, wraplength=420).grid(
            row=2, column=1, columnspan=2, sticky="w", pady=(4, 0)
        )

        # Автозапуск
        chk_autostart = ttk.Checkbutton(
            ctrl,
            text="Автоматически запускать мониторинг при старте программы",
            variable=self.var_autostart,
            command=self.save_config,
        )
        chk_autostart.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # Логи
        log_frame = ttk.LabelFrame(
            tab_monitor,
            text="Лог",
            style="Card.TLabelframe",
        )
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_wrap = ttk.Frame(log_frame, style="Log.TFrame")
        log_wrap.pack(fill="both", expand=True)

        self.text_log = ScrolledText(
            log_wrap,
            height=18,
            wrap="word",
            font=("Consolas", 10),
            bg=self.palette["LOG_BG"],
            fg=self.palette["LOG_FG"],
            insertbackground=self.palette["FG"],
            borderwidth=0,
        )
        self.text_log.pack(fill="both", expand=True)
        self.text_log.configure(state="disabled")

        self._append_log(
            "Готово. Настрой профиль и параметры, при необходимости включи автозапуск."
        )

        # ---------- вкладка Диагностика ----------
        diag_frame = ttk.LabelFrame(
            tab_diag,
            text="Быстрая диагностика",
            style="Card.TLabelframe",
        )
        diag_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(
            diag_frame,
            text=(
                "Здесь можно проверить доступность API Gizmo и подключение ADB.\n"
                "Также можно запустить GUI управления ТВ (tvpsv2)."
            ),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        btn_test_api = ttk.Button(
            diag_frame,
            text="Проверить API Gizmo",
            command=self.test_api,
        )
        btn_test_api.grid(row=1, column=0, padx=5, pady=4, sticky="w")

        btn_test_adb = ttk.Button(
            diag_frame,
            text="Проверить ADB подключение",
            command=self.test_adb,
        )
        btn_test_adb.grid(row=1, column=1, padx=5, pady=4, sticky="w")

        btn_open_tv = ttk.Button(
            diag_frame,
            text="Открыть TV GUI (tvpsv2)",
            command=self.open_tvpsv2,
        )
        btn_open_tv.grid(row=1, column=2, padx=5, pady=4, sticky="w")

        ttk.Label(diag_frame, text="Статус проверки:", style="Header.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Label(diag_frame, textvariable=self.var_diag_status, wraplength=500).grid(
            row=2, column=1, columnspan=2, sticky="w", pady=(10, 0)
        )

        for i in range(3):
            diag_frame.columnconfigure(i, weight=1)

    # ---- логирование ----
    def _append_log(self, msg: str):
        # Записываем в файл
        ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts_full}] {msg}\n"
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

        # Показываем в GUI (только время)
        ts = ts_full.split(" ")[1]
        self.text_log.configure(state="normal")
        self.text_log.insert("end", f"[{ts}] {msg}\n")
        self.text_log.see("end")
        self.text_log.configure(state="disabled")

    def _log_from_thread(self, msg: str):
        self.root.after(0, lambda m=msg: self._append_log(m))

    # ---- статус ----
    def _set_status_color(self, running: bool, active: bool):
        if not running:
            color = self.palette["ERR"]
        elif running and active:
            color = self.palette["OK"]
        elif running and not active:
            color = self.palette["WARN"]
        else:
            color = "gray"
        self.status_canvas.itemconfig(self.status_dot, fill=color)

    def _state_from_thread(self, data: dict):
        running = data.get("running", False)
        session_active = data.get("session_active", False)
        session = data.get("session")

        if not running:
            status = "Остановлено"
        else:
            status = "Работает"

        if session_active:
            sess_text = "Активная сессия обнаружена"
            if session and "id" in session:
                sess_text += f" (ID={session.get('id')})"
        else:
            sess_text = "Нет активной сессии"

        self.var_status.set(status)
        self.var_session.set(sess_text)
        self._set_status_color(running, session_active)

    # ---- уведомления о выключении ТВ ----
    def _on_tv_turned_off_auto(self):
        self._append_log("[TV] Телевизор выключен по окончании сессии.")
        mb.showinfo("TV Gizmo", "Телевизор выключен по окончании сессии.")

    def _on_tv_turned_off_manual(self):
        self._append_log("[TV] Телевизор выключен по ручной команде.")
        mb.showinfo("TV Gizmo", "Телевизор выключен по ручной команде.")

    # ---- обработчики ----
    def start_watcher(self):
        if self.watcher and self.watcher.is_alive():
            self._append_log("Мониторинг уже запущен.")
            return

        global HOST_ID, POLL_INTERVAL_SEC, ADB_PATH, TV_ADB_TARGET
        global API_BASE, GIZMO_ADMIN_USERNAME, GIZMO_ADMIN_PASSWORD, VERIFY_SSL

        try:
            host_id = int(self.var_host_id.get())
        except ValueError:
            msg = "Некорректный Host ID (должно быть число)."
            self._append_log("❌ " + msg)
            mb.showerror("Ошибка", msg)
            return

        try:
            poll = int(self.var_poll.get())
            if poll <= 0:
                raise ValueError
        except ValueError:
            msg = "Некорректный интервал опроса (должно быть положительное число)."
            self._append_log("❌ " + msg)
            mb.showerror("Ошибка", msg)
            return

        api_base = self.var_api.get().strip()
        if not api_base:
            msg = "API base URL не может быть пустым."
            self._append_log("❌ " + msg)
            mb.showerror("Ошибка", msg)
            return

        HOST_ID = host_id
        POLL_INTERVAL_SEC = poll
        API_BASE = api_base
        GIZMO_ADMIN_USERNAME = self.var_api_user.get().strip() or GIZMO_ADMIN_USERNAME
        GIZMO_ADMIN_PASSWORD = self.var_api_pass.get().strip() or GIZMO_ADMIN_PASSWORD
        ADB_PATH = self.var_adb_path.get().strip() or ADB_PATH
        TV_ADB_TARGET = self.var_tv_target.get().strip() or TV_ADB_TARGET
        VERIFY_SSL = not self.var_no_ssl_check.get()

        admin_token = None  # сброс токена при смене настроек
        self.save_config()

        self._append_log(
            f"Запуск мониторинга... (verify_ssl={VERIFY_SSL}, api={API_BASE})"
        )
        self.var_status.set("Запуск...")

        self.watcher = GizmoTVWatcher(
            host_id=HOST_ID,
            poll_interval=POLL_INTERVAL_SEC,
            log_callback=self._log_from_thread,
            state_callback=lambda d: self.root.after(
                0, self._state_from_thread, d
            ),
            tv_off_callback=lambda: self.root.after(
                0, self._on_tv_turned_off_auto
            ),
        )
        self.watcher.start()

    def stop_watcher(self):
        if self.watcher and self.watcher.is_alive():
            self._append_log("Останавливаем мониторинг...")
            self.watcher.stop()
        else:
            self._append_log("Мониторинг уже остановлен.")
        self._set_status_color(False, False)
        self.save_config()

    def turn_off_now(self):
        self._append_log("Ручное выключение ТВ через ADB...")

        def worker():
            turn_off_tv(log=self._log_from_thread)
            self.root.after(0, self._on_tv_turned_off_manual)

        threading.Thread(target=worker, daemon=True).start()

    # ---- диагностика ----
    def test_api(self):
        """Проверка доступности API Gizmo."""
        self._append_log("[ТЕСТ] Проверка API Gizmo...")
        self.var_diag_status.set("Проверка API Gizmo...")

        def worker():
            global API_BASE, GIZMO_ADMIN_USERNAME, GIZMO_ADMIN_PASSWORD, VERIFY_SSL
            API_BASE = self.var_api.get().strip() or API_BASE
            GIZMO_ADMIN_USERNAME = self.var_api_user.get().strip() or GIZMO_ADMIN_USERNAME
            GIZMO_ADMIN_PASSWORD = self.var_api_pass.get().strip() or GIZMO_ADMIN_PASSWORD
            VERIFY_SSL = not self.var_no_ssl_check.get()

            ok = login_admin_sync(log=self._log_from_thread)
            if ok:
                msg = "✅ API Gizmo доступен, авторизация прошла успешно."
                self._log_from_thread("[ТЕСТ] " + msg)
                self.root.after(0, lambda: self.var_diag_status.set(msg))
            else:
                msg = "❌ Не удалось авторизоваться в API Gizmo."
                self._log_from_thread("[ТЕСТ] " + msg)

                def show():
                    self.var_diag_status.set(msg)
                    mb.showerror("Проверка API Gizmo", msg)

                self.root.after(0, show)

        threading.Thread(target=worker, daemon=True).start()

    def test_adb(self):
        """Проверка ADB подключения."""
        self._append_log("[ТЕСТ] Проверка ADB подключения...")
        self.var_diag_status.set("Проверка ADB подключения...")

        global ADB_PATH, TV_ADB_TARGET
        ADB_PATH = self.var_adb_path.get().strip() or ADB_PATH
        TV_ADB_TARGET = self.var_tv_target.get().strip() or TV_ADB_TARGET

        self.save_config()

        def worker():
            ok = adb_connect(TV_ADB_TARGET, log=self._log_from_thread)
            if ok:
                msg = f"✅ ADB подключение успешно ({TV_ADB_TARGET})."
                self._log_from_thread("[ТЕСТ] " + msg)
                self.root.after(0, lambda: self.var_diag_status.set(msg))
            else:
                msg = f"❌ Не удалось подключиться к ADB ({TV_ADB_TARGET})."
                self._log_from_thread("[ТЕСТ] " + msg)

                def show():
                    self.var_diag_status.set(msg)
                    mb.showerror("Проверка ADB", msg)

                self.root.after(0, show)

        threading.Thread(target=worker, daemon=True).start()

    def open_tvpsv2(self):
        """Запуск внешнего GUI tvpsv2 (exe или py)."""
        if os.path.exists(TVPSV2_EXE):
            self._append_log("[TVPSV2] Запуск tvpsv2.exe...")
            try:
                subprocess.Popen([TVPSV2_EXE])
            except Exception as e:
                msg = f"Ошибка запуска tvpsv2.exe: {e}"
                self._append_log("[TVPSV2] " + msg)
                mb.showerror("tvpsv2.exe", msg)
            return

        if not os.path.exists(TVPSV2_PY):
            msg = "Файл tvpsv2.py не найден рядом с tvgizmoadb."
            self._append_log("[TVPSV2] " + msg)
            mb.showerror("tvpsv2", msg)
            return

        self._append_log("[TVPSV2] Запуск tvpsv2.py...")
        try:
            subprocess.Popen([sys.executable, TVPSV2_PY])
        except Exception as e:
            msg = f"Ошибка запуска tvpsv2.py: {e}"
            self._append_log("[TVPSV2] " + msg)
            mb.showerror("tvpsv2.py", msg)

    # ---- смена темы / профиля ----
    def on_theme_change(self, event=None):
        value = self.var_theme.get()
        mode = "dark" if value == "Тёмная" else "light"
        self.apply_theme(mode)
        running = self.var_status.get() == "Работает"
        active = "Активная сессия" in self.var_session.get()
        self._set_status_color(running, active)
        self.save_config()

    def on_profile_selected(self, event=None):
        name = self.var_profile.get().strip()
        if name in self.profiles:
            self.apply_profile_settings(self.profiles[name])

    def save_profile(self):
        name = self.var_profile.get().strip()
        if not name:
            mb.showerror("Профиль", "Имя профиля не может быть пустым.")
            return
        self.profiles[name] = self._collect_current_profile_data()
        self._update_profile_combobox()
        self.var_profile.set(name)
        self.save_config()
        self._append_log(f"[PROFILE] Профиль «{name}» сохранён.")

    def delete_profile(self):
        name = self.var_profile.get().strip()
        if not name or name not in self.profiles:
            return
        if len(self.profiles) == 1:
            mb.showwarning("Профиль", "Нельзя удалить последний профиль.")
            return
        if not mb.askyesno(
            "Удалить профиль",
            f"Удалить профиль «{name}»?",
        ):
            return
        del self.profiles[name]
        self._update_profile_combobox()
        new_name = list(self.profiles.keys())[0]
        self.var_profile.set(new_name)
        self.apply_profile_settings(self.profiles[new_name])
        self.save_config()
        self._append_log(f"[PROFILE] Профиль «{name}» удалён.")

    # ---- закрытие окна ----
    def on_close(self):
        self.save_config()
        if self.watcher and self.watcher.is_alive():
            self.watcher.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TVGizmoGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
