import os
import time
import subprocess
import threading
import datetime
import glob
import sys
import pyperclip
import winsound
import hashlib
import json
import re  # Importamos re para expresiones regulares
import customtkinter as ctk
from tkinter import messagebox, filedialog  # Importamos filedialog
from src.trs4_sims.settings import (
    APP_ROOT,
    DEFAULT_USER_CONFIG,
    DOWNLOADS_DIR,
    DOWNLOADER_SRC_DIR,
    NOTEPADS_DIR,
    ensure_project_layout,
    load_allowed_urls,
    load_user_preferences,
    normalize_destination_path,
    save_user_preferences,
    sync_downloader_config,
)

# --- CONFIGURACIÓN DE RUTAS ---
# Usamos __file__ para ubicar el json de usuario en la misma carpeta que este script
ensure_project_layout()
RUTA_BASE = str(APP_ROOT)
RUTA_NOTEPADS = str(NOTEPADS_DIR)
RUTA_CARPETA_MAIN = str(DOWNLOADER_SRC_DIR)

# --- NUEVA ESTRUCTURA DE CATEGORÍAS (SEGÚN INSTRUCCIONES) ---
# Orden de prioridad para desempate (1 es mayor prioridad)
CATEGORIAS_PRIORIDAD = [
    "child", "makeup", "outfits", "tops", "bottoms", 
    "skintones", "shoes", "hair", "accessories"
]

# Palabras clave por categoría
PALABRAS_CLAVE = {
    "child": ["child"],
    "skintones": ["skintone", "skintones", "skin"],
    "makeup": ["makeup", "lipstick", "lip", "lips", "blush", "eyeshadow", "liner", "eyeliner"],
    "outfits": ["outfit", "dress", "fullbody", "gown", "set", "jumpsuit"],
    "tops": ["top", "shirt", "blouse", "hoodie", "tank"],
    "bottoms": ["bottom", "pant", "skirt", "jean", "trouser", "legging"],
    "shoes": ["shoe", "boot", "boots", "sneaker", "heel", "sandals"],
    "hair": ["hair", "hairstyle"],
    "accessories": ["accessory", "necklace", "earring", "hat", "glasses"]
}

# --- CONFIGURACIÓN POR DEFECTO DEL USUARIO (UI) ---
DEFAULT_USER_CONFIG = {
    "modo_oscuro": False,
    "sonido_al_finalizar": True,
    "siempre_visible": False,
    "popup_al_finalizar": True,
    "autoscan_duplicados": False,
    "download_root_path": "",  # AQUÍ SE GUARDA LA RUTA MAESTRA PERMANENTE
    "categorizacion_automatica": False 
}

# --- CONFIGURACIÓN VISUAL INICIAL ---
ctk.set_appearance_mode("Light") 
ctk.set_default_color_theme("blue") 

class SimsOrchestratorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Configuración Ventana
        self.title("Sims 4 Orchestrator V24 (Path Visualization)")
        self.geometry("1250x950")
        
        # --- CARGAR PREFERENCIAS DE USUARIO (UI) ---
        self.user_prefs = DEFAULT_USER_CONFIG.copy()
        self.cargar_preferencias_usuario()

        # Aplicar tema inicial inmediatamente
        if self.user_prefs["modo_oscuro"]:
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

        # --- CARGAR RUTA DE DESCARGA (Lógica de Negocio) ---
        # 1. Intentamos cargar la ruta GUARDADA por el usuario en config_user.json
        saved_root = self.user_prefs.get("download_root_path", "")
        
        if saved_root and os.path.exists(saved_root):
            self.download_root_path = saved_root
        else:
            # 2. Si no hay ruta guardada o no existe, usamos la ruta por defecto
            self.download_root_path = str(DOWNLOADS_DIR)
            # Guardamos esta ruta por defecto como la preferencia actual
            self.user_prefs["download_root_path"] = self.download_root_path
            self.guardar_preferencias_usuario()

        # Sincronizamos el config.json del script con la ruta base inicial (limpieza)
        self.actualizar_archivo_config_json_script(self.download_root_path)

        # --- ESTADO GENERAL ---
        self.running = False
        self.paused = False 
        self.pause_event = threading.Event()
        self.pause_event.set()
        
        self.current_process = None
        self.current_dest_folder = None
        self.available_filenames = [] 
        self.selected_files_specific = [] 
        self.last_files_state = None 
        self.folder_widgets = {}
        
        # --- VARIABLES COPYBOARD ---
        self.copyboard_active = False
        self.copyboard_paused = False
        self.copyboard_start_time = None
        self.copyboard_urls_count = 0
        self.last_clipboard_content = ""
        self.allowed_urls = []
        
        # --- NUEVA VARIABLE: Notepad seleccionado ---
        self.current_notepad_path = None

        # --- NUEVA VARIABLE: Ruta de Escaneo de Duplicados ---
        # Por defecto es igual a la ruta de descargas, pero puede cambiarse
        self.duplicate_scan_path = self.download_root_path 
        
        # --- SISTEMA DE LOGS ---
        self.log_data = {"Inicio": "", "Copyboard": ""} 
        self.current_log_view = "Inicio" 
        self.log_buttons = {} 
        
        # Variables Timer Descarga
        self.time_left = 0
        self.timer_active = False
        
        # Variables Duplicados
        self.duplicate_groups = []
        self.duplicate_vars = []
        
        # Inicialización de widgets
        self.log_box = None 
        self.log_box_dup = None
        self.log_box_copy = None

        # Cargar JSON URLs permitidas (variable self.allowed_urls se usa en monitor)
        # Nota: El módulo de categorización carga su propio json fresco.
        self.cargar_urls_permitidas()

        # --- LAYOUT (Rejilla) ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ================= PANEL IZQUIERDO (CONTROLES) =================
        self.sidebar = ctk.CTkScrollableFrame(self, width=280, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        # Título
        self.lbl_title = ctk.CTkLabel(self.sidebar, text="PANEL DE CONTROL", font=ctk.CTkFont(size=20, weight="bold"))
        self.lbl_title.grid(row=0, column=0, padx=20, pady=(20, 5))

        # --- VISUALIZACIÓN RUTA DESTINO ACTUAL ---
        self.lbl_base_path_title = ctk.CTkLabel(self.sidebar, text="Carpeta Destino Actual:", font=("Arial", 10, "bold"), text_color="gray", anchor="w")
        self.lbl_base_path_title.grid(row=1, column=0, padx=20, pady=(0, 0), sticky="w")
        
        # Mostramos la ruta dinámica self.download_root_path
        self.lbl_base_path_val = ctk.CTkLabel(self.sidebar, text=self.download_root_path, font=("Arial", 10), text_color="#3B8ED0", wraplength=240, anchor="w")
        self.lbl_base_path_val.grid(row=2, column=0, padx=20, pady=(0, 5), sticky="w")
        # --------------------------------------

        # --- BOTÓN DESTINO (MOVIDO AQUÍ) ---
        self.btn_config_folder = ctk.CTkButton(self.sidebar, text="⚙️ DESTINO", command=self.abrir_menu_config_carpeta) 
        self.btn_config_folder.grid(row=3, column=0, padx=20, pady=(0, 15), sticky="ew")

        # Selector: Todo vs Específico
        self.lbl_mode = ctk.CTkLabel(self.sidebar, text="Modo de ejecución:", anchor="w")
        self.lbl_mode.grid(row=4, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.radio_var = ctk.IntVar(value=1)
        self.radio_all = ctk.CTkRadioButton(self.sidebar, text="Descargar TODO (A-Z)", variable=self.radio_var, value=1, command=self.check_mode)
        self.radio_all.grid(row=5, column=0, padx=20, pady=5, sticky="w")
        
        self.radio_spec = ctk.CTkRadioButton(self.sidebar, text="Selección Personalizada", variable=self.radio_var, value=2, command=self.check_mode)
        self.radio_spec.grid(row=6, column=0, padx=20, pady=5, sticky="w")

        # Frame selección
        self.selection_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.selection_frame.grid(row=7, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.selection_frame.grid_columnconfigure(0, weight=1)

        self.btn_select_custom = ctk.CTkButton(
            self.selection_frame, text="☰ Seleccionar...", 
            command=self.abrir_selector_categorias, state="disabled"
        )
        self.btn_select_custom.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.btn_reload = ctk.CTkButton(self.selection_frame, text="↻", width=40, command=self.refresh_dropdown_options, font=ctk.CTkFont(size=16))
        self.btn_reload.grid(row=0, column=1, sticky="e")
        
        self.lbl_selection_info = ctk.CTkLabel(self.sidebar, text="(Ninguno seleccionado)", font=("Arial", 11), text_color="gray")
        self.lbl_selection_info.grid(row=8, column=0, padx=20, pady=(0, 15))

        # Delay
        self.lbl_delay = ctk.CTkLabel(self.sidebar, text="Espera entre copias (seg):", anchor="w")
        self.lbl_delay.grid(row=9, column=0, padx=20, sticky="w")
        self.entry_delay = ctk.CTkEntry(self.sidebar, placeholder_text="0")
        self.entry_delay.insert(0, "0")
        self.entry_delay.grid(row=10, column=0, padx=20, pady=(5, 15), sticky="ew")

        # Botones de acción
        self.btn_start = ctk.CTkButton(self.sidebar, text="INICIAR PROCESO", command=self.start_thread, fg_color="#2CC985", hover_color="#229A65", text_color="white", font=ctk.CTkFont(weight="bold"))
        self.btn_start.grid(row=11, column=0, padx=20, pady=5, sticky="ew")

        self.btn_pause = ctk.CTkButton(
            self.sidebar, text="⏸️ PAUSAR", command=self.toggle_pause, 
            fg_color="#FFA500", hover_color="#CC8400", state="disabled"
        )
        self.btn_pause.grid(row=12, column=0, padx=20, pady=5, sticky="ew")

        self.btn_stop = ctk.CTkButton(self.sidebar, text="DETENER EMERGENCIA", command=self.stop_process, fg_color="#FF4D4D", hover_color="#CC0000", state="disabled")
        self.btn_stop.grid(row=13, column=0, padx=20, pady=5, sticky="ew")

        # Ajustes
        self.lbl_settings = ctk.CTkLabel(self.sidebar, text="CONFIGURACIÓN", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_settings.grid(row=14, column=0, padx=20, pady=(20, 10), sticky="w")

        # -- SWITCH TEMA --
        self.switch_theme = ctk.CTkSwitch(self.sidebar, text="Modo Oscuro", command=self.cambiar_tema)
        self.switch_theme.grid(row=15, column=0, padx=20, pady=5, sticky="w")
        if self.user_prefs["modo_oscuro"]: self.switch_theme.select()
        else: self.switch_theme.deselect()

        # -- CHECKBOXES --
        self.check_sound = ctk.CTkCheckBox(self.sidebar, text="Sonido al Finalizar TODO", command=self.guardar_estado_checkboxes_generales)
        self.check_sound.grid(row=16, column=0, padx=20, pady=5, sticky="w")
        if self.user_prefs["sonido_al_finalizar"]: self.check_sound.select()
        else: self.check_sound.deselect()
        
        self.check_top = ctk.CTkCheckBox(self.sidebar, text="Siempre visible", command=self.toggle_always_on_top)
        self.check_top.grid(row=17, column=0, padx=20, pady=5, sticky="w")
        if self.user_prefs["siempre_visible"]: 
            self.check_top.select(); self.attributes("-topmost", True)
        else: 
            self.check_top.deselect(); self.attributes("-topmost", False)

        self.check_popup = ctk.CTkCheckBox(self.sidebar, text="Popup al Finalizar", command=self.guardar_estado_checkboxes_generales)
        self.check_popup.grid(row=18, column=0, padx=20, pady=5, sticky="w")
        if self.user_prefs["popup_al_finalizar"]: self.check_popup.select()
        else: self.check_popup.deselect()

        self.check_autodup = ctk.CTkCheckBox(self.sidebar, text="Auto-Scan Duplicados", text_color="#3B8ED0", command=self.guardar_estado_checkboxes_generales)
        self.check_autodup.grid(row=19, column=0, padx=20, pady=5, sticky="w")
        if self.user_prefs["autoscan_duplicados"]: self.check_autodup.select()
        else: self.check_autodup.deselect()

        self.lbl_ratio = ctk.CTkLabel(self.sidebar, text="Tamaño: Logs vs Archivos", font=("Arial", 12))
        self.lbl_ratio.grid(row=20, column=0, padx=20, pady=(15, 0), sticky="w")
        
        self.slider_ratio = ctk.CTkSlider(self.sidebar, from_=2, to=8, number_of_steps=6, command=self.actualizar_layout)
        self.slider_ratio.set(4)
        self.slider_ratio.grid(row=21, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.lbl_footer = ctk.CTkLabel(self.sidebar, text="v24.0 Path View", text_color="gray")
        self.lbl_footer.grid(row=22, column=0, padx=20, pady=10)

        # ================= PANEL DERECHO (PESTAÑAS) =================
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=0, column=1, sticky="nsew", padx=20, pady=10)
        
        # Pestañas
        self.tab_descargas = self.tabview.add("⬇️ DESCARGAS")
        self.tab_duplicados = self.tabview.add("♻️ DUPLICADOS")
        self.tab_copyboard = self.tabview.add("📋 COPYBOARD")

        # ============================================================
        # === PESTAÑA 1: DESCARGAS ===
        # ============================================================
        self.tab_descargas.grid_columnconfigure(0, weight=1)
        self.tab_descargas.grid_rowconfigure(2, weight=1)
        self.tab_descargas.grid_rowconfigure(10, weight=1)

        self.log_header_frame = ctk.CTkFrame(self.tab_descargas, fg_color="transparent")
        self.log_header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        ctk.CTkLabel(self.log_header_frame, text="Registro de Actividad", font=("Arial", 14, "bold"), anchor="w").pack(side="left")
        
        self.log_tabs_frame = ctk.CTkScrollableFrame(self.tab_descargas, height=35, orientation="horizontal", label_text="")
        self.log_tabs_frame.grid(row=1, column=0, sticky="ew", pady=(0, 0))
        
        self.log_box = ctk.CTkTextbox(self.tab_descargas, font=("Consolas", 12), border_width=1, height=150) 
        self.log_box.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        self.log_box.configure(state="disabled")

        self.crear_boton_log("Inicio", select=True)

        self.lbl_progress_title = ctk.CTkLabel(self.tab_descargas, text="Progreso de Copiado: Inactivo", font=("Arial", 12, "bold"), text_color="#555", anchor="w")
        self.lbl_progress_title.grid(row=3, column=0, sticky="w", pady=(0, 2))

        self.progress_bar = ctk.CTkProgressBar(self.tab_descargas, orientation="horizontal", progress_color="#2CC985")
        self.progress_bar.grid(row=4, column=0, sticky="ew", pady=(0, 5))
        self.progress_bar.set(0)

        self.lbl_url_display = ctk.CTkLabel(self.tab_descargas, text="", font=("Consolas", 11, "bold"), text_color=("#B8860B", "#FFFF00"), anchor="w")
        self.lbl_url_display.grid(row=5, column=0, sticky="w", padx=0, pady=(0, 15))

        self.lbl_timer = ctk.CTkLabel(self.tab_descargas, text="Tiempo Restante: --:--", font=("Arial", 11), text_color="gray", anchor="e")
        self.lbl_timer.grid(row=5, column=0, sticky="e", padx=0, pady=(0, 15))

        self.nav_header = ctk.CTkFrame(self.tab_descargas, fg_color="transparent")
        self.nav_header.grid(row=6, column=0, sticky="ew", pady=(5,0))
        ctk.CTkLabel(self.nav_header, text="Carpetas de Descarga (Monitor):", font=("Arial", 12, "bold"), text_color="#2CC985").pack(side="left")
        
        self.stats_frame = ctk.CTkFrame(self.nav_header, fg_color="transparent")
        self.stats_frame.pack(side="right")
        self.lbl_stats_count = ctk.CTkLabel(self.stats_frame, text="📦 Archivos: 0", font=("Arial", 12, "bold"), text_color="#3B8ED0")
        self.lbl_stats_count.pack(side="left", padx=(0, 15))
        self.lbl_stats_size = ctk.CTkLabel(self.stats_frame, text="💾 Peso Sesión: 0 MB", font=("Arial", 12, "bold"), text_color="#E67E22")
        self.lbl_stats_size.pack(side="left", padx=(0, 5))
        
        self.nav_buttons_frame = ctk.CTkScrollableFrame(self.tab_descargas, height=85, orientation="horizontal", label_text="")
        self.nav_buttons_frame.grid(row=7, column=0, sticky="ew", pady=(0, 15))

        self.monitor_header_frame = ctk.CTkFrame(self.tab_descargas, fg_color="transparent")
        self.monitor_header_frame.grid(row=8, column=0, sticky="ew", pady=(0, 0))
        
        self.lbl_monitor_title = ctk.CTkLabel(self.monitor_header_frame, text="Visor de Archivos (.package)", font=("Arial", 14, "bold"), anchor="w")
        self.lbl_monitor_title.pack(side="left")
        
        self.btn_open_folder = ctk.CTkButton(self.monitor_header_frame, text="↗ Abrir Carpeta", width=120, height=24, fg_color="#555", state="disabled", command=self.abrir_carpeta_actual)
        self.btn_open_folder.pack(side="right")

        # --- SE ELIMINÓ EL BOTÓN DESTINO DE AQUÍ ---

        self.lbl_path_debug = ctk.CTkLabel(self.tab_descargas, text="Selecciona una carpeta arriba...", font=("Arial", 10), text_color="gray", anchor="w")
        self.lbl_path_debug.grid(row=9, column=0, sticky="w", pady=(0, 5))

        self.file_list_frame = ctk.CTkScrollableFrame(self.tab_descargas, label_text="", border_width=1, border_color="gray")
        self.file_list_frame.grid(row=10, column=0, sticky="nsew", pady=(0, 0))

        # ============================================================
        # === PESTAÑA 2: DUPLICADOS ===
        # ============================================================
        self.tab_duplicados.grid_columnconfigure(0, weight=1)
        self.tab_duplicados.grid_rowconfigure(1, weight=1) # Log Dup
        self.tab_duplicados.grid_rowconfigure(6, weight=3) # Lista Dup (MOVIDA POR NUEVA BARRA)

        ctk.CTkLabel(self.tab_duplicados, text="Log de Búsqueda (Grupos Encontrados)", font=("Arial", 14, "bold"), anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.log_box_dup = ctk.CTkTextbox(self.tab_duplicados, font=("Consolas", 11), border_width=1, height=100)
        self.log_box_dup.grid(row=1, column=0, sticky="nsew", pady=(0, 5)) # Reduced padding
        self.log_box_dup.configure(state="disabled")

        # --- NUEVO: BARRA DE PROGRESO DUPLICADOS ---
        self.dup_progress_frame = ctk.CTkFrame(self.tab_duplicados, fg_color="transparent")
        self.dup_progress_frame.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        
        self.lbl_dup_progress = ctk.CTkLabel(self.dup_progress_frame, text="Progreso: 0%", font=("Arial", 11, "bold"), text_color="gray", anchor="w")
        self.lbl_dup_progress.pack(fill="x")
        
        self.dup_progress_bar = ctk.CTkProgressBar(self.dup_progress_frame, orientation="horizontal", progress_color="#3B8ED0")
        self.dup_progress_bar.pack(fill="x", pady=(2, 0))
        self.dup_progress_bar.set(0)
        # -------------------------------------------

        self.dup_action_frame = ctk.CTkFrame(self.tab_duplicados, fg_color="transparent")
        self.dup_action_frame.grid(row=3, column=0, sticky="ew", pady=(0, 5))
        
        self.btn_scan_dup = ctk.CTkButton(self.dup_action_frame, text="🔍 Buscar Duplicados Ahora", command=self.iniciar_escaneo_duplicados)
        self.btn_scan_dup.pack(side="left")
        
        # --- NUEVO BOTÓN RUTA ---
        # Botón "Ruta" con un color distintivo (naranja) para configurar ruta específica de duplicados
        self.btn_path_dup = ctk.CTkButton(self.dup_action_frame, text="📂 Ruta", width=80, fg_color="#E67E22", command=self.abrir_menu_ruta_duplicados)
        self.btn_path_dup.pack(side="left", padx=5)
        # ------------------------

        self.btn_del_dup = ctk.CTkButton(self.dup_action_frame, text="🗑️ Eliminar Seleccionados", fg_color="#FF4D4D", hover_color="#CC0000", state="disabled", command=self.eliminar_duplicados)
        self.btn_del_dup.pack(side="right")

        ctk.CTkLabel(self.tab_duplicados, text="Archivos Duplicados Encontrados", font=("Arial", 14, "bold"), anchor="w").grid(row=4, column=0, sticky="w", pady=(5, 5))
        self.dup_filters_frame = ctk.CTkScrollableFrame(self.tab_duplicados, height=40, orientation="horizontal", label_text="")
        self.dup_filters_frame.grid(row=5, column=0, sticky="ew", pady=(0, 5))
        self.dup_list_frame = ctk.CTkScrollableFrame(self.tab_duplicados, label_text="Resultados", border_width=1, border_color="gray")
        self.dup_list_frame.grid(row=6, column=0, sticky="nsew")

        # ============================================================
        # === PESTAÑA 3: COPYBOARD (MODIFICADO) ===
        # ============================================================
        self.tab_copyboard.grid_columnconfigure(0, weight=1)
        self.tab_copyboard.grid_rowconfigure(1, weight=1)
        self.tab_copyboard.grid_rowconfigure(5, weight=2)

        ctk.CTkLabel(self.tab_copyboard, text="Registro Copyboard (URLs Capturadas)", font=("Arial", 14, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        self.log_box_copy = ctk.CTkTextbox(self.tab_copyboard, font=("Consolas", 11), border_width=1, height=120)
        self.log_box_copy.grid(row=1, column=0, sticky="nsew", pady=(5, 15))
        self.log_box_copy.configure(state="disabled")

        self.copy_controls_frame = ctk.CTkFrame(self.tab_copyboard, fg_color="transparent")
        self.copy_controls_frame.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        self.btn_copy_start = ctk.CTkButton(self.copy_controls_frame, text="✅ ACTIVAR", fg_color="#2CC985", width=100, command=self.iniciar_copyboard)
        self.btn_copy_start.pack(side="left", padx=5)
        self.btn_copy_pause = ctk.CTkButton(self.copy_controls_frame, text="⏸️ PAUSAR", fg_color="#FFA500", width=100, state="disabled", command=self.pausar_copyboard)
        self.btn_copy_pause.pack(side="left", padx=5)
        self.btn_copy_stop = ctk.CTkButton(self.copy_controls_frame, text="🛑 DESACTIVAR", fg_color="#FF4D4D", width=100, state="disabled", command=self.detener_copyboard)
        self.btn_copy_stop.pack(side="left", padx=5)

        self.lbl_copy_timer = ctk.CTkLabel(self.copy_controls_frame, text="Tiempo: 00:00", font=("Arial", 12, "bold"), text_color="gray")
        self.lbl_copy_timer.pack(side="right", padx=15)
        self.lbl_copy_count = ctk.CTkLabel(self.copy_controls_frame, text="URLs: 0", font=("Arial", 12, "bold"), text_color="#3B8ED0")
        self.lbl_copy_count.pack(side="right", padx=5)

        self.copy_opts_frame = ctk.CTkFrame(self.tab_copyboard, fg_color="transparent")
        self.copy_opts_frame.grid(row=3, column=0, sticky="ew", pady=(5, 10))
        
        self.btn_cat_config = ctk.CTkButton(self.copy_opts_frame, text="Categorización", command=self.abrir_menu_categorizacion)
        self.btn_cat_config.pack(side="left", padx=5)
        
        self.btn_help_cat = ctk.CTkButton(self.copy_opts_frame, text="?", width=25, height=25, fg_color="gray", command=self.mostrar_ayuda_cat)
        self.btn_help_cat.pack(side="left", padx=5)

        ctk.CTkLabel(self.tab_copyboard, text="Visor de Notepads (.txt)", font=("Arial", 14, "bold"), anchor="w").grid(row=4, column=0, sticky="w")
        
        # --- NUEVA ESTRUCTURA DEL VISOR (MODIFICADO) ---
        self.notepad_viewer_frame = ctk.CTkFrame(self.tab_copyboard, fg_color="transparent")
        self.notepad_viewer_frame.grid(row=5, column=0, sticky="nsew")
        self.notepad_viewer_frame.grid_columnconfigure(0, weight=1) # Lista
        self.notepad_viewer_frame.grid_columnconfigure(1, weight=3) # Visor
        # Ahora el visor tiene 2 filas: 0 para herramientas/info, 1 para contenido
        self.notepad_viewer_frame.grid_rowconfigure(0, weight=0)
        self.notepad_viewer_frame.grid_rowconfigure(1, weight=1)

        # 1. LISTA DE ARCHIVOS (Izquierda) - Abarca 2 filas para ocupar todo el alto
        self.notepad_list_frame = ctk.CTkScrollableFrame(self.notepad_viewer_frame, label_text="Archivos", width=200)
        self.notepad_list_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 5))

        # 2. HEADER DE HERRAMIENTAS (Derecha Arriba) - NUEVO
        self.notepad_tools_frame = ctk.CTkFrame(self.notepad_viewer_frame, fg_color="transparent", height=30)
        self.notepad_tools_frame.grid(row=0, column=1, sticky="ew", pady=(0, 5))
        
        # Etiqueta de conteo de líneas
        self.lbl_notepad_lines = ctk.CTkLabel(self.notepad_tools_frame, text="Líneas totales: --", font=("Arial", 11, "bold"), text_color="gray")
        self.lbl_notepad_lines.pack(side="left", padx=5)

        # Botón Eliminar (A la derecha del header)
        self.btn_delete_notepad = ctk.CTkButton(
            self.notepad_tools_frame, 
            text="🗑️ Eliminar Notepad", 
            fg_color="#FF4D4D", 
            hover_color="#CC0000",
            width=120,
            height=24,
            state="disabled",
            command=self.eliminar_notepad_actual
        )
        self.btn_delete_notepad.pack(side="right", padx=5)

        # 3. CAJA DE TEXTO (Derecha Abajo) - MOVIDO A ROW 1
        self.notepad_preview_box = ctk.CTkTextbox(self.notepad_viewer_frame, font=("Consolas", 11))
        self.notepad_preview_box.grid(row=1, column=1, sticky="nsew")
        
        # ----------------------------------------------------------------------

        self.notepad_buttons_frame = ctk.CTkFrame(self.tab_copyboard, fg_color="transparent")
        self.notepad_buttons_frame.grid(row=6, column=0, sticky="w", pady=5)

        self.btn_open_notepads = ctk.CTkButton(self.notepad_buttons_frame, text="📂 Ubicación", width=120, command=self.abrir_ubicacion_notepads)
        self.btn_open_notepads.pack(side="left", padx=(0, 5))

        self.btn_reload_notepad = ctk.CTkButton(self.notepad_buttons_frame, text="↻ Recargar Archivos", width=120, command=self.actualizar_visor_notepad)
        self.btn_reload_notepad.pack(side="left")

        # --- INICIALIZACIÓN ---
        self.refresh_dropdown_options() 
        self.tomar_foto_inicial()
        self.loop_actualizar_carpetas()
        self.actualizar_layout(self.slider_ratio.get())
        self.after(1500, self.update_file_monitor)
        self.actualizar_visor_notepad()

    # =========================================================================
    # LÓGICA DE PREFERENCIAS (CONFIG DE USUARIO)
    # =========================================================================
    def cargar_preferencias_usuario(self):
        """Carga las preferencias desde config_user.json o crea el archivo si no existe."""
        try:
            self.user_prefs = load_user_preferences()
            print(f"[Preferencias] Cargadas: {self.user_prefs}")
        except Exception as e:
            print(f"[Preferencias] Error al cargar: {e}. Usando defaults.")
            self.user_prefs = DEFAULT_USER_CONFIG.copy()
            self.guardar_preferencias_usuario()

    def guardar_preferencias_usuario(self):
        """Guarda el estado actual de self.user_prefs en el archivo JSON."""
        try:
            save_user_preferences(self.user_prefs)
            print("[Preferencias] Guardadas correctamente.")
        except Exception as e:
            print(f"[Preferencias] Error al guardar: {e}")

    def guardar_estado_checkboxes_generales(self):
        self.user_prefs["sonido_al_finalizar"] = bool(self.check_sound.get())
        self.user_prefs["popup_al_finalizar"] = bool(self.check_popup.get())
        self.user_prefs["autoscan_duplicados"] = bool(self.check_autodup.get())
        self.guardar_preferencias_usuario()

    def normalizar_ruta_destino(self, ruta):
        return normalize_destination_path(ruta)

    # =========================================================================
    # LÓGICA DE ACTUALIZACIÓN DEL CONFIG.JSON (SCRIPT)
    # =========================================================================
    def actualizar_archivo_config_json_script(self, ruta_destino):
        try:
            sync_downloader_config(ruta_destino)
        except Exception as e:
            print(f"Error sincronizando config.json: {e}")

    # =========================================================================
    # LÓGICA CONFIGURACIÓN CARPETA DESTINO (Botón DESTINO)
    # =========================================================================
    def abrir_menu_config_carpeta(self):
        top = ctk.CTkToplevel(self)
        top.title("Configurar Destino de Descarga")
        top.geometry("400x300") 
        top.transient(self)
        top.grab_set()
        
        ctk.CTkLabel(top, text="Ruta Actual de Trabajo (Scripts/Logs):", font=("Arial", 10, "bold"), text_color="gray").pack(pady=(15, 0))
        ctk.CTkLabel(top, text=RUTA_BASE, font=("Arial", 10), wraplength=380, text_color="gray").pack(pady=(0, 10))
        
        ctk.CTkLabel(top, text="DESTINO DE DESCARGAS ACTUAL:", font=("Arial", 11, "bold"), text_color="#3B8ED0").pack(pady=(5,0))
        ctk.CTkLabel(top, text=self.download_root_path, font=("Arial", 10), wraplength=380).pack(pady=(0, 15))
        
        ctk.CTkLabel(top, text="¿Cómo desea cambiar el destino?", font=("Arial", 13, "bold")).pack(pady=5)
        
        btn_win = ctk.CTkButton(top, text="📂 Seleccionar Carpeta (Windows)", command=lambda: [top.destroy(), self.config_carpeta_windows()], width=250)
        btn_win.pack(pady=10)
        
        btn_man = ctk.CTkButton(top, text="✍️ Ingresar Ruta Manualmente", command=lambda: [top.destroy(), self.config_carpeta_manual()], width=250, fg_color="#E67E22", hover_color="#D35400")
        btn_man.pack(pady=10)
        
        ctk.CTkButton(top, text="Cancelar", command=top.destroy, fg_color="gray", width=100).pack(pady=10)

    def config_carpeta_windows(self):
        ruta = filedialog.askdirectory(title="Seleccionar Carpeta Destino para Descargas")
        if ruta:
            self.actualizar_destino_usuario(ruta)

    def config_carpeta_manual(self):
        dialog = ctk.CTkInputDialog(text="Ingrese la ruta completa de la carpeta destino:", title="Ruta Manual")
        entrada = dialog.get_input()
        if entrada:
            ruta_limpia = entrada.strip('"').strip("'")
            try:
                os.makedirs(ruta_limpia, exist_ok=True)
                if os.path.exists(ruta_limpia):
                    self.actualizar_destino_usuario(ruta_limpia)
                else:
                     messagebox.showerror("Error", "No se pudo acceder o crear la ruta especificada.")
            except Exception as e:
                messagebox.showerror("Error", f"Ruta inválida o error de permisos:\n{e}")

    def actualizar_destino_usuario(self, nueva_ruta):
        # 1. Actualizar variable interna maestra
        self.download_root_path = self.normalizar_ruta_destino(nueva_ruta)

        # 2. Guardar en preferencias de usuario (PERSISTENCIA)
        self.user_prefs["download_root_path"] = self.download_root_path
        self.guardar_preferencias_usuario()
        
        # 3. Sincronizar el script externo temporalmente (para que esté listo)
        self.actualizar_archivo_config_json_script(self.download_root_path)
        
        # 4. Actualizar ruta duplicados también a Default para evitar inconsistencias
        self.duplicate_scan_path = self.download_root_path

        self.log(f"⚙️ Destino actualizado a: {self.download_root_path}", channel="Inicio")
        
        # 5. Actualizar interfaz
        self.lbl_base_path_val.configure(text=self.download_root_path)
        self.loop_actualizar_carpetas()
        messagebox.showinfo("Éxito", f"Carpeta de descargas cambiada a:\n{self.download_root_path}")

    # =========================================================================
    # LÓGICA DE SELECCIÓN DE RUTA DUPLICADOS (NUEVO)
    # =========================================================================
    def abrir_menu_ruta_duplicados(self):
        """Muestra popup para elegir ruta de escaneo de duplicados."""
        top = ctk.CTkToplevel(self)
        top.title("Ruta de Búsqueda")
        top.geometry("300x180")
        top.transient(self)
        top.grab_set()
        
        ctk.CTkLabel(top, text="Configurar ruta de escaneo:", font=("Arial", 12, "bold")).pack(pady=(15, 10))
        
        # Mostrar ruta actual (acortada si es larga)
        ruta_display = self.duplicate_scan_path
        if len(ruta_display) > 40: ruta_display = "..." + ruta_display[-37:]
        ctk.CTkLabel(top, text=f"Actual: {ruta_display}", font=("Arial", 10), text_color="gray").pack(pady=(0, 15))

        btn_custom = ctk.CTkButton(top, text="📂 Elegir otra carpeta...", command=lambda: [top.destroy(), self.fijar_ruta_dup_custom()])
        btn_custom.pack(pady=5)
        
        btn_default = ctk.CTkButton(top, text="↩ Restablecer a Default", fg_color="#3B8ED0", command=lambda: [top.destroy(), self.fijar_ruta_dup_default()])
        btn_default.pack(pady=5)

    def fijar_ruta_dup_custom(self):
        ruta = filedialog.askdirectory(title="Seleccionar carpeta para buscar duplicados")
        if ruta:
            self.duplicate_scan_path = os.path.abspath(ruta)
            self.log_dup(f"📍 Ruta de escaneo cambiada a: {self.duplicate_scan_path}")
            messagebox.showinfo("Ruta Actualizada", f"Ahora se buscarán duplicados en:\n{self.duplicate_scan_path}")

    def fijar_ruta_dup_default(self):
        self.duplicate_scan_path = self.download_root_path
        self.log_dup(f"📍 Ruta de escaneo restablecida a Default: {self.duplicate_scan_path}")
        messagebox.showinfo("Ruta Default", "Se ha restablecido la carpeta de destino principal.")

    # =========================================================================
    # LÓGICA COPYBOARD (CONFIGURACIÓN DE CATEGORIZACIÓN)
    # =========================================================================
    def abrir_menu_categorizacion(self):
        """Abre un popup para activar/desactivar la categorización automática."""
        top = ctk.CTkToplevel(self)
        top.title("Configurar Categorización")
        top.geometry("300x200")
        top.transient(self)
        top.grab_set()

        estado_actual = "ACTIVADO" if self.user_prefs.get("categorizacion_automatica") else "DESACTIVADO"
        color_estado = "green" if self.user_prefs.get("categorizacion_automatica") else "red"

        ctk.CTkLabel(top, text=f"Estado actual: {estado_actual}", font=("Arial", 12, "bold"), text_color=color_estado).pack(pady=20)

        def set_active():
            self.user_prefs["categorizacion_automatica"] = True
            self.guardar_preferencias_usuario()
            self.log_copy("Configuración: Categorización ACTIVADA.")
            top.destroy()

        def set_inactive():
            self.user_prefs["categorizacion_automatica"] = False
            self.guardar_preferencias_usuario()
            self.log_copy("Configuración: Categorización DESACTIVADA.")
            top.destroy()

        ctk.CTkButton(top, text="Activar categorización", command=set_active, fg_color="#2CC985").pack(pady=5)
        ctk.CTkButton(top, text="Desactivar categorización", command=set_inactive, fg_color="#FF4D4D").pack(pady=5)

    def cargar_urls_permitidas(self):
        try:
            self.allowed_urls = load_allowed_urls()
        except Exception:
            self.allowed_urls = []

    def mostrar_ayuda_cat(self):
        msg = ("INFORMACIÓN DE CATEGORIZACIÓN:\n\n"
               "• Activar categorización:\n"
               "  Si está activado, al finalizar el CopyBoard se ejecutará automáticamente "
               "el sistema de categorización sin preguntar.\n\n"
               "• Desactivar categorización:\n"
               "  Si está desactivado, el proceso CopyBoard terminará sin categorizar nada.")
        messagebox.showinfo("Ayuda Categorización", msg)

    def log_copy(self, text):
        self.log_box_copy.configure(state="normal")
        self.log_box_copy.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {text}\n")
        self.log_box_copy.see("end")
        self.log_box_copy.configure(state="disabled")

    def abrir_ubicacion_notepads(self):
        if os.path.exists(RUTA_NOTEPADS):
            try:
                os.startfile(RUTA_NOTEPADS)
            except Exception as e:
                 self.log_copy(f"Error abriendo carpeta: {e}")
        else:
             self.log_copy("Carpeta Notepads no existe.")

    def iniciar_copyboard(self):
        if not os.path.exists(RUTA_NOTEPADS):
            try: os.makedirs(RUTA_NOTEPADS)
            except: pass

        path_all = os.path.join(RUTA_NOTEPADS, "uncategorized.txt")
        
        if os.path.exists(path_all) and os.path.getsize(path_all) > 0:
            resp = messagebox.askokcancel("Archivo Existente", "El archivo 'uncategorized.txt' ya tiene datos.\n¿Desea eliminarlo y empezar de cero?")
            if not resp: return 
            try: os.remove(path_all)
            except: pass
        
        otros_txt = [f for f in glob.glob(os.path.join(RUTA_NOTEPADS, "*.txt")) if os.path.basename(f) != "uncategorized.txt"]
        if otros_txt:
            self.abrir_popup_limpieza(otros_txt)
            return

        self._start_copyboard_real()

    def abrir_popup_limpieza(self, archivos):
        top = ctk.CTkToplevel(self)
        top.title("Archivos Existentes Detectados")
        top.geometry("400x500")
        top.transient(self); top.grab_set()
        
        ctk.CTkLabel(top, text="Se encontraron otros archivos .txt.\n¿Qué desea hacer?", font=("Arial", 12, "bold")).pack(pady=10)
        scroll = ctk.CTkScrollableFrame(top)
        scroll.pack(fill="both", expand=True, padx=20)
        
        vars_chk = {}
        for f in archivos:
            v = ctk.BooleanVar(value=False)
            chk = ctk.CTkCheckBox(scroll, text=os.path.basename(f), variable=v)
            chk.pack(anchor="w", pady=2); vars_chk[f] = v
            
        def select_all():
            for v in vars_chk.values(): v.set(True)
        def delete_sel():
            for f, v in vars_chk.items():
                if v.get():
                    try: os.remove(f)
                    except: pass
            top.destroy(); self._start_copyboard_real()
        def ignore(): top.destroy(); self._start_copyboard_real()
        def cancel(): top.destroy()
            
        btn_frame = ctk.CTkFrame(top, fg_color="transparent"); btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="Seleccionar Todos", command=select_all, width=100).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Eliminar Seleccionados", command=delete_sel, fg_color="#FF4D4D", width=120).pack(side="left", padx=5)
        btn_frame2 = ctk.CTkFrame(top, fg_color="transparent"); btn_frame2.pack(pady=5)
        ctk.CTkButton(btn_frame2, text="Ignorar y Continuar", command=ignore, fg_color="gray").pack(side="left", padx=5)
        ctk.CTkButton(btn_frame2, text="Cancelar Proceso", command=cancel, fg_color="gray").pack(side="left", padx=5)

    def _start_copyboard_real(self):
        self.copyboard_active = True
        self.copyboard_paused = False
        self.copyboard_start_time = time.time()
        self.copyboard_urls_count = 0
        self.last_clipboard_content = pyperclip.paste()
        self.btn_copy_start.configure(state="disabled")
        self.btn_copy_pause.configure(state="normal", text="⏸️ PAUSAR", fg_color="#FFA500")
        self.btn_copy_stop.configure(state="normal")
        self.log_copy("🚀 Copyboard Iniciado. Esperando copias...")
        threading.Thread(target=self.thread_copyboard_monitor, daemon=True).start()
        self.update_copyboard_timer()

    def pausar_copyboard(self):
        if not self.copyboard_active: return
        if self.copyboard_paused:
            self.copyboard_paused = False
            self.btn_copy_pause.configure(text="⏸️ PAUSAR", fg_color="#FFA500")
            self.log_copy("▶ Reanudado.")
        else:
            self.copyboard_paused = True
            self.btn_copy_pause.configure(text="▶ REANUDAR", fg_color="#3B8ED0")
            self.log_copy("⏸️ Pausado.")

    def detener_copyboard(self):
        self.copyboard_active = False
        self.btn_copy_start.configure(state="normal")
        self.btn_copy_pause.configure(state="disabled")
        self.btn_copy_stop.configure(state="disabled")
        self.log_copy("🛑 Copyboard Detenido.")
        self.procesar_finalizacion_copyboard()

    def update_copyboard_timer(self):
        if self.copyboard_active:
            if not self.copyboard_paused:
                elapsed = int(time.time() - self.copyboard_start_time)
                m, s = elapsed // 60, elapsed % 60
                self.lbl_copy_timer.configure(text=f"Tiempo: {m:02}:{s:02}")
            self.after(1000, self.update_copyboard_timer)

    def thread_copyboard_monitor(self):
        path_all = os.path.join(RUTA_NOTEPADS, "uncategorized.txt")
        while self.copyboard_active:
            if not self.copyboard_paused:
                try:
                    content = pyperclip.paste()
                    if content != self.last_clipboard_content:
                        self.last_clipboard_content = content
                        es_valida = False
                        for allowed in self.allowed_urls:
                            if content.startswith(allowed): es_valida = True; break
                        if es_valida:
                            with open(path_all, "a", encoding="utf-8") as f: f.write(content + "\n")
                            self.copyboard_urls_count += 1
                            self.log_copy(f"{self.copyboard_urls_count} > {content}") # REMOVED SLICE
                            self.lbl_copy_count.configure(text=f"URLs: {self.copyboard_urls_count}")
                            self.actualizar_visor_notepad() 
                except: pass
            time.sleep(0.5)

    def procesar_finalizacion_copyboard(self):
        categorizar = self.user_prefs.get("categorizacion_automatica", False)
        path_uncat = os.path.join(RUTA_NOTEPADS, "uncategorized.txt")

        # 1. Leer y eliminar duplicados internos
        if os.path.exists(path_uncat):
            with open(path_uncat, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            
            unique_lines = list(dict.fromkeys(lines)) # Preserve order
            
            if len(lines) != len(unique_lines):
                self.log_copy(f"🧹 Eliminados {len(lines) - len(unique_lines)} duplicados internos.")
            
            with open(path_uncat, 'w', encoding='utf-8') as f:
                f.write("\n".join(unique_lines))
                
            if not unique_lines: # Si está vacío, borrar y salir
                os.remove(path_uncat)
                return
        else:
            return

        if not categorizar:
            self.log_copy("ℹ️ Categorización desactivada. Finalizando sin cambios.")
            self.verificar_duplicados_txt()
            return

        # 2. Verificar duplicados en OTROS archivos
        self.log_copy("🔎 Buscando duplicados externos...")
        existing_map = {} # url -> filename
        for f in glob.glob(os.path.join(RUTA_NOTEPADS, "*.txt")):
            if os.path.basename(f) == "uncategorized.txt": continue
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    for idx, line in enumerate(file):
                        l = line.strip()
                        if l: existing_map[l] = (os.path.basename(f), idx + 1)
            except: pass

        # Leer de nuevo uncategorized ya limpio
        with open(path_uncat, 'r', encoding='utf-8') as f:
            current_urls = [l.strip() for l in f.readlines() if l.strip()]

        duplicados_encontrados = []
        for url in current_urls:
            if url in existing_map:
                fname, line = existing_map[url]
                duplicados_encontrados.append((url, fname, line))

        if duplicados_encontrados:
            self.log_copy(f"⚠️ {len(duplicados_encontrados)} Duplicados encontrados en otros archivos.")
            # Clasificar primero en memoria para saber qué categorías tenemos
            datos_categorizados = self.clasificar_en_memoria(current_urls)
            self.abrir_ventanas_duplicados(duplicados_encontrados, datos_categorizados)
        else:
            self.log_copy("✅ Sin duplicados externos. Procediendo...")
            self.ejecutar_categorizacion(path_uncat)

    def clasificar_en_memoria(self, urls):
        categorized_data = {cat: [] for cat in CATEGORIAS_PRIORIDAD}
        categorized_data["uncategorized"] = [] 

        allowed_list = self.allowed_urls # Use loaded allowed list

        for url in urls:
             # Check allowed
            is_allowed = False
            for allowed_prefix in allowed_list:
                if url.startswith(allowed_prefix):
                    is_allowed = True; break
            if not is_allowed:
                categorized_data["uncategorized"].append(url)
                continue

            url_lower = url.lower()
            
            # Child rule
            if "child" in url_lower:
                categorized_data["child"].append(url)
                continue

            # Scores
            scores = {cat: 0 for cat in CATEGORIAS_PRIORIDAD}
            match_found = False
            for cat, keywords in PALABRAS_CLAVE.items():
                for kw in keywords:
                    if kw in url_lower:
                        scores[cat] += 1; match_found = True
            
            if match_found:
                max_score = max(scores.values())
                candidates = [cat for cat, score in scores.items() if score == max_score]
                winner = None
                for prio_cat in CATEGORIAS_PRIORIDAD:
                    if prio_cat in candidates: winner = prio_cat; break
                if winner: categorized_data[winner].append(url)
                else: categorized_data["uncategorized"].append(url) # Should not happen if match_found
            else:
                categorized_data["uncategorized"].append(url)
        
        return categorized_data

    def abrir_ventanas_duplicados(self, duplicados, datos_categorizados):
        # VENTANA IZQUIERDA (INFO)
        info_win = ctk.CTkToplevel(self)
        info_win.title("Información de Duplicados")
        info_win.geometry("500x400")
        info_win.transient(self)
        
        info_box = ctk.CTkTextbox(info_win, font=("Consolas", 10))
        info_box.pack(fill="both", expand=True, padx=10, pady=10)
        
        msg = "--- URLs DUPLICADAS ENCONTRADAS ---\n\n"
        for url, fname, line in duplicados:
            msg += f"URL: {url}\nEN: {fname} (Línea {line})\n{'-'*40}\n"
        info_box.insert("1.0", msg)
        info_box.configure(state="disabled")

        # VENTANA DERECHA (OPCIONES)
        opt_win = ctk.CTkToplevel(self)
        opt_win.title("Resolver Conflictos")
        opt_win.geometry("500x500")
        opt_win.transient(self)
        opt_win.grab_set() # Modal

        ctk.CTkLabel(opt_win, text="Seleccione una acción:", font=("Arial", 12, "bold")).pack(pady=10)
        
        opcion_var = ctk.IntVar(value=1)
        
        # Frame para inputs manuales (Opción 3)
        manual_frame = ctk.CTkScrollableFrame(opt_win, height=150, label_text="Nombres Manuales (Opción 3)")
        
        manual_inputs = {}

        def toggle_manual_inputs():
            state = "normal" if opcion_var.get() == 3 else "disabled"
            for entry in manual_inputs.values():
                entry.configure(state=state)

        # Generar inputs para opción 3
        for cat, urls in datos_categorizados.items():
            if not urls: continue
            lbl = ctk.CTkLabel(manual_frame, text=f"{cat} ({len(urls)} líneas):", anchor="w")
            lbl.pack(fill="x", padx=5, pady=(5,0))
            entry = ctk.CTkEntry(manual_frame)
            entry.insert(0, f"{cat}.txt") # Default name
            entry.pack(fill="x", padx=5, pady=(0,5))
            entry.configure(state="disabled")
            manual_inputs[cat] = entry

        r1 = ctk.CTkRadioButton(opt_win, text="Opción 1: Reemplazar archivos (Sobrescribir si hay conflictos)", variable=opcion_var, value=1, command=toggle_manual_inputs)
        r1.pack(anchor="w", padx=20, pady=5)
        
        r2 = ctk.CTkRadioButton(opt_win, text="Opción 2: Crear nuevos archivos incrementales (V2, V3...)", variable=opcion_var, value=2, command=toggle_manual_inputs)
        r2.pack(anchor="w", padx=20, pady=5)
        
        r3 = ctk.CTkRadioButton(opt_win, text="Opción 3: Escribir nombres manualmente", variable=opcion_var, value=3, command=toggle_manual_inputs)
        r3.pack(anchor="w", padx=20, pady=5)
        
        manual_frame.pack(fill="x", padx=20, pady=5) # Mostrar frame después de radio 3
        
        r4 = ctk.CTkRadioButton(opt_win, text="Opción 4: Cancelar (Mover todo a uncategorized.txt)", variable=opcion_var, value=4, command=toggle_manual_inputs)
        r4.pack(anchor="w", padx=20, pady=5)

        def aceptar():
            op = opcion_var.get()
            nombres_manuales = {}
            if op == 3:
                for cat, entry in manual_inputs.items():
                    nombres_manuales[cat] = entry.get()
            
            info_win.destroy()
            opt_win.destroy()
            self.ejecutar_escritura_final(op, datos_categorizados, nombres_manuales)

        def rechazar():
            # Cancelar es igual a cerrar y no hacer nada (dejar en uncategorized)
            # O volver a selección? Prompt dice "regresa atrás para volver a elegir o cancelar"
            # Asumiremos que cierra las ventanas y deja todo en uncategorized (estado actual)
            info_win.destroy()
            opt_win.destroy()
            self.log_copy("Resolución cancelada por usuario.")

        btn_frame = ctk.CTkFrame(opt_win, fg_color="transparent")
        btn_frame.pack(pady=20)
        ctk.CTkButton(btn_frame, text="ACEPTAR", command=aceptar, fg_color="#2CC985").pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="RECHAZAR", command=rechazar, fg_color="#FF4D4D").pack(side="left", padx=10)

    def ejecutar_escritura_final(self, opcion, datos, nombres_manuales=None):
        created_count = 0
        path_uncat = os.path.join(RUTA_NOTEPADS, "uncategorized.txt")

        # Opción 4: Todo a uncategorized
        if opcion == 4:
             # Ya está en uncategorized, solo asegurarse de que all.txt (si existiera lógica residual) no interfiera
             # Simplemente reescribimos uncategorized con TODO lo que tenemos en memoria
             all_urls = []
             for urls in datos.values(): all_urls.extend(urls)
             with open(path_uncat, 'w', encoding='utf-8') as f:
                 f.write("\n".join(all_urls))
             self.log_copy("Opción 4: Todo movido a uncategorized.txt")
             self.actualizar_visor_notepad()
             return

        # Procesar categorías
        for cat, urls in datos.items():
            if not urls: continue
            
            target_path = ""
            
            # Determinar nombre base
            if cat == "uncategorized":
                base_name = "uncategorized.txt"
            elif cat == "makeup":
                 folder = os.path.join(RUTA_NOTEPADS, "makeup")
                 os.makedirs(folder, exist_ok=True)
                 base_name = os.path.join("makeup", "makeup.txt") # Relative path logic handling below
            else:
                 base_name = f"{cat}.txt"
            
            # Lógica de ruta completa
            if cat == "makeup":
                full_path = os.path.join(RUTA_NOTEPADS, "makeup", "makeup.txt")
            else:
                full_path = os.path.join(RUTA_NOTEPADS, base_name)


            # APLICAR OPCIONES
            final_target = full_path

            if opcion == 1: # Reemplazar si conflicto, llenar si vacío
                # Sobrescribir sin piedad
                pass 
            
            elif opcion == 2: # Incremental
                if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
                    # Buscar siguiente V
                    folder = os.path.dirname(full_path)
                    name_part = os.path.splitext(os.path.basename(full_path))[0]
                    ext = ".txt"
                    counter = 2
                    while True:
                        new_name = f"{name_part}V{counter}{ext}"
                        new_path = os.path.join(folder, new_name)
                        if not os.path.exists(new_path):
                            final_target = new_path
                            break
                        counter += 1
            
            elif opcion == 3: # Manual
                custom_name = nombres_manuales.get(cat, base_name)
                if not custom_name.endswith(".txt"): custom_name += ".txt"
                # Si es makeup, asumimos que el usuario da el nombre del archivo dentro de la carpeta makeup? 
                # O en la raiz? Prompt dice "escribir nombre de cada notepad". 
                # Asumiremos raíz NOTEPAD salvo makeup folder logic overrides.
                # Simplificación: guardar en raiz NOTEPAD con ese nombre
                final_target = os.path.join(RUTA_NOTEPADS, custom_name)

            # Escritura
            mode = 'w' if opcion == 1 else 'a' # Opción 1 implies replace? "reemplazar el anterior". Yes, 'w'.
            # Wait, Option 2 is new file, so 'w' on new file.
            # If standard flow (no duplicates), we usually append. But here we detected duplicates globally.
            # Let's stick to 'w' for Option 1 and 'w' for Option 2 (since it's a new file).
            
            try:
                with open(final_target, 'w', encoding='utf-8') as f:
                    f.write("\n".join(urls))
                created_count += len(urls)
            except Exception as e:
                self.log_copy(f"Error escribiendo {os.path.basename(final_target)}: {e}")

        # Limpiar uncategorized si todo se movió (y no era parte del target)
        # Si la opcion fue 1, 2 o 3, asumimos que uncategorized se procesó (ya sea moviendose a un archivo o quedandose si era "uncategorized")
        # Si "uncategorized" tenía items, se escribieron arriba.
        # Si el archivo original uncategorized.txt sigue ahí y ya procesamos todo, podemos vaciarlo/borrarlo para evitar duplicidad
        # Re-creamos uncategorized solo con lo que quedó en la categoría "uncategorized" (si se usó opcion 3 y se renombró, genial)
        
        # En este flujo, ya escribimos TODO el contenido de memoria a disco.
        # Podemos borrar el uncategorized.txt original con seguridad y dejar solo los nuevos archivos.
        if os.path.exists(path_uncat):
            os.remove(path_uncat)
            
        # Si en los datos había items en la categoría "uncategorized" y se escribieron en "uncategorized.txt" (default name), el archivo vuelve a existir.
        
        self.log_copy(f"✅ Proceso finalizado. {created_count} URLs procesadas.")
        self.actualizar_visor_notepad()


    def ejecutar_categorizacion(self, path_all):
        """
        Módulo completo de categorización híbrida (Versión Standard sin conflicto).
        Reglas: Allowed URLs -> Child Rule -> Score -> Priority
        """
        # Cargar allowed... (Ya hecho o re-verificar)
        allowed_list = self.allowed_urls # Usar caché

        try:
            with open(path_all, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            
            # Clasificar
            categorized_data = self.clasificar_en_memoria(lines)
            
            # Escribir (Append standard)
            created_count = 0
            uncat_buffer = []

            for cat, urls in categorized_data.items():
                if not urls: continue
                
                if cat == "uncategorized":
                    uncat_buffer = urls
                    continue
                
                if cat == "makeup":
                    # --- Lógica de Subcategorización para Makeup ---
                    # Esta sección REEMPLAZA la escritura simple anterior
                    # para dividir el makeup en múltiples archivos según prioridad.
                    
                    folder_path = os.path.join(RUTA_NOTEPADS, "makeup")
                    if not os.path.exists(folder_path):
                        os.makedirs(folder_path)
                    
                    # Diccionario para agrupar internamente
                    makeup_subfiles = {
                        "lipstick.txt": [],
                        "lips.txt": [],
                        "blush.txt": [],
                        "eyeshadow.txt": [],
                        "eyeliner.txt": [],
                        "makeup_other.txt": []
                    }
                    
                    for u in urls:
                        u_lower = u.lower()
                        
                        # Prioridad interna estricta: lipstick > lips > blush > eyeshadow > eyeliner > makeup_other
                        if "lipstick" in u_lower:
                            makeup_subfiles["lipstick.txt"].append(u)
                        elif "lip" in u_lower or "lips" in u_lower: # includes "lips"
                            makeup_subfiles["lips.txt"].append(u)
                        elif "blush" in u_lower:
                            makeup_subfiles["blush.txt"].append(u)
                        elif "eyeshadow" in u_lower:
                            makeup_subfiles["eyeshadow.txt"].append(u)
                        elif "eyeliner" in u_lower or "liner" in u_lower:
                            makeup_subfiles["eyeliner.txt"].append(u)
                        else:
                            makeup_subfiles["makeup_other.txt"].append(u)
                        
                    # Escribir cada sub-archivo
                    for fname, sub_urls in makeup_subfiles.items():
                        if sub_urls:
                            fpath = os.path.join(folder_path, fname)
                            try:
                                with open(fpath, 'a', encoding='utf-8') as f:
                                    for u in sub_urls: f.write(u + "\n")
                            except Exception as e:
                                self.log_copy(f"Error escribiendo {fname}: {e}")
                    
                    created_count += len(urls)

                else:
                    target_file_path = os.path.join(RUTA_NOTEPADS, f"{cat}.txt")

                    with open(target_file_path, 'a', encoding='utf-8') as f:
                        for u in urls: f.write(u + "\n")
                    created_count += len(urls)

            # Reescribir uncategorized solo con lo que sobró
            with open(path_all, 'w', encoding='utf-8') as f:
                f.write("\n".join(uncat_buffer))
            
            if not uncat_buffer:
                os.remove(path_all)
                self.log_copy("✨ uncategorized.txt ha quedado vacío y se eliminó.")

            self.log_copy(f"✅ Categorización completada. {created_count} URLs movidas.")
            self.actualizar_visor_notepad()

        except Exception as e:
            self.log_copy(f"❌ Error crítico en categorización: {e}")

    def verificar_duplicados_txt(self):
        # Esta función era informativa post-proceso, la mantenemos
        pass # La lógica fuerte está en el pre-scan ahora

    def actualizar_visor_notepad(self):
        for w in self.notepad_list_frame.winfo_children(): w.destroy()
        if not os.path.exists(RUTA_NOTEPADS): return
        # Recorrer recursivamente para encontrar makeup/makeup.txt también
        files = glob.glob(os.path.join(RUTA_NOTEPADS, "**", "*.txt"), recursive=True)
        files.sort()
        for f in files:
            name = os.path.relpath(f, RUTA_NOTEPADS)
            btn = ctk.CTkButton(self.notepad_list_frame, text=name, fg_color="transparent", border_width=1, text_color="black", command=lambda p=f: self.cargar_preview_notepad(p))
            btn.pack(fill="x", pady=1)

    def cargar_preview_notepad(self, path):
        """Carga el contenido y actualiza el contador de líneas y estado de borrado."""
        self.current_notepad_path = path  # Guardamos referencia para borrar
        self.btn_delete_notepad.configure(state="normal")  # Habilitar botón borrar

        try:
            with open(path, 'r', encoding='utf-8') as f: 
                lines = f.readlines()
                content = "".join(lines)
            
            # --- NUEVO: Actualizar conteo visual ---
            count = len(lines)
            self.lbl_notepad_lines.configure(text=f"Líneas totales: {count}")
            
            self.notepad_preview_box.delete("1.0", "end")
            self.notepad_preview_box.insert("end", content)
        except Exception as e:
            self.lbl_notepad_lines.configure(text="Líneas totales: Error")
            self.notepad_preview_box.delete("1.0", "end")
            self.notepad_preview_box.insert("end", f"Error leyendo archivo: {e}")

    def eliminar_notepad_actual(self):
        """Elimina el archivo notepad seleccionado actualmente."""
        if not self.current_notepad_path or not os.path.exists(self.current_notepad_path):
            return

        nombre = os.path.basename(self.current_notepad_path)
        confirm = messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro que deseas eliminar el notepad:\n'{nombre}'?\n\nEsta acción no se puede deshacer.")
        
        if confirm:
            try:
                os.remove(self.current_notepad_path)
                self.log_copy(f"🗑️ Notepad eliminado: {nombre}")
                
                # Reset UI
                self.current_notepad_path = None
                self.notepad_preview_box.delete("1.0", "end")
                self.lbl_notepad_lines.configure(text="Líneas totales: --")
                self.btn_delete_notepad.configure(state="disabled")
                
                # Recargar lista
                self.actualizar_visor_notepad()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el archivo:\n{e}")

    # =========================================================================
    # LÓGICA DUPLICADOS (HASHING)
    # =========================================================================
    def log_dup(self, text):
        self.log_box_dup.configure(state="normal")
        self.log_box_dup.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {text}\n")
        self.log_box_dup.see("end")
        self.log_box_dup.configure(state="disabled")

    def calcular_hash(self, filepath):
        hasher = hashlib.md5()
        try:
            with open(filepath, 'rb') as f:
                buf = f.read(65536) 
                while len(buf) > 0: hasher.update(buf); buf = f.read(65536)
            return hasher.hexdigest()
        except: return None

    def iniciar_escaneo_duplicados(self):
        self.btn_scan_dup.configure(state="disabled", text="Escaneando...")
        self.btn_del_dup.configure(state="disabled")
        self.log_box_dup.configure(state="normal")
        self.log_box_dup.delete("1.0", "end")
        self.log_box_dup.configure(state="disabled")
        threading.Thread(target=self.thread_escaneo, daemon=True).start()

    def thread_escaneo(self):
        # USAMOS LA RUTA ESPECÍFICA DE DUPLICADOS
        ruta_objetivo = self.duplicate_scan_path # <--- CAMBIO
        self.log_dup(f"🚀 Iniciando escaneo en: {ruta_objetivo}")
        hashes = {}; self.duplicate_groups = [] 
        for widget in self.dup_list_frame.winfo_children(): widget.destroy()
        for widget in self.dup_filters_frame.winfo_children(): widget.destroy()
        
        # Reset progress
        self.dup_progress_bar.set(0)
        self.lbl_dup_progress.configure(text="Progreso: 0%")

        if not os.path.exists(ruta_objetivo):
            self.log_dup(f"⚠️ Carpeta de escaneo no existe: {ruta_objetivo}")
            self.reset_dup_ui(); return

        archivos = glob.glob(os.path.join(ruta_objetivo, "**", "*.package"), recursive=True)
        total_files = len(archivos)
        self.log_dup(f"📂 Analizando {total_files} archivos .package...")
        
        count = 0
        for f in archivos:
            h = self.calcular_hash(f)
            if h:
                if h in hashes: hashes[h].append(f)
                else: hashes[h] = [f]
            count += 1
            
            # --- Update Progress ---
            if total_files > 0:
                prog = count / total_files
                self.dup_progress_bar.set(prog)
                self.lbl_dup_progress.configure(text=f"Progreso: {int(prog * 100)}%")
            # -----------------------

            if count % 50 == 0: self.log_dup(f"Analizados: {count}/{total_files}...")

        group_id = 1
        for h, paths in hashes.items():
            if len(paths) > 1:
                paths.sort(key=os.path.getctime)
                nombre_grupo = os.path.basename(paths[0])
                self.duplicate_groups.append({"id": group_id, "name": nombre_grupo, "files": paths})
                group_id += 1

        self.log_dup(f"✅ Escaneo completado. {len(self.duplicate_groups)} grupos de duplicados encontrados.")
        # Finalize progress
        self.dup_progress_bar.set(1)
        self.lbl_dup_progress.configure(text="Progreso: 100%")
        self.after(0, lambda: self.mostrar_resultados_dup(self.duplicate_groups))

    def mostrar_resultados_dup(self, groups):
        self.duplicate_vars = []
        for w in self.dup_filters_frame.winfo_children(): w.destroy()
        
        if not groups:
            lbl = ctk.CTkLabel(self.dup_list_frame, text="¡Felicidades! No se encontraron duplicados.", text_color="green")
            lbl.pack(pady=20); self.reset_dup_ui(); return

        ctk.CTkButton(self.dup_filters_frame, text="Todos", width=60, fg_color="#229A65", command=lambda: self.render_duplicate_list(groups)).pack(side="left", padx=2)
        for g in groups:
            self.log_dup(f"{g['id']}- {g['name']}")
            ctk.CTkButton(self.dup_filters_frame, text=str(g['id']), width=40, command=lambda grupo=g: self.render_duplicate_list([grupo])).pack(side="left", padx=2)

        self.btn_del_dup.configure(state="normal")
        self.reset_dup_ui()
        self.render_duplicate_list(groups)

    def render_duplicate_list(self, groups_to_show):
        for widget in self.dup_list_frame.winfo_children(): widget.destroy()
        self.duplicate_vars = [] 
        for g in groups_to_show:
            header_frame = ctk.CTkFrame(self.dup_list_frame, fg_color="#DDDDDD") 
            header_frame.pack(fill="x", pady=(10, 2), padx=5)
            ctk.CTkLabel(header_frame, text=f"Grupo {g['id']}: {g['name']}", text_color="black", font=("Arial", 12, "bold")).pack(anchor="w", padx=5)
            for ruta in g['files']:
                nombre = os.path.basename(ruta)
                carpeta = os.path.basename(os.path.dirname(ruta))
                size_kb = os.path.getsize(ruta) / 1024
                frame_item = ctk.CTkFrame(self.dup_list_frame)
                frame_item.pack(fill="x", pady=1, padx=15) 
                var = ctk.BooleanVar(value=False)
                chk = ctk.CTkCheckBox(frame_item, text=f"{nombre}", variable=var)
                chk.pack(side="left", padx=5)
                lbl_info = ctk.CTkLabel(frame_item, text=f"Carpeta: /{carpeta} | Peso: {size_kb:.0f} KB", text_color="gray", font=("Arial", 11))
                lbl_info.pack(side="right", padx=10)
                self.duplicate_vars.append({"path": ruta, "var": var, "widget": frame_item})

    def reset_dup_ui(self):
        self.btn_scan_dup.configure(state="normal", text="🔍 Buscar Duplicados Ahora")

    def eliminar_duplicados(self):
        count_deleted = 0; to_delete_widgets = []
        for item in self.duplicate_vars:
            if item["var"].get():
                try:
                    os.remove(item["path"]); count_deleted += 1; to_delete_widgets.append(item["widget"])
                except Exception as e: self.log_dup(f"Error borrando {os.path.basename(item['path'])}: {e}")
        for w in to_delete_widgets: w.destroy()
        if count_deleted > 0:
            self.log_dup(f"🗑️ Se eliminaron {count_deleted} archivos.")
            messagebox.showinfo("Limpieza", f"Se eliminaron {count_deleted} archivos.")
            self.loop_actualizar_carpetas()
        else: messagebox.showwarning("Aviso", "No seleccionaste ningún archivo para borrar.")

    # =========================================================================
    # LÓGICA GENERAL
    # =========================================================================
    def actualizar_layout(self, value):
        try:
            val_logs = int(value); val_monitor = 10 - val_logs
            self.tab_descargas.grid_rowconfigure(2, weight=val_logs)
            self.tab_descargas.grid_rowconfigure(10, weight=val_monitor)
        except: pass

    def crear_boton_log(self, nombre_canal, select=False):
        if nombre_canal in self.log_buttons: return 
        if nombre_canal not in self.log_data: self.log_data[nombre_canal] = ""
        texto_boton = "🏠 INICIO" if nombre_canal == "Inicio" else f"📂 {nombre_canal}"
        btn = ctk.CTkButton(self.log_tabs_frame, text=texto_boton, width=100, height=25, fg_color="#3B8ED0", command=lambda c=nombre_canal: self.cambiar_vista_log(c))
        btn.pack(side="left", padx=2, pady=2)
        self.log_buttons[nombre_canal] = btn
        if select: self.cambiar_vista_log(nombre_canal)

    def cambiar_vista_log(self, canal):
        self.current_log_view = canal
        for c, btn in self.log_buttons.items(): btn.configure(fg_color="#229A65" if c == canal else "#3B8ED0")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", self.log_data[canal])
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def log(self, text, channel=None):
        target_channel = channel if channel else "Inicio"
        timestamp = datetime.datetime.now().strftime("[%H:%M:%S]")
        msg = f"{timestamp} {text}\n"
        if target_channel not in self.log_data: self.log_data[target_channel] = ""
        self.log_data[target_channel] += msg
        print(f"[{target_channel}] {msg.strip()}")
        if self.log_box is not None and target_channel == self.current_log_view:
            self.log_box.configure(state="normal"); self.log_box.insert("end", msg); self.log_box.see("end"); self.log_box.configure(state="disabled")

    def tomar_foto_inicial(self):
        self.files_at_start = set()
        # AHORA USA LA RUTA DINÁMICA
        if os.path.exists(self.download_root_path):
            patron = os.path.join(self.download_root_path, "**", "*.package")
            archivos = glob.glob(patron, recursive=True)
            self.files_at_start = set(os.path.abspath(f) for f in archivos)
        self.log(f"📊 Estado inicial: {len(self.files_at_start)} archivos en destino.", channel="Inicio")

    def abrir_selector_categorias(self):
        if not self.available_filenames: messagebox.showwarning("Aviso", "No hay archivos .txt disponibles."); return
        top = ctk.CTkToplevel(self); top.title("Seleccionar Categorías"); top.geometry("400x500"); top.transient(self); top.grab_set(); top.focus_force()
        ctk.CTkLabel(top, text="Marque los archivos que desea procesar:", font=("Arial", 14, "bold")).pack(pady=10)
        scroll = ctk.CTkScrollableFrame(top); scroll.pack(fill="both", expand=True, padx=20, pady=10)
        checkboxes_vars = {} 
        for nombre in self.available_filenames:
            var = ctk.BooleanVar(value=False)
            if nombre in self.selected_files_specific: var.set(True)
            chk = ctk.CTkCheckBox(scroll, text=nombre, variable=var); chk.pack(anchor="w", pady=5)
            checkboxes_vars[nombre] = var
        def confirmar_seleccion():
            seleccionados = []
            for nombre, var in checkboxes_vars.items():
                if var.get(): seleccionados.append(nombre)
            self.selected_files_specific = seleccionados
            count = len(self.selected_files_specific)
            if count == 0: self.lbl_selection_info.configure(text="(Ninguno seleccionado)", text_color="red")
            else: self.lbl_selection_info.configure(text=f"✅ {count} archivos seleccionados", text_color="green")
            top.destroy()
        btn_frame = ctk.CTkFrame(top, fg_color="transparent"); btn_frame.pack(pady=20)
        ctk.CTkButton(btn_frame, text="Confirmar Selección", command=confirmar_seleccion, fg_color="#2CC985").pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Cancelar", command=top.destroy, fg_color="gray").pack(side="left", padx=10)

    def cambiar_tema(self):
        if self.switch_theme.get() == 1: 
            ctk.set_appearance_mode("Dark")
            self.log("🌙 Modo Oscuro activado.", channel="Inicio")
            self.user_prefs["modo_oscuro"] = True
        else: 
            ctk.set_appearance_mode("Light")
            self.log("☀️ Modo Claro activado.", channel="Inicio")
            self.user_prefs["modo_oscuro"] = False
        self.guardar_preferencias_usuario()

    def toggle_always_on_top(self):
        if self.check_top.get() == 1: 
            self.attributes("-topmost", True)
            self.log("📌 Ventana fijada al frente.", channel="Inicio")
            self.user_prefs["siempre_visible"] = True
        else: 
            self.attributes("-topmost", False)
            self.log("📌 Ventana liberada.", channel="Inicio")
            self.user_prefs["siempre_visible"] = False
        self.guardar_preferencias_usuario()

    def reproducir_sonido(self):
        if self.check_sound.get() == 1:
            try: winsound.Beep(1000, 600); time.sleep(0.1); winsound.Beep(1500, 300) 
            except: pass

    def toggle_pause(self):
        if not self.running: return
        if not self.paused:
            self.paused = True; self.pause_event.clear()
            self.btn_pause.configure(text="▶ REANUDAR", fg_color="#3B8ED0") 
            self.lbl_progress_title.configure(text=self.lbl_progress_title.cget("text") + " (PAUSADO)", text_color="orange")
            self.log("⏸️ PROCESO PAUSADO.", channel="Inicio") 
        else:
            self.paused = False; self.pause_event.set()
            self.btn_pause.configure(text="⏸️ PAUSAR", fg_color="#FFA500") 
            texto_actual = self.lbl_progress_title.cget("text").replace(" (PAUSADO)", "")
            self.lbl_progress_title.configure(text=texto_actual, text_color="#2CC985")
            self.log("▶ REANUDANDO proceso...", channel="Inicio")

    def iniciar_cuenta_regresiva(self, segundos_totales):
        self.time_left = segundos_totales; self.timer_active = True; self.lbl_timer.configure(text_color="blue"); self.actualizar_reloj()

    def actualizar_reloj(self):
        if not self.timer_active or not self.running: return
        if self.paused: self.after(1000, self.actualizar_reloj); return
        if self.time_left > 0:
            minutos = self.time_left // 60; segundos = self.time_left % 60
            self.lbl_timer.configure(text=f"Tiempo Estimado: {minutos:02}:{segundos:02}")
            self.time_left -= 1
            self.after(1000, self.actualizar_reloj)
        else: self.lbl_timer.configure(text="Finalizando descargas...", text_color="orange")

    def detener_reloj(self):
        self.timer_active = False; self.lbl_timer.configure(text="--:--", text_color="gray")

    def abrir_carpeta_actual(self):
        if self.current_dest_folder and os.path.exists(self.current_dest_folder):
            try: os.startfile(self.current_dest_folder); self.log(f"📂 Abriendo carpeta: {os.path.basename(self.current_dest_folder)}", channel="Inicio")
            except Exception as e: self.log(f"❌ Error al abrir: {e}", channel="Inicio")
        else: messagebox.showwarning("Error", "Carpeta no válida.")

    def fijar_vista_monitor(self, ruta):
        if os.path.exists(ruta):
            self.current_dest_folder = ruta; self.last_files_state = None 
            nombre_carpeta = os.path.basename(ruta)
            self.lbl_path_debug.configure(text=f"Viendo: .../{nombre_carpeta}")
            self.log(f"👁️ Visualizando: {nombre_carpeta}", channel="Inicio")
            self.btn_open_folder.configure(state="normal", fg_color="#3B8ED0") 
            self.update_file_monitor()
        else:
            self.log(f"⚠️ Carpeta no encontrada: {ruta}", channel="Inicio")
            self.btn_open_folder.configure(state="disabled", fg_color="#555")

    def loop_actualizar_carpetas(self):
        # AHORA USA LA RUTA DINÁMICA
        if not os.path.exists(self.download_root_path):
            try: os.makedirs(self.download_root_path)
            except: pass
        try:
            items_en_disco = os.listdir(self.download_root_path)
            carpetas_disco = set([d for d in items_en_disco if os.path.isdir(os.path.join(self.download_root_path, d))])
            patron_all = os.path.join(self.download_root_path, "**", "*.package")
            archivos_actuales_lista = glob.glob(patron_all, recursive=True)
            archivos_actuales_set = set(os.path.abspath(f) for f in archivos_actuales_lista)
            archivos_nuevos = archivos_actuales_set - self.files_at_start
            peso_total = sum(os.path.getsize(f) for f in archivos_nuevos) / (1024 * 1024)
            self.lbl_stats_count.configure(text=f"📦 Archivos: {len(archivos_nuevos)}")
            self.lbl_stats_size.configure(text=f"💾 Peso Sesión: {peso_total:.1f} MB")
        except: carpetas_disco = set()

        carpetas_en_gui = set(self.folder_widgets.keys())
        for carpeta_borrada in (carpetas_en_gui - carpetas_disco):
            widgets = self.folder_widgets[carpeta_borrada]
            widgets["container"].destroy()
            del self.folder_widgets[carpeta_borrada]

        nuevas_carpetas = sorted(list(carpetas_disco - carpetas_en_gui))
        for carpeta in nuevas_carpetas:
            ruta_completa = os.path.join(self.download_root_path, carpeta)
            container = ctk.CTkFrame(self.nav_buttons_frame, fg_color="transparent")
            container.pack(side="left", padx=5, pady=2)
            
            lbl_count = ctk.CTkLabel(container, text="...", font=("Arial", 11, "bold"), text_color="gray")
            lbl_count.pack(side="top", pady=(0, 0)) # Reducimos padding para acercar etiquetas
            
            # --- NUEVA ETIQUETA PARA EL TAMAÑO ---
            lbl_size = ctk.CTkLabel(container, text="...", font=("Arial", 10), text_color="#E67E22")
            lbl_size.pack(side="top", pady=(0, 2))

            btn = ctk.CTkButton(container, text=f"📂 {carpeta}", width=110, fg_color="#3B8ED0", hover_color="#1F6AA5", command=lambda p=ruta_completa: self.fijar_vista_monitor(p))
            btn.pack(side="bottom")
            
            # Guardamos ambas etiquetas en el diccionario
            self.folder_widgets[carpeta] = {"container": container, "label": lbl_count, "label_size": lbl_size}

        for carpeta in self.folder_widgets:
            ruta = os.path.join(self.download_root_path, carpeta)
            try:
                # --- MODIFICACIÓN SOLICITADA POR USUARIO ---
                # Lógica recursiva: Contar .package en carpeta + subcarpetas
                cantidad = 0
                total_size = 0
                
                # os.walk recorre todo el árbol de directorios hacia abajo
                for dirpath, _, filenames in os.walk(ruta):
                    for f in filenames:
                        # Ruta completa del archivo
                        fp = os.path.join(dirpath, f)
                        
                        # 1. Contar si es .package (insensible a mayúsculas)
                        if f.lower().endswith(".package"):
                            cantidad += 1
                        
                        # 2. Calcular peso total (excluyendo enlaces simbólicos)
                        if not os.path.islink(fp):
                            total_size += os.path.getsize(fp)
                
                # Formateo de tamaño
                size_mb = total_size / (1024 * 1024)
                if size_mb < 1000:
                    str_size = f"{size_mb:.1f} MB"
                else:
                    str_size = f"{size_mb / 1024:.2f} GB"

                # Actualizar etiquetas
                lbl = self.folder_widgets[carpeta]["label"]
                lbl_sz = self.folder_widgets[carpeta]["label_size"]
                
                if cantidad > 0: 
                    lbl.configure(text=f"{cantidad} archivos", text_color="#2CC985")
                else: 
                    lbl.configure(text="Vacío", text_color="gray")
                
                lbl_sz.configure(text=str_size)

            except: pass
        self.after(2000, self.loop_actualizar_carpetas)

    def check_mode(self):
        if self.radio_var.get() == 2: self.btn_select_custom.configure(state="normal", fg_color="#3B8ED0")
        else: self.btn_select_custom.configure(state="disabled", fg_color="gray"); self.lbl_selection_info.configure(text="(Modo TODO activo)", text_color="gray")

    # =========================================================================
    #  MODOS DE EJECUCIÓN: LECTURA Y DESCUBRIMIENTO DE ARCHIVOS (RECURSIVO)
    # =========================================================================

    def refresh_dropdown_options(self):
        """
        [MODIFICADO] Escanea recursivamente la carpeta RUTA_NOTEPADS y todas sus subcarpetas
        buscando archivos que terminen en .txt.
        Genera una lista de rutas relativas para identificar los archivos únicos.
        """
        found_files = []
        
        # Verificamos que la carpeta base exista para evitar errores
        if os.path.exists(RUTA_NOTEPADS):
            # os.walk recorre el árbol de directorios de arriba a abajo
            # root: carpeta actual en la iteración
            # dirs: subcarpetas en la carpeta actual
            # files: archivos en la carpeta actual
            for root, dirs, files in os.walk(RUTA_NOTEPADS):
                for file in files:
                    # Filtramos exclusivamente los archivos .txt
                    if file.lower().endswith(".txt"):
                        # Construimos la ruta absoluta temporalmente
                        full_path = os.path.join(root, file)
                        
                        # Calculamos la ruta relativa respecto a RUTA_NOTEPADS
                        # Ejemplo: si el archivo es ".../NOTEPAD/makeup/lips.txt",
                        # rel_path será "makeup/lips.txt".
                        # Esto permite diferenciar archivos con el mismo nombre en distintas carpetas.
                        try:
                            rel_path = os.path.relpath(full_path, RUTA_NOTEPADS)
                            found_files.append(rel_path)
                        except ValueError:
                            # Fallback por si hay problemas de rutas en sistemas mixtos
                            pass

        # Ordenamos alfabéticamente para mantener el orden A-Z
        found_files.sort()
        
        # Actualizamos la variable que nutre la interfaz y el selector
        self.available_filenames = found_files
        
        self.log(f"✅ Lista recargada (Recursiva): {len(found_files)} archivos .txt detectados.", channel="Inicio")
        
        # Refrescamos el estado de los botones (UI)
        self.check_mode()

    def obtener_archivos(self):
        """
        [MODIFICADO] Prepara la lista de archivos a procesar basándose en el modo seleccionado.
        Maneja correctamente las rutas relativas de las subcarpetas para la lectura.
        """
        validos = []
        
        # Si la carpeta principal no existe, retornamos lista vacía
        if not os.path.exists(RUTA_NOTEPADS):
            return []

        # Determinamos la lista objetivo según el modo (Todo vs Selección)
        # Nota: 'targets' contiene las rutas relativas (ej: "carpeta/archivo.txt")
        targets = self.available_filenames if self.radio_var.get() == 1 else self.selected_files_specific

        for nombre_relativo in targets:
            # Reconstruimos la ruta completa segura uniendo la base con el nombre relativo
            ruta_completa = os.path.join(RUTA_NOTEPADS, nombre_relativo)

            # Verificamos existencia física antes de intentar abrir
            if os.path.exists(ruta_completa):
                try:
                    with open(ruta_completa, 'r', encoding='utf-8') as f:
                        # Leemos y limpiamos las líneas
                        lineas_crudas = [l.strip() for l in f.readlines() if l.strip()]
                        lineas_validas = []
                        
                        # Mantenemos la lógica original de filtrado de URLs
                        for l in lineas_crudas:
                            if l.lower().startswith(('http', 'www')):
                                lineas_validas.append(l)
                            else:
                                self.log(f"⚠️ Omitida (No URL): {l[:20]}...", channel="Inicio")

                        # Solo agregamos el archivo si tiene contenido válido
                        if lineas_validas:
                            validos.append({
                                "nombre": nombre_relativo, # Usamos el relativo para identificarlo en logs
                                "lineas": len(lineas_validas),
                                "ruta": ruta_completa,
                                "contenido": lineas_validas
                            })
                        else:
                            self.log(f"⚠️ {nombre_relativo} omitido (Sin URLs válidas).", channel="Inicio")
                            
                except Exception as e:
                    self.log(f"❌ Error leyendo {nombre_relativo}: {e}", channel="Inicio")
            else:
                self.log(f"⚠️ Archivo no encontrado (¿Movido?): {ruta_completa}", channel="Inicio")

        return validos

    def ejecutar_setup(self, nombre_categoria):
        # --- PASO 1: Validación ---
        entrada = nombre_categoria.replace(".txt", "")
        nombre_carpeta = ""
        
        # Permitimos letras, números, espacios, guiones, y separadores de carpeta (\ y /)
        if re.match(r'^[A-Za-z0-9 _\-\\/]+$', entrada):
            nombre_carpeta = entrada.lower()
        else:
            self.log(f"❌ INCORRECTO: '{entrada}' contiene caracteres no permitidos.", channel="Inicio")
            return None

        # --- PASO 2: Crear la carpeta USANDO LA RUTA DINÁMICA ---
        # AQUÍ ESTÁ EL CAMBIO CLAVE: Usa self.download_root_path en lugar de la ruta fija
        ruta_nueva_carpeta = os.path.join(self.download_root_path, nombre_carpeta)

        try:
            os.makedirs(ruta_nueva_carpeta, exist_ok=True)
            self.log(f"✅ Carpeta creada en: {ruta_nueva_carpeta}", channel="Inicio")
        except Exception as e:
            self.log(f"Error al crear la carpeta: {e}", channel="Inicio")
            return None

        # --- PASO 3: Modificar el config.json TEMPORALMENTE ---
        # Se modifica el config.json del script para que descargue en la subcarpeta
        # PERO NO TOCAMOS self.download_root_path NI user_prefs
        self.actualizar_archivo_config_json_script(ruta_nueva_carpeta)
            
        self.current_dest_folder = os.path.abspath(ruta_nueva_carpeta)
        return self.current_dest_folder

    def start_thread(self):
        if self.running: return
        if self.radio_var.get() == 2 and not self.selected_files_specific: messagebox.showerror("Error", "No has seleccionado ningún archivo."); return
        if not self.available_filenames: messagebox.showerror("Error", "No hay archivos en la carpeta NOTEPAD."); return
        self.running = True; self.paused = False; self.pause_event.set()
        self.btn_start.configure(state="disabled", text="EJECUTANDO...")
        self.btn_stop.configure(state="normal")
        self.btn_pause.configure(state="normal", text="⏸️ PAUSAR", fg_color="#FFA500")
        self.radio_all.configure(state="disabled"); self.radio_spec.configure(state="disabled")
        self.btn_select_custom.configure(state="disabled"); self.btn_reload.configure(state="disabled")
        self.switch_theme.configure(state="disabled")
        self.cambiar_vista_log("Inicio")
        self.log("🚀 INICIANDO PROCESO GENERAL", channel="Inicio")
        threading.Thread(target=self.proceso_principal, daemon=True).start()

    def stop_process(self):
        self.running = False; self.paused = False; self.pause_event.set()
        self.log("⚠️ DETENCIÓN SOLICITADA.", channel="Inicio")

    def proceso_principal(self):
        try:
            archivos = self.obtener_archivos()
            if not archivos: self.log("❌ Sin archivos válidos.", channel="Inicio"); self.reset_ui(); return
            lista = sorted(archivos, key=lambda x: x["nombre"])
            try: segundos = int(float(self.entry_delay.get()))
            except: segundos = 0

            for item in lista:
                if not self.running: break
                nombre_archivo = item["nombre"]; nombre_simple = nombre_archivo.replace(".txt", ""); total = item["lineas"]; contenido = item["contenido"]
                self.after(0, lambda n=nombre_simple: self.crear_boton_log(n, select=True)); time.sleep(0.1)
                self.log(f"▶ Procesando: {nombre_archivo}", channel="Inicio")
                self.log(f"=== {nombre_simple} ===", channel=nombre_simple)
                self.progress_bar.set(0)
                self.lbl_progress_title.configure(text=f"Progreso: 0/{total} - {nombre_simple}", text_color="blue")
                tiempo_estimado = (total * segundos) + 20
                self.after(0, lambda t=tiempo_estimado: self.iniciar_cuenta_regresiva(t))
                self.pause_event.wait()
                if not self.running: break
                destino_actual = self.ejecutar_setup(nombre_archivo)
                if not destino_actual: self.detener_reloj(); continue
                self.log("🚀 Ejecutando script de descarga...", channel=nombre_simple)
                env_utf8 = os.environ.copy(); env_utf8["PYTHONIOENCODING"] = "utf-8"
                self.current_process = subprocess.Popen(["python", "main.py"], cwd=RUTA_CARPETA_MAIN, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, encoding='utf-8', errors='replace', env=env_utf8)
                descarga_ok = threading.Event()
                actividad_script = {"ts": time.monotonic()}
                def leer_salida(proc, evento, canal):
                    l = ""
                    for line in iter(proc.stdout.readline, ''):
                        if line:
                            actividad_script["ts"] = time.monotonic()
                            l = line.strip()
                            self.log(f"[Script]: {l}", channel=canal)
                        if "[INFO] All downloads have been completed" in l: evento.set()
                def leer_errores(proc, canal):
                    for line in iter(proc.stderr.readline, ''):
                        if line:
                            actividad_script["ts"] = time.monotonic()
                            self.log(f"[Script-ERR]: {line.strip()}", channel=canal)
                t_mon = threading.Thread(target=leer_salida, args=(self.current_process, descarga_ok, nombre_simple), daemon=True); t_mon.start()
                threading.Thread(target=leer_errores, args=(self.current_process, nombre_simple), daemon=True).start()
                self.log("⏳ Esperando carga inicial (10s)...", channel=nombre_simple)
                for _ in range(10): 
                    if not self.running: break
                    self.pause_event.wait(); time.sleep(1)
                self.log(f"📋 Copiando enlaces al portapapeles...", channel=nombre_simple)
                self.lbl_progress_title.configure(text=f"Copiando... {nombre_simple}", text_color="#2CC985")
                for i, linea in enumerate(contenido):
                    self.pause_event.wait()
                    if not self.running: break
                    pyperclip.copy(linea)
                    url_display = linea if len(linea) < 95 else "..." + linea[-90:]
                    self.lbl_url_display.configure(text=url_display) 
                    self.log(f"Copiado ({i+1}/{total}): {linea[:30]}...", channel=nombre_simple)
                    progreso_actual = (i + 1) / total
                    self.progress_bar.set(progreso_actual)
                    self.lbl_progress_title.configure(text=f"Copiando: {i + 1}/{total} ({int(progreso_actual * 100)}%)")
                    if segundos > 0: time.sleep(segundos)
                self.lbl_progress_title.configure(text=f"Esperando finalización... {nombre_simple}", text_color="orange")
                self.log("Esperando confirmación de descarga completa...", channel=nombre_simple)
                while not descarga_ok.is_set():
                    if not self.running: break
                    if self.current_process.poll() is not None: self.log("⚠️ El script terminó inesperadamente.", channel=nombre_simple); break
                    self.pause_event.wait(); time.sleep(1)
                if self.running and descarga_ok.is_set() and self.current_process and self.current_process.poll() is None:
                    self.log("Esperando que el downloader vacie procesos internos...", channel=nombre_simple)
                    inicio_gracia = time.monotonic()
                    while time.monotonic() - inicio_gracia < 15:
                        if self.current_process.poll() is not None:
                            break
                        if time.monotonic() - actividad_script["ts"] >= 3:
                            break
                        self.pause_event.wait()
                        time.sleep(0.5)
                self.kill_current_process()
                self.log("🔪 Proceso de descarga terminado (Killed).", channel=nombre_simple)
                self.log(f"✅ Finalizado: {nombre_archivo}", channel="Inicio")
                self.detener_reloj(); pyperclip.copy(""); self.lbl_url_display.configure(text="")
                self.progress_bar.set(1); self.lbl_progress_title.configure(text=f"Completado: {nombre_simple}", text_color="green")

            if self.running:
                self.log("✨ FIN GLOBAL ✨", channel="Inicio")
                self.cambiar_vista_log("Inicio") 
                self.lbl_progress_title.configure(text=f"✅ Proceso Global Finalizado", text_color="green")
                self.detener_reloj(); self.reproducir_sonido() 
                
                # --- AUTO-SCAN DUPLICADOS ---
                if self.check_autodup.get() == 1:
                    # LÓGICA DE PROTECCIÓN (SOLICITADA)
                    # Si la ruta actual de escaneo es diferente a la de descargas, se resetea.
                    if self.duplicate_scan_path != self.download_root_path:
                        self.log("🔄 Auto-Scan: Ruta personalizada detectada. Restableciendo a Default...", channel="Inicio")
                        self.duplicate_scan_path = self.download_root_path
                        self.log_dup(f"📍 Auto-reset a: {self.duplicate_scan_path}")

                    self.log("🔄 Iniciando Auto-Scan de Duplicados...", channel="Inicio")
                    self.tabview.set("♻️ DUPLICADOS")
                    self.iniciar_escaneo_duplicados()

                if self.check_popup.get() == 1: messagebox.showinfo("Sims Downloader", "Proceso GLOBAL finalizado.")

        except Exception as e: self.log(f"❌ ERROR CRÍTICO: {e}", channel="Inicio"); import traceback; traceback.print_exc()
        finally: self.kill_current_process(); self.detener_reloj(); self.reset_ui(); pyperclip.copy(""); self.lbl_url_display.configure(text="")

    def kill_current_process(self):
        if self.current_process:
            try: self.current_process.terminate()
            except: pass
            self.current_process = None

    def reset_ui(self):
        self.running = False; self.paused = False; self.pause_event.set()
        self.btn_start.configure(state="normal", text="INICIAR PROCESO")
        self.btn_stop.configure(state="disabled")
        self.btn_pause.configure(state="disabled", text="⏸️ PAUSAR", fg_color="#FFA500")
        self.btn_reload.configure(state="normal"); self.radio_all.configure(state="normal"); self.radio_spec.configure(state="normal")
        self.check_mode(); self.switch_theme.configure(state="normal"); self.lbl_url_display.configure(text="")

    def update_file_monitor(self):
        if self.current_dest_folder:
            if os.path.exists(self.current_dest_folder):
                pattern = os.path.join(self.current_dest_folder, "*.package")
                archivos = glob.glob(pattern)
                try: archivos.sort(key=os.path.getmtime, reverse=True)
                except: pass
                estado_actual = []
                for f in archivos[:60]:
                    try: estado_actual.append((os.path.basename(f), os.path.getsize(f)))
                    except: pass
                if estado_actual != self.last_files_state:
                    self.last_files_state = estado_actual
                    for w in self.file_list_frame.winfo_children(): w.destroy()
                    if not estado_actual: ctk.CTkLabel(self.file_list_frame, text="(Carpeta vacía de .packages)", text_color="gray").pack(pady=5)
                    else:
                        for nombre, size in estado_actual:
                            size_kb = size / 1024
                            ctk.CTkLabel(self.file_list_frame, text=f"📦 {nombre} ({size_kb:.0f} KB)", anchor="w").pack(fill="x", padx=5)
            else:
                self.lbl_path_debug.configure(text="⚠️ Carpeta no encontrada.")
                self.btn_open_folder.configure(state="disabled", fg_color="#555") 
                if self.last_files_state != "ERROR":
                    self.last_files_state = "ERROR"
                    for widget in self.file_list_frame.winfo_children(): widget.destroy()
        else: self.lbl_path_debug.configure(text="Esperando selección...")
        self.after(1500, self.update_file_monitor)

def main():
    app = SimsOrchestratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
