import json
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = APP_ROOT / "data"
NOTEPADS_DIR = DATA_DIR / "notepad"
ROPA_DIR = DATA_DIR / "ropa"
DOWNLOADS_DIR = APP_ROOT / "downloads"
VENDOR_DIR = APP_ROOT / "tsr_downloader" 
DOWNLOADER_SRC_DIR = VENDOR_DIR / "./"

USER_CONFIG_PATH = DATA_DIR / "config_user.json"
ALLOWED_URLS_PATH = DATA_DIR / "allowed_urls.json"
DOWNLOADER_CONFIG_PATH = DOWNLOADER_SRC_DIR / "config.json"

DEFAULT_USER_CONFIG = {
    "modo_oscuro": False,
    "sonido_al_finalizar": True,
    "siempre_visible": False,
    "popup_al_finalizar": True,
    "autoscan_duplicados": False,
    "download_root_path": "",
    "categorizacion_automatica": False,
}


def ensure_project_layout():
    for path in (DATA_DIR, NOTEPADS_DIR, ROPA_DIR, DOWNLOADS_DIR, DOWNLOADER_SRC_DIR):
        path.mkdir(parents=True, exist_ok=True)


def normalize_destination_path(path_value):
    cleaned = str(path_value).strip().strip('"').strip("'")
    if not cleaned:
        return ""
    if not os.path.isabs(cleaned):
        cleaned = str((APP_ROOT / cleaned).resolve())
    return os.path.abspath(cleaned)


def load_user_preferences():
    ensure_project_layout()
    if USER_CONFIG_PATH.exists():
        try:
            with USER_CONFIG_PATH.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            data = {}
    else:
        data = {}

    prefs = DEFAULT_USER_CONFIG.copy()
    prefs.update(data)
    saved_root = prefs.get("download_root_path", "")
    if saved_root:
        prefs["download_root_path"] = normalize_destination_path(saved_root)
    return prefs


def save_user_preferences(preferences):
    ensure_project_layout()
    with USER_CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(preferences, handle, indent=4)


def load_allowed_urls():
    ensure_project_layout()
    default_data = {"allowed_urls": ["https://www.thesimsresource.com/downloads"]}

    if not ALLOWED_URLS_PATH.exists():
        with ALLOWED_URLS_PATH.open("w", encoding="utf-8") as handle:
            json.dump(default_data, handle, indent=4)
        return default_data["allowed_urls"]

    try:
        with ALLOWED_URLS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return default_data["allowed_urls"]

    raw_urls = data.get("allowed_urls", data.get("urls_permitidas", []))
    if isinstance(raw_urls, str):
        return [raw_urls]
    if isinstance(raw_urls, list):
        return raw_urls
    return []


def sync_downloader_config(destination_path):
    ensure_project_layout()
    config_data = {}
    if DOWNLOADER_CONFIG_PATH.exists():
        try:
            with DOWNLOADER_CONFIG_PATH.open("r", encoding="utf-8") as handle:
                config_data = json.load(handle)
        except Exception:
            config_data = {}

    normalized = normalize_destination_path(destination_path)
    if normalized:
        os.makedirs(normalized, exist_ok=True)
    config_data["downloadDirectory"] = normalized.replace("\\", "/")

    with DOWNLOADER_CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config_data, handle, indent=4)
