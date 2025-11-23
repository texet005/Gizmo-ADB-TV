import tkinter as tk
from tkinter import ttk
import threading
import time
import subprocess
import os
import sys
import json
from ppadb.client import Client

BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
SETTINGS_FILE = os.path.join(BASE_DIR, "tvgizmo_settings.json")


def load_shared_config():
    """
    Загружаем настройки из tvgizmo_settings.json.
    Поддерживает новый формат (profiles + active_profile) и старый плоский.
    Возвращает словарь с ключами:
      - tv_target
      - adb_path
    """
    cfg = {}
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
    except Exception:
        cfg = {}

    result = {"tv_target": "", "adb_path": None}

    # Пытаемся взять из корневых полей (совместимость)
    if isinstance(cfg, dict):
        if "tv_target" in cfg:
            result["tv_target"] = str(cfg.get("tv_target") or "")
        if "adb_path" in cfg:
            result["adb_path"] = cfg.get("adb_path")

        # Новый формат с профилями
        profiles = cfg.get("profiles")
        if isinstance(profiles, dict) and profiles:
            active_name = cfg.get("active_profile")
            prof = None
            if active_name and active_name in profiles:
                prof = profiles[active_name]
            else:
                # берём первый попавшийся профиль
                prof = profiles[list(profiles.keys())[0]]

            if prof:
                if not result["tv_target"]:
                    result["tv_target"] = str(prof.get("tv_target") or "")
                if not result["adb_path"]:
                    result["adb_path"] = prof.get("adb_path")

    return result


SHARED_CONFIG = load_shared_config()
DEFAULT_IP = SHARED_CONFIG.get("tv_target") or ""
ADB_EXE_PATH = SHARED_CONFIG.get("adb_path") or "adb"

# Настройка ADB client (как в твоём оригинале)
adb_client = Client(host="127.0.0.1", port=5037)


def ensure_adb_server():
    """Пробуем запустить adb start-server тем же adb, что и в tvgizmoadb."""
    try:
        subprocess.run(
            [ADB_EXE_PATH, "start-server"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except Exception:
        pass

def parse_hh_mm_to_seconds(text):
    """Парсит строки HH:MM или H:MM -> секунды. Возвращает None при ошибке."""
    try:
        parts = text.strip().split(":")
        if len(parts) != 2:
            return None
        h = int(parts[0])
        m = int(parts[1])
        if h < 0 or m < 0 or m >= 60:
            return None
        return h * 3600 + m * 60
    except Exception:
        return None


def format_seconds_to_hh_mm_ss(sec):
    """Форматирует секунды в строку HH:MM:SS."""
    try:
        sec = int(sec)
    except Exception:
        sec = 0
    sec = max(0, int(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class TVControlPanel:
    def __init__(self, parent, index, default_ip=""):
        self.parent = parent
        self.index = index
        self.device_ip = default_ip or ""  # "192.168.x.x:5555"
        self.device = None
        self.connected = False

        # Timer state
        self.countdown_seconds = 0
        self.timer_running = False
        self.timer_mode = None  # 'countdown' или 'countup' или None
        self._timer_thread = None
        self._timer_lock = threading.Lock()
        self._countup_start_time = 0  # timestamp, когда стартовал countup

        # Price state (для открытого времени)
        self.price_per_hour = 0.0
        self.current_cost = 0.0

        # UI
        self.frame = ttk.LabelFrame(parent, text=f"ТВ {index+1}", padding=(12, 12))
        self.frame.grid(row=0, column=index, padx=10, pady=10, sticky="n")

        # Название панели
        self.entry_name = ttk.Entry(self.frame, width=20)
        self.entry_name.insert(0, f"TV {index+1}")
        self.entry_name.grid(row=0, column=0, columnspan=2, pady=(0, 6))
        self.entry_name.bind("<FocusOut>", lambda e: self._update_frame_title())

        # IP:PORT
        ttk.Label(self.frame, text="IP:PORT").grid(row=1, column=0, sticky="w")
        self.entry_ip = ttk.Entry(self.frame, width=18)
        if self.device_ip:
            self.entry_ip.insert(0, self.device_ip)
        self.entry_ip.grid(row=1, column=1, sticky="e", padx=(4, 0))

        # Connect button and status
        self.btn_connect = ttk.Button(
            self.frame, text="Connect", command=self._connect_command
        )
        self.btn_connect.grid(row=2, column=0, pady=6, sticky="we", columnspan=1)
        self.label_status = ttk.Label(
            self.frame, text="OFFLINE", anchor="center", width=12
        )
        self.label_status.grid(row=2, column=1, pady=6, sticky="e")

        # Countdown label
        self.label_timer = tk.Label(
            self.frame, text="00:00:00", font=("Arial", 14, "bold")
        )
        self.label_timer.grid(row=3, column=0, columnspan=2, pady=(6, 8))

        # Ввод времени HH:MM и кнопка Принять (обратный отсчёт)
        ttk.Label(self.frame, text="Установить (HH:MM)").grid(
            row=4, column=0, sticky="w"
        )
        self.entry_set_time = ttk.Entry(self.frame, width=10)
        self.entry_set_time.insert(0, "00:30")
        self.entry_set_time.grid(row=4, column=1, sticky="e")
        self.btn_accept_time = ttk.Button(
            self.frame, text="Принять", command=self._accept_time
        )
        self.btn_accept_time.grid(
            row=5, column=0, columnspan=2, pady=6, sticky="we"
        )

        # Добавить время к оставшемуся
        ttk.Label(self.frame, text="Добавить (HH:MM)").grid(
            row=6, column=0, sticky="w"
        )
        self.entry_add_time = ttk.Entry(self.frame, width=10)
        self.entry_add_time.insert(0, "00:00")
        self.entry_add_time.grid(row=6, column=1, sticky="e")
        self.btn_add_time = ttk.Button(
            self.frame, text="Добавить", command=self._add_time
        )
        self.btn_add_time.grid(
            row=7, column=0, columnspan=2, pady=6, sticky="we"
        )

        # Сброс таймера
        self.btn_reset = ttk.Button(
            self.frame, text="Сброс", command=self._reset_timer
        )
        self.btn_reset.grid(
            row=8, column=0, columnspan=2, pady=(2, 8), sticky="we"
        )

        # Открытое время + цена
        self.btn_open_time = ttk.Button(
            self.frame, text="Открытое время", command=self._start_open_time
        )
        self.btn_open_time.grid(
            row=9, column=0, columnspan=2, sticky="we", pady=(2, 4)
        )

        # Цена и отображение суммы
        ttk.Label(self.frame, text="Цена/час").grid(row=10, column=0, sticky="w")
        self.entry_price = ttk.Entry(self.frame, width=10)
        self.entry_price.insert(0, "0")
        self.entry_price.grid(row=10, column=1, sticky="e")

        ttk.Label(self.frame, text="Текущая сумма").grid(
            row=11, column=0, sticky="w"
        )
        self.label_cost = ttk.Label(self.frame, text="0.00", anchor="e")
        self.label_cost.grid(row=11, column=1, sticky="e")

        # Кнопка вкл/выкл
        self.btn_toggle = ttk.Button(
            self.frame, text="Выкл / Вкл", command=self._toggle_power
        )
        self.btn_toggle.grid(
            row=12, column=0, columnspan=2, pady=(10, 0), sticky="we"
        )

        # Начальный статус
        self._update_status_label("OFFLINE")

    # UI helpers
    def _update_frame_title(self):
        name = self.entry_name.get().strip()
        if name:
            self.frame.config(text=name)

    def _update_status_label(self, status_text):
        self.label_status.config(text=status_text)
        if status_text == "ONLINE":
            self.label_status.config(foreground="green")
        else:
            self.label_status.config(foreground="red")

    # ADB connect command (в отдельном потоке)
    def _connect_command(self):
        ip_text = self.entry_ip.get().strip()
        if not ip_text:
            self._update_status_label("OFFLINE")
            return

        self.device_ip = ip_text

        def worker():
            try:
                # Используем тот же adb, что и в tvgizmoadb (ADB_EXE_PATH)
                cmd = [ADB_EXE_PATH, "connect", self.device_ip]
                try:
                    subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=5,
                    )
                except Exception:
                    pass

                devices = adb_client.devices()
                dev = None
                for d in devices:
                    if d.serial == self.device_ip:
                        dev = d
                        break
                if dev is None:
                    self.connected = False
                    self.device = None
                    self._update_status_label("OFFLINE")
                else:
                    self.connected = True
                    self.device = dev
                    self._update_status_label("ONLINE")
            except Exception:
                self.connected = False
                self.device = None
                self._update_status_label("OFFLINE")

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_power(self):
        if not self.connected or self.device is None:
            self._update_status_label("OFFLINE")
            return

        def worker():
            try:
                self.device.shell("input keyevent 26")
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _flash_error(self, widget):
        orig_bg = widget.cget("background")
        try:
            widget.configure(background="#ffcccc")
            widget.after(300, lambda: widget.configure(background=orig_bg))
        except Exception:
            pass

    # Управление таймером
    def _accept_time(self):
        s = parse_hh_mm_to_seconds(self.entry_set_time.get())
        if s is None:
            self._flash_error(self.entry_set_time)
            return
        with self._timer_lock:
            self.countdown_seconds = s
            self.timer_mode = "countdown"
            if not self.timer_running:
                self.timer_running = True
                self._start_timer_thread()

    def _add_time(self):
        s = parse_hh_mm_to_seconds(self.entry_add_time.get())
        if s is None:
            self._flash_error(self.entry_add_time)
            return
        with self._timer_lock:
            if self.timer_mode == "countdown" or self.timer_running:
                self.countdown_seconds += s
            else:
                self.countdown_seconds += s
                self.timer_mode = "countdown"
                self.timer_running = True
                self._start_timer_thread()

    def _reset_timer(self):
        with self._timer_lock:
            self.countdown_seconds = 0
            self.timer_running = False
            self.timer_mode = None
            self.current_cost = 0.0
        self.label_timer.config(text="00:00:00")
        self.label_cost.config(text="0.00")

    def _start_open_time(self):
        try:
            price = float(self.entry_price.get().replace(",", "."))
        except Exception:
            price = 0.0
        with self._timer_lock:
            self.price_per_hour = max(0.0, price)
            self.timer_mode = "countup"
            if not self.timer_running:
                self.timer_running = True
                self._countup_start_time = time.time()
                self.current_cost = 0.0
                self._start_timer_thread()

    def _start_timer_thread(self):
        if self._timer_thread and self._timer_thread.is_alive():
            return

        def run():
            while True:
                with self._timer_lock:
                    if not self.timer_running:
                        break
                    mode = self.timer_mode
                    if mode == "countdown":
                        self.countdown_seconds -= 1
                        if self.countdown_seconds <= 0:
                            self.countdown_seconds = 0
                            self.timer_running = False
                            try:
                                self._toggle_power()
                            except Exception:
                                pass
                        value = self.countdown_seconds
                        text = format_seconds_to_hh_mm_ss(value)
                    elif mode == "countup":
                        elapsed = time.time() - self._countup_start_time
                        value = int(elapsed)
                        text = format_seconds_to_hh_mm_ss(value)
                        if self.price_per_hour > 0:
                            self.current_cost = (
                                elapsed / 3600.0
                            ) * self.price_per_hour
                        else:
                            self.current_cost = 0.0
                    else:
                        value = 0
                        text = "00:00:00"

                def update_ui():
                    self.label_timer.config(text=text)
                    if mode == "countup":
                        self.label_cost.config(text=f"{self.current_cost:.2f}")

                try:
                    self.frame.after(0, update_ui)
                except Exception:
                    pass

                time.sleep(1)

        self._timer_thread = threading.Thread(target=run, daemon=True)
        self._timer_thread.start()


class TVApp:
    def __init__(self, root):
        self.root = root
        root.title("Управление ТВ — ADB Таймеры")

        # Стили (мягкие кнопки через padding и font)
        style = ttk.Style()
        style.configure("TButton", padding=8, font=("Arial", 10, "bold"))
        style.configure("TLabel", font=("Arial", 10))
        style.configure("TEntry", padding=4)

        # Ввод количества колонок
        top_frame = ttk.Frame(root, padding=10)
        top_frame.grid(row=0, column=0, sticky="we")
        ttk.Label(top_frame, text="Количество колонок:").grid(
            row=0, column=0, sticky="w"
        )
        self.entry_cols = ttk.Entry(top_frame, width=6)
        self.entry_cols.insert(0, "3")
        self.entry_cols.grid(row=0, column=1, sticky="w", padx=(6, 10))
        self.btn_set_cols = ttk.Button(
            top_frame, text="Создать", command=self._create_columns
        )
        self.btn_set_cols.grid(row=0, column=2, sticky="w")

        # Фрейм для панелей
        self.panels_frame = ttk.Frame(root, padding=6)
        self.panels_frame.grid(row=1, column=0, sticky="n")

        self.panels = []

    def _create_columns(self):
        # Удаляем старые панели
        for p in self.panels:
            try:
                p.frame.destroy()
            except Exception:
                pass
        self.panels = []

        # Определяем количество колонок
        val = self.entry_cols.get().strip()
        if not val:
            n = 3
        else:
            try:
                n = int(self.entry_cols.get())
            except Exception:
                n = 3

        n = max(1, min(8, n))  # чтобы интерфейс не ломался

        for i in range(n):
            panel = TVControlPanel(self.panels_frame, i, default_ip=DEFAULT_IP)
            self.panels.append(panel)


def main():
    ensure_adb_server()
    root = tk.Tk()
    app = TVApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
