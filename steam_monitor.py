import os
import time
import re
import winreg
import psutil
import threading
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

class SteamDownloadMonitor:
    def __init__(self):
        self.steam_path = self._get_steam_path()
        self.running = False
        self.current_game = "Неизвестно"
        self.download_status = "Неизвестно"
        self.download_speed = 0
        self.steam_processes = []
        self.log_path = os.path.join(self.steam_path, "logs", "content_log.txt")

    def _get_steam_path(self):
        try:
            hkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\Valve\\Steam")
            steam_path = winreg.QueryValueEx(hkey, "SteamPath")[0]
            winreg.CloseKey(hkey)
            logging.info(f"Найден путь Steam в реестре: {steam_path}")
            return steam_path
        except Exception as e:
            logging.warning(f"Ошибка получения пути Steam из реестра: {e}")
            for path in ["C:\\Program Files (x86)\\Steam", "C:\\Program Files\\Steam"]:
                if os.path.exists(path):
                    logging.info(f"Найден Steam в стандартном расположении: {path}")
                    return path
            logging.warning("Используется путь Steam по умолчанию")
            return "C:\\Program Files (x86)\\Steam"

    def _find_steam_processes(self):
        self.steam_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                proc_name = proc.info['name'].lower() if proc.info['name'] else ""
                proc_exe = proc.info['exe'].lower() if proc.info.get('exe') else ""

                if 'steam' in proc_name or 'steam' in proc_exe:
                    self.steam_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if not self.steam_processes:
            logging.warning("Процессы Steam не найдены")

    def _monitor_network_usage(self):
        if not self.steam_processes:
            self._find_steam_processes()
            if not self.steam_processes:
                self.download_status = "Steam не запущен"
                self.download_speed = 0
                return

        total_bytes_before = 0
        active_processes = []

        for proc in self.steam_processes:
            try:
                io_counters = proc.io_counters()
                total_bytes_before += io_counters.bytes_recv
                active_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        time.sleep(1)

        total_bytes_after = 0
        for proc in active_processes:
            try:
                io_counters = proc.io_counters()
                total_bytes_after += io_counters.bytes_recv
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        bytes_diff = total_bytes_after - total_bytes_before
        self.download_speed = bytes_diff / 1024

        if self.download_speed > 10:
            self.download_status = "Загрузка"
        else:
            self.download_status = "Простой или Пауза"

    def _parse_log_file(self):
        if not os.path.exists(self.log_path):
            return False

        try:
            mod_time = os.path.getmtime(self.log_path)
            if time.time() - mod_time > 300:
                return False

            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                if not lines:
                    return False

                recent_lines = lines[-200:]

                for line in reversed(recent_lines):
                    app_match = re.search(r"AppID (\d+) \"(.+?)\"", line)
                    if app_match and "downloading" in line.lower():
                        self.current_game = app_match.group(2)

                    if "download complete" in line.lower():
                        self.download_status = "Завершено"
                    elif "download paused" in line.lower():
                        self.download_status = "Пауза"
                    elif "downloading" in line.lower():
                        self.download_status = "Загрузка"

                    speed_match = re.search(r"(\d+\.?\d*)\s*(KB|MB|GB)/s", line, re.IGNORECASE)
                    if speed_match:
                        speed = float(speed_match.group(1))
                        unit = speed_match.group(2).upper()

                        if unit == "MB":
                            speed *= 1024
                        elif unit == "GB":
                            speed *= 1024 * 1024

                        self.download_speed = speed
                        break
            return True
        except Exception as e:
            logging.error(f"Ошибка при парсинге лог-файла: {e}")
            return False

    def _check_download_folder(self):
        download_dir = os.path.join(self.steam_path, "steamapps", "downloading")
        if not os.path.exists(download_dir):
            return False

        try:
            subdirs = [d for d in os.listdir(download_dir) if os.path.isdir(os.path.join(download_dir, d))]
            if not subdirs:
                return False

            latest_dir = max(subdirs, key=lambda d: os.path.getmtime(os.path.join(download_dir, d)))

            app_id_match = re.search(r"^(\d+)", latest_dir)
            if app_id_match:
                app_id = app_id_match.group(1)
                manifest_path = os.path.join(self.steam_path, "steamapps", f"appmanifest_{app_id}.acf")

                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        name_match = re.search(r'"name"\s+"(.+?)"', content)
                        if name_match:
                            self.current_game = name_match.group(1)
                            return True

            return False
        except Exception as e:
            logging.error(f"Ошибка при проверке папки загрузок: {e}")
            return False

    def update_download_info(self):
        if self._parse_log_file():
            return

        if self._check_download_folder():
            return

        self._monitor_network_usage()

    def start_monitoring(self):
        self.running = True

        monitor_thread = threading.Thread(target=self._monitor_loop)
        monitor_thread.daemon = True
        monitor_thread.start()

        logging.info("Запуск мониторинга загрузок Steam на 5 минут")
        logging.info(f"Путь к Steam: {self.steam_path}")

        start_time = time.time()
        while time.time() - start_time < 300:
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"\nВремя: {current_time}")
            print(f"Игра: {self.current_game}")
            print(f"Статус: {self.download_status}")
            print(f"Скорость загрузки: {self.download_speed:.2f} KB/s")
            print("-" * 40)
            time.sleep(60)

        self.running = False
        logging.info("Мониторинг завершен")

    def _monitor_loop(self):
        while self.running:
            try:
                self.update_download_info()
            except Exception as e:
                logging.error(f"Ошибка в цикле мониторинга: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print("Мониторинг загрузок Steam")
    print("=" * 40)
    try:
        monitor = SteamDownloadMonitor()
        print(f"Путь к Steam: {monitor.steam_path}")
        print("Мониторинг в течение 5 минут, вывод статистики каждую минуту.")
        print("-" * 40)
        monitor.start_monitoring()
    except Exception as e:
        logging.critical(f"Критическая ошибка: {e}")
        print(f"Ошибка: {e}")
