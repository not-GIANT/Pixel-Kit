import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import os
import threading
import time
import json
import sys
from pathlib import Path

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

try:
    import customtkinter as ctk
except ImportError:
    messagebox.showerror("Dependency Error", "Please install customtkinter:\npip install customtkinter")
    exit()

# --- Constants & Configuration ---
IS_WINDOWS = os.name == 'nt'
WIN_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
PLATFORM_TOOLS_DIR = Path(resource_path("platform-tools"))
REQUIRED_TOOLS = ["adb", "fastboot", "scrcpy"]
CONFIG_FILE = Path("pixelkit_config.json")

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# --- Custom Tooltip Class ---
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.id = None
        self.widget.bind("<Enter>", self.schedule_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def schedule_tooltip(self, event):
        self.id = self.widget.after(500, self.show_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return
        
        x, y, _, _ = self.widget.bbox("insert") if hasattr(self.widget, "bbox") and self.widget.bbox("insert") else (0,0,0,0)
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        
        bg_color = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#e0e0e0"
        fg_color = "#ffffff" if ctk.get_appearance_mode() == "Dark" else "#000000"
        
        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background=bg_color, foreground=fg_color, relief='solid', borderwidth=1,
                         font=("Segoe UI", 9, "normal"))
        label.pack(ipadx=4, ipady=2)

    def hide_tooltip(self, event=None):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

# --- Core Application Class ---
class AndroidToolkit(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Pixel Kit - ADB & Fastboot Toolkit")
        self.status_running = False
        self.active_menu_frame = None
        self.current_process = None
        self.stop_event = __import__("threading").Event()
        
        self.config_data = self.load_config()
        self.current_theme = self.config_data.get("theme", "Dark")
        self.apply_theme(self.current_theme)
        
        pos = self.config_data.get("position", "1100x800+100+100")
        self.geometry(pos)
        self.minsize(1000, 750)
        
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(4, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self.create_header()
        self.create_device_info_panel()
        self.create_menu_frames()
        self.create_main_content()
        self.create_footer()

        self.check_tools_on_startup()
        self.start_status_checker()

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
        return {"theme": "Dark", "position": "1100x800+100+100"}

    def save_config(self):
        self.config_data["theme"] = self.current_theme
        self.config_data["position"] = self.geometry()
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config_data, f)
        except Exception as e:
            print(f"Error saving config: {e}")

    def apply_theme(self, theme_name):
        self.current_theme = theme_name
        ctk.set_appearance_mode(theme_name)
        if hasattr(self, 'console_output'):
            if theme_name == "Dark":
                self.console_output.tag_config("status", foreground="#00bcd4")
                self.console_output.tag_config("error", foreground="#f48fb1")
                self.console_output.tag_config("command_output", foreground="#4caf50")
            else:
                self.console_output.tag_config("status", foreground="#0097a7")
                self.console_output.tag_config("error", foreground="#d81b60")
                self.console_output.tag_config("command_output", foreground="#2e7d32")

    def create_header(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky='ew', padx=20, pady=20)
        header_frame.grid_columnconfigure(1, weight=1)

        menu_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        menu_frame.grid(row=0, column=0, sticky='w')
        
        btn_extras = ctk.CTkButton(menu_frame, text="Extras", width=90, command=self.toggle_extras_menu)
        btn_extras.pack(side='left', padx=5)
        ToolTip(btn_extras, "Extra tools and options")
        
        btn_theme = ctk.CTkButton(menu_frame, text="Theme", width=90, command=self.toggle_theme_menu)
        btn_theme.pack(side='left', padx=5)
        ToolTip(btn_theme, "Change the application theme")
        
        btn_about = ctk.CTkButton(menu_frame, text="About", width=90, command=self.show_about_window)
        btn_about.pack(side='left', padx=5)
        ToolTip(btn_about, "Information about the application")

        title_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_frame.grid(row=0, column=1, sticky='n')
        ctk.CTkLabel(title_frame, text="Pixel Kit", font=ctk.CTkFont(family="Fixedsys", size=36, weight="bold"), text_color="#00bcd4").pack()
        ctk.CTkLabel(title_frame, text="coded by GIANT", font=ctk.CTkFont(family="Fixedsys", size=16, weight="bold", slant="italic"), text_color="#ff5722").pack()

        status_container = ctk.CTkFrame(header_frame, fg_color="transparent")
        status_container.grid(row=0, column=2, sticky='e')
        
        btn_refresh = ctk.CTkButton(status_container, text="↻", width=40, height=40, font=ctk.CTkFont(size=20), 
                                    command=lambda: threading.Thread(target=self.update_device_status, daemon=True).start())
        btn_refresh.pack(side='left', padx=15)
        ToolTip(btn_refresh, "Refresh device status")
        
        self.status_label = ctk.CTkLabel(status_container, text="Disconnected", font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"), text_color="#f44336")
        self.status_label.pack(side='left')

    def create_device_info_panel(self):
        self.device_info_frame = ctk.CTkFrame(self)
        self.device_model_label = ctk.CTkLabel(self.device_info_frame, text="Model: N/A", font=ctk.CTkFont(size=14, weight="bold"))
        self.device_model_label.pack(side='left', expand=True, padx=20, pady=10)
        self.device_serial_label = ctk.CTkLabel(self.device_info_frame, text="Serial: N/A", font=ctk.CTkFont(size=14, weight="bold"))
        self.device_serial_label.pack(side='left', expand=True, padx=20, pady=10)

    def create_menu_frames(self):
        self.extras_menu_frame = ctk.CTkFrame(self)
        btn_drivers = ctk.CTkButton(self.extras_menu_frame, text="Install Drivers", width=150, height=35, command=self.install_drivers)
        btn_drivers.pack(side='left', padx=10, pady=10)
        ToolTip(btn_drivers, "Install necessary ADB/Fastboot drivers")
        
        btn_logs = ctk.CTkButton(self.extras_menu_frame, text="Save Logs", width=150, height=35, command=self.save_logs)
        btn_logs.pack(side='left', padx=10, pady=10)
        ToolTip(btn_logs, "Save console output to a text file")
        
        self.theme_menu_frame = ctk.CTkFrame(self)
        ctk.CTkButton(self.theme_menu_frame, text="Dark Mode", width=120, height=35, command=lambda: self.apply_theme("Dark")).pack(side='left', padx=10, pady=10)
        ctk.CTkButton(self.theme_menu_frame, text="Light Mode", width=120, height=35, command=lambda: self.apply_theme("Light")).pack(side='left', padx=10, pady=10)
        ctk.CTkButton(self.theme_menu_frame, text="System", width=120, height=35, command=lambda: self.apply_theme("System")).pack(side='left', padx=10, pady=10)

    def create_main_content(self):
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.grid(row=3, column=0, sticky='nsew', padx=20, pady=(0, 20))
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=2)
        
        # Left Side: Tab View for Commands and Flashing
        self.tab_view = ctk.CTkTabview(content_frame, command=self.on_tab_switch, corner_radius=15)
        self.tab_view.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        self.tab_view.add("ADB")
        self.tab_view.add("Fastboot")
        self.tab_view.add("Flashing Operations")
        
        self.tab_view._segmented_button.configure(font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"))
        
        self.adb_scroll_frame = ctk.CTkScrollableFrame(self.tab_view.tab("ADB"), fg_color=("gray85", "gray17"))
        self.adb_scroll_frame.pack(expand=True, fill='both')
        self.adb_scroll_frame.grid_columnconfigure(0, weight=1)
        
        self.fastboot_scroll_frame = ctk.CTkScrollableFrame(self.tab_view.tab("Fastboot"), fg_color=("gray85", "gray17"))
        self.fastboot_scroll_frame.pack(expand=True, fill='both')
        self.fastboot_scroll_frame.grid_columnconfigure(0, weight=1)
        
        self.flash_scroll_frame = ctk.CTkScrollableFrame(self.tab_view.tab("Flashing Operations"), fg_color=("gray85", "gray17"))
        self.flash_scroll_frame.pack(expand=True, fill='both')
        self.flash_scroll_frame.grid_columnconfigure(0, weight=1)
        
        self.create_adb_section(self.adb_scroll_frame)
        self.create_fastboot_section(self.fastboot_scroll_frame)
        self.create_flashing_section(self.flash_scroll_frame)
        
        # Right Side: Console Output
        console_frame = ctk.CTkFrame(content_frame)
        console_frame.grid(row=0, column=1, sticky='nsew')
        console_frame.grid_rowconfigure(1, weight=1)
        console_frame.grid_columnconfigure(0, weight=1)
        
        header_frame = ctk.CTkFrame(console_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky='ew', padx=15, pady=15)
        ctk.CTkLabel(header_frame, text="Command Matrix", font=ctk.CTkFont(size=18, weight="bold")).pack(side='left')
        
        btn_clear = ctk.CTkButton(header_frame, text="Clear", width=80, command=lambda: self.console_output.delete("1.0", tk.END), fg_color="#e53935", hover_color="#b71c1c")
        btn_clear.pack(side='right', padx=(5, 0))
        
        btn_stop = ctk.CTkButton(header_frame, text="Stop", width=80, command=self.stop_current_command, fg_color="#f57c00", hover_color="#e65100")
        btn_stop.pack(side='right')
        
        self.console_output = ctk.CTkTextbox(console_frame, font=ctk.CTkFont(family="Consolas", size=13), wrap="word")
        self.console_output.grid(row=1, column=0, sticky='nsew', padx=15, pady=(0, 15))
        
        self.apply_theme(self.current_theme)

    def create_adb_section(self, parent):
        adb_frame = ctk.CTkFrame(parent, fg_color="transparent")
        adb_frame.pack(expand=True, fill='both', pady=(0, 20))
        adb_frame.grid_columnconfigure((0, 1), weight=1)
        
        ctk.CTkLabel(adb_frame, text="ADB Operations", font=ctk.CTkFont(size=16, weight="bold"), text_color=("#00838f", "#00bcd4")).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
        
        left_col = ctk.CTkFrame(adb_frame, fg_color=("gray92", "gray14"), corner_radius=8, border_width=1, border_color=("gray80", "gray20"))
        left_col.grid(row=1, column=0, sticky='nsew', padx=(0, 5))
        left_col.grid_columnconfigure(0, weight=1)
        
        right_col = ctk.CTkFrame(adb_frame, fg_color=("gray92", "gray14"), corner_radius=8, border_width=1, border_color=("gray80", "gray20"))
        right_col.grid(row=1, column=1, sticky='nsew', padx=(5, 0))
        right_col.grid_columnconfigure(0, weight=1)

        left_actions = [
            ("List Devices", self.list_adb_devices, "List connected ADB devices"),
            ("Open Shell", lambda: self.run_command_threaded("adb", ['shell'], is_shell=True, task_name="Open Shell"), "Open an interactive ADB shell"),
            ("Install APK", self.install_apk, "Select and install an APK file"),
            ("Uninstall APK", self.uninstall_apk, "Uninstall an application package"),
            ("Sideload ZIP", self.adb_sideload, "Sideload an update ZIP"),
            ("Push File", self.adb_push, "Push a file to device"),
            ("Pull File", self.adb_pull, "Pull a file from device"),
            ("Reset EFS", self.reset_efs, "DANGEROUS: Wipes EFS partitions"),
            ("Start Scrcpy", self.start_scrcpy, "Mirror device screen")
        ]
        
        for i, (text, action, tip) in enumerate(left_actions):
            btn = ctk.CTkButton(left_col, text=text, command=action, height=35,
                                fg_color=("gray85", "gray22"), hover_color=("gray75", "gray30"), text_color=("black", "gray95"),
                                border_width=1, border_color=("gray70", "gray28"))
            btn.grid(row=i, column=0, padx=10, pady=5, sticky='ew')
            if i == 0: btn.grid(pady=(10, 5))
            if i == len(left_actions) - 1: btn.grid(pady=(5, 10))
            ToolTip(btn, tip)

        btn_reboot_menu = ctk.CTkButton(right_col, text="Reboot Menu", command=self.toggle_adb_reboot_menu, height=35,
                                        fg_color=("#00bcd4", "#00838f"), hover_color=("#00acc1", "#006064"), text_color=("black", "white"))
        btn_reboot_menu.grid(row=0, column=0, padx=10, pady=(10, 5), sticky='ew')
        ToolTip(btn_reboot_menu, "Show reboot options")
        
        self.adb_reboot_menu_frame = ctk.CTkFrame(right_col, fg_color="transparent")
        
        reboot_actions = [
            ("-> System", lambda: self.run_command_threaded("adb", ['reboot'], task_name="Reboot System"), "Reboot to Android OS"),
            ("-> Bootloader", lambda: self.run_command_threaded("adb", ['reboot', 'bootloader'], task_name="Reboot Bootloader"), "Reboot to bootloader/fastboot mode"),
            ("-> Recovery", lambda: self.run_command_threaded("adb", ['reboot', 'recovery'], task_name="Reboot Recovery"), "Reboot to recovery mode"),
            ("-> 💀 EDL", lambda: self.run_command_threaded("adb", ['reboot', 'edl'], task_name="Reboot EDL"), "DANGEROUS: Reboot to EDL mode")
        ]
        
        for text, action, tip in reboot_actions:
            btn = ctk.CTkButton(self.adb_reboot_menu_frame, text=text, command=action, height=30, 
                                fg_color=("#80deea", "#006064"), hover_color=("#4dd0e1", "#004d40"), text_color=("black", "white"),
                                border_width=1, border_color=("#00bcd4", "#00838f"))
            if "EDL" in text:
                btn.configure(fg_color=("#ef9a9a", "#b71c1c"), hover_color=("#e57373", "#880e4f"), border_color=("#f44336", "#d32f2f"))
            btn.pack(fill='x', pady=3, padx=20)
            ToolTip(btn, tip)

        right_actions = [
            ("Install Magisk", self.install_magisk, "Install Magisk.apk from platform-tools"),
            ("Open Diag", self.enable_diag_mode, "Enable diagnostic mode on some devices"),
            ("Start Server", lambda: self.run_command_threaded("adb", ['start-server'], task_name="Start Server"), "Start the ADB server process"),
            ("Kill Server", lambda: self.run_command_threaded("adb", ['kill-server'], task_name="Kill Server"), "Kill the ADB server process"),
            ("Get Serialno", lambda: self.run_command_threaded("adb", ['get-serialno'], task_name="Get Serialno"), "Get device serial number"),
            ("TCP/IP 5555", lambda: self.run_command_threaded("adb", ["tcpip", "5555"], task_name="TCP/IP 5555"), "Restart adbd listening on TCP 5555"),
            ("Connect", self.adb_connect, "Connect to a device over Wi-Fi"),
            ("Custom Command", lambda: self.show_custom_command_window("adb"), "Run a custom ADB command")
        ]
        
        for i, (text, action, tip) in enumerate(right_actions):
            btn = ctk.CTkButton(right_col, text=text, command=action, height=35,
                                fg_color=("gray85", "gray22"), hover_color=("gray75", "gray30"), text_color=("black", "gray95"),
                                border_width=1, border_color=("gray70", "gray28"))
            btn.grid(row=i+2, column=0, padx=10, pady=5, sticky='ew')
            if i == len(right_actions) - 1: btn.grid(pady=(5, 10))
            ToolTip(btn, tip)

    def create_fastboot_section(self, parent):
        fb_frame = ctk.CTkFrame(parent, fg_color="transparent")
        fb_frame.pack(expand=True, fill='both', pady=(10, 20))
        fb_frame.grid_columnconfigure((0, 1), weight=1)
        
        ctk.CTkLabel(fb_frame, text="Fastboot Operations", font=ctk.CTkFont(size=16, weight="bold"), text_color=("#00838f", "#00bcd4")).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
        
        left_col = ctk.CTkFrame(fb_frame, fg_color=("gray92", "gray14"), corner_radius=8, border_width=1, border_color=("gray80", "gray20"))
        left_col.grid(row=1, column=0, sticky='nsew', padx=(0, 5))
        left_col.grid_columnconfigure(0, weight=1)
        
        right_col = ctk.CTkFrame(fb_frame, fg_color=("gray92", "gray14"), corner_radius=8, border_width=1, border_color=("gray80", "gray20"))
        right_col.grid(row=1, column=1, sticky='nsew', padx=(5, 0))
        right_col.grid_columnconfigure(0, weight=1)

        left_actions = [
            ("List Devices", lambda: self.run_command_threaded("fastboot", ['devices'], task_name="List Devices"), "List connected Fastboot devices"),
            ("Unlock BL", lambda: self.prompt_bootloader_action("unlock"), "Unlock the bootloader (wipes data)"),
            ("Lock BL", lambda: self.prompt_bootloader_action("lock"), "Lock the bootloader"),
            ("Erase Cache", lambda: self.run_command_threaded("fastboot", ['erase', 'cache'], task_name="Erase Cache"), "Erase the cache partition"),
            ("Erase FRP", lambda: self.run_command_threaded("fastboot", ['erase', 'frp'], task_name="Erase FRP"), "Erase Factory Reset Protection (FRP) partition"),
            ("Wipe Data", lambda: self.run_command_threaded("fastboot", ['-w'], task_name="Wipe Data"), "Wipe user data and cache")
        ]
        
        for i, (text, action, tip) in enumerate(left_actions):
            btn = ctk.CTkButton(left_col, text=text, command=action, height=35,
                                fg_color=("gray85", "gray22"), hover_color=("gray75", "gray30"), text_color=("black", "gray95"),
                                border_width=1, border_color=("gray70", "gray28"))
            btn.grid(row=i, column=0, padx=10, pady=5, sticky='ew')
            if i == 0: btn.grid(pady=(10, 5))
            if i == len(left_actions) - 1: btn.grid(pady=(5, 10))
            ToolTip(btn, tip)

        btn_reboot_menu = ctk.CTkButton(right_col, text="Reboot Menu", command=self.toggle_fastboot_reboot_menu, height=35,
                                        fg_color=("#00bcd4", "#00838f"), hover_color=("#00acc1", "#006064"), text_color=("black", "white"))
        btn_reboot_menu.grid(row=0, column=0, padx=10, pady=(10, 5), sticky='ew')
        ToolTip(btn_reboot_menu, "Show reboot options")
        
        self.fb_reboot_menu_frame = ctk.CTkFrame(right_col, fg_color="transparent")
        
        reboot_actions = [
            ("-> System", lambda: self.run_command_threaded("fastboot", ['reboot'], task_name="Reboot System"), "Reboot to Android OS"),
            ("-> Bootloader", lambda: self.run_command_threaded("fastboot", ['reboot', 'bootloader'], task_name="Reboot Bootloader"), "Reboot back to bootloader"),
            ("-> Fastbootd", lambda: self.run_command_threaded("fastboot", ['reboot', 'fastboot'], task_name="Reboot Fastbootd"), "Reboot to fastbootd mode"),
            ("-> Recovery", lambda: self.run_command_threaded("fastboot", ['reboot', 'recovery'], task_name="Reboot Recovery"), "Reboot to recovery mode")
        ]
        
        for text, action, tip in reboot_actions:
            btn = ctk.CTkButton(self.fb_reboot_menu_frame, text=text, command=action, height=30, 
                                fg_color=("#80deea", "#006064"), hover_color=("#4dd0e1", "#004d40"), text_color=("black", "white"),
                                border_width=1, border_color=("#00bcd4", "#00838f"))
            btn.pack(fill='x', pady=3, padx=20)
            ToolTip(btn, tip)

        right_actions = [
            ("Get Info", lambda: self.run_command_threaded("fastboot", ['getvar', 'all'], task_name="Get Device Info"), "Get all device variables (getvar all)"),
            ("OEM Device Info", lambda: self.run_command_threaded("fastboot", ['oem', 'device-info'], task_name="OEM Device Info"), "Get OEM specific device info"),
            ("Set Active Other", lambda: self.run_command_threaded("fastboot", ['set_active', 'other'], task_name="Switch A/B Slot"), "Switch to the other A/B slot"),
            ("Boot Image", self.fastboot_boot, "Temporarily boot from a selected .img file"),
            ("Custom Command", lambda: self.show_custom_command_window("fastboot"), "Run a custom Fastboot command")
        ]
        
        for i, (text, action, tip) in enumerate(right_actions):
            btn = ctk.CTkButton(right_col, text=text, command=action, height=35,
                                fg_color=("gray85", "gray22"), hover_color=("gray75", "gray30"), text_color=("black", "gray95"),
                                border_width=1, border_color=("gray70", "gray28"))
            btn.grid(row=i+2, column=0, padx=10, pady=5, sticky='ew')
            if i == len(right_actions) - 1: btn.grid(pady=(5, 10))
            ToolTip(btn, tip)

    def create_flashing_section(self, parent):
        flash_frame = ctk.CTkFrame(parent, fg_color="transparent")
        flash_frame.pack(expand=True, fill='both', pady=(10, 20))
        
        ctk.CTkLabel(flash_frame, text="Partition Flashing", font=ctk.CTkFont(size=16, weight="bold"), text_color=("#e65100", "#f57c00")).pack(anchor='w', pady=(0, 10))
        
        grid_frame = ctk.CTkFrame(flash_frame, fg_color=("gray92", "gray14"), corner_radius=8, border_width=1, border_color=("gray80", "gray20"))
        grid_frame.pack(fill='x')
        grid_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        flash_partitions = [
            "boot", "system", "vbmeta", "recovery", "vbmeta_system",
            "vbmeta_vendor", "vendor", "product", "cust", "super",
            "userdata", "preloader", "logo", "dtbo", "gz", "lk",
            "nvdata", "nvram", "tee", "md1img", "rescue", "dpm",
            "efuse", "scp", "spmfw", "modem", "abl", "xbl", "sbl",
            "init_boot", "devinfo"
        ]
        
        for i, part in enumerate(flash_partitions):
            btn = ctk.CTkButton(grid_frame, text=part, font=ctk.CTkFont(size=12),
                                command=lambda p=part: self.flash_image(p), 
                                height=30, 
                                fg_color=("#81c784", "#388e3c"), 
                                hover_color=("#66bb6a", "#2e7d32"),
                                text_color=("black", "white"),
                                border_width=1, border_color=("#4caf50", "#1b5e20"))
            btn.grid(row=i//3, column=i%3, padx=6, pady=6, sticky='ew')
            ToolTip(btn, f"Flash {part}.img")

    def create_footer(self):
        footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        footer_frame.grid(row=4, column=0, sticky='ew', padx=20, pady=(0, 20))
        self.progress_bar = ctk.CTkProgressBar(footer_frame, mode='indeterminate')
        self.progress_bar.pack(expand=True, fill='x')
        self.progress_bar.set(0)

    def toggle_extras_menu(self): self.toggle_menu_frame(self.extras_menu_frame)
    def toggle_theme_menu(self): self.toggle_menu_frame(self.theme_menu_frame)

    def toggle_adb_reboot_menu(self):
        if self.adb_reboot_menu_frame.winfo_viewable():
            self.adb_reboot_menu_frame.grid_forget()
        else:
            self.adb_reboot_menu_frame.grid(row=1, column=0, sticky='ew', pady=(0, 5))

    def toggle_fastboot_reboot_menu(self):
        if self.fb_reboot_menu_frame.winfo_viewable():
            self.fb_reboot_menu_frame.grid_forget()
        else:
            self.fb_reboot_menu_frame.grid(row=1, column=0, sticky='ew', pady=(0, 5))

    def on_tab_switch(self):
        current_tab = self.tab_view.get()
        if current_tab == "Flashing Operations" and not getattr(self, 'flashing_warning_shown', False):
            self.show_flashing_warning()

    def show_flashing_warning(self):
        popup = ctk.CTkToplevel(self)
        popup.title("⚠️ WARNING: Dangerous Operations")
        popup.geometry("450x250")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()
        
        title_lbl = ctk.CTkLabel(popup, text="DANGER ZONE", font=ctk.CTkFont(size=20, weight="bold"), text_color="#f44336")
        title_lbl.pack(pady=(20, 10))
        
        msg = "These operations execute low-level flashing commands that can potentially BRICK your device.\n\nTry these ONLY if you know exactly what you are doing.\nThe device MUST be in Fastboot mode to proceed."
        msg_lbl = ctk.CTkLabel(popup, text=msg, font=ctk.CTkFont(size=13), justify="center", wraplength=400)
        msg_lbl.pack(pady=(0, 20))
        
        def proceed():
            self.flashing_warning_shown = True
            popup.grab_release()
            popup.destroy()
            
        def cancel():
            self.tab_view.set("Fastboot")
            popup.grab_release()
            popup.destroy()
            
        popup.protocol("WM_DELETE_WINDOW", cancel)
        
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)
        
        btn_cancel = ctk.CTkButton(btn_frame, text="Go Back", command=cancel, width=120, height=35, fg_color="#757575", hover_color="#616161")
        btn_cancel.pack(side="left", padx=30)
        
        btn_proceed = ctk.CTkButton(btn_frame, text="I Understand", command=proceed, width=120, height=35, fg_color="#d32f2f", hover_color="#b71c1c")
        btn_proceed.pack(side="right", padx=30)

    def toggle_menu_frame(self, frame_to_toggle):
        if self.active_menu_frame and self.active_menu_frame != frame_to_toggle:
            self.active_menu_frame.grid_forget()
        if self.active_menu_frame == frame_to_toggle:
            frame_to_toggle.grid_forget()
            self.active_menu_frame = None
        else:
            frame_to_toggle.grid(row=2, column=0, sticky='ew', padx=20, pady=(0, 15))
            self.active_menu_frame = frame_to_toggle

    def show_about_window(self):
        about_win = ctk.CTkToplevel(self)
        about_win.title("About Pixel Kit")
        about_win.geometry("500x550")
        about_win.resizable(False, False)
        about_win.transient(self)
        
        ctk.CTkLabel(about_win, text="Pixel Kit", font=ctk.CTkFont(family="Fixedsys", size=32, weight="bold"), text_color=("#00838f", "#00bcd4")).pack(pady=(20, 5))
        ctk.CTkLabel(about_win, text="A streamlined ADB & Fastboot Toolkit for Android", font=ctk.CTkFont(size=14, weight="bold")).pack()
        ctk.CTkLabel(about_win, text="Made by a Human on Planet Earth.", font=ctk.CTkFont(size=12)).pack(pady=(0, 15))
        
        features_frame = ctk.CTkFrame(about_win, fg_color=("gray92", "gray14"), corner_radius=8, border_width=1, border_color=("gray80", "gray20"))
        features_frame.pack(fill='both', expand=True, padx=20, pady=5)
        
        features_text = (
            "✨ Major Features & Capabilities:\n\n"
            "📱 ADB Operations\n"
            " • Seamless file pushing/pulling with dynamic paths\n"
            " • APK Installation, Uninstallation, & Sideloading\n"
            " • Reboot Menu (System, Bootloader, Recovery, EDL)\n"
            " • Qualcomm Diag Mode enabler & EFS Wiping\n"
            " • Magisk auto-installer & Scrcpy mirroring launch\n\n"
            "⚡ Fastboot Operations\n"
            " • Bootloader Unlocking & Locking\n"
            " • Complete device data & cache wiping\n"
            " • Active A/B slot switching & Advanced Device Info\n\n"
            "🛠️ Flashing Arsenal\n"
            " • One-click flashing for 30+ specific Android partitions\n"
            " • Pre-configured commands to prevent syntax errors\n\n"
            "🎨 Modern UX\n"
            " • Fully responsive Adaptive Light/Dark mode\n"
            " • Real-time device connection polling & tracking\n"
            " • Live threaded command console with 'Stop' functionality"
        )
        
        feat_label = ctk.CTkLabel(features_frame, text=features_text, font=ctk.CTkFont(size=13), justify="left", anchor="w")
        feat_label.pack(padx=20, pady=15, fill='both', expand=True)
        
        ctk.CTkLabel(about_win, text="Coded by GIANT", font=ctk.CTkFont(family="Fixedsys", size=16, weight="bold", slant="italic"), text_color="#ff5722").pack(pady=(15, 20))

    def show_custom_command_window(self, mode):
        popup = ctk.CTkToplevel(self)
        popup.title(f"Custom {mode.upper()} Command")
        popup.geometry("450x180")
        popup.resizable(False, False)
        popup.transient(self)

        ctk.CTkLabel(popup, text=f"Enter full command (e.g., {mode} devices)", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(20, 10))
        
        entry = ctk.CTkEntry(popup, width=350, font=ctk.CTkFont(family="Consolas", size=13))
        entry.pack(pady=10)
        entry.focus()

        def execute(event=None):
            command = entry.get()
            if command:
                if command.strip().startswith(mode + " "):
                    command = command[len(mode)+1:].strip()
                self.run_command_threaded(tool=mode, args_list=command.split(), task_name=f"Custom {mode.upper()} Command")
                popup.destroy()

        btn = ctk.CTkButton(popup, text="Execute", command=execute, width=120, height=35)
        btn.pack(pady=10)
        popup.bind("<Return>", execute)

    def write_to_console(self, text, tag=None):
        def update():
            self.console_output.insert("end", text, tag)
            self.console_output.see("end")
        self.after(0, update)

    def start_progress(self):
        self.after(0, self.progress_bar.start)

    def stop_progress(self):
        self.after(0, self.progress_bar.stop)

    def stop_current_command(self):
        if self.current_process:
            self.stop_event.set()
            try:
                self.current_process.terminate()
                self.write_to_console("Command execution stopped by user.\n", "error")
            except Exception as e:
                self.write_to_console(f"Failed to terminate process: {e}\n", "error")
            self.stop_progress()

    def start_status_checker(self):
        self.status_running = True
        thread = threading.Thread(target=self.device_status_loop)
        thread.daemon = True
        thread.start()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        self.status_running = False
        self.save_config()
        if self.current_process:
            try:
                self.current_process.terminate()
            except Exception as e:
                print(f"Error terminating process on close: {e}")
        self.destroy()

    def device_status_loop(self):
        while self.status_running:
            self.update_device_status()
            time.sleep(10)

    def update_device_status(self):
        status, color_hex, model, serial = "Disconnected", "#f44336", "N/A", "N/A"
        try:
            process = self.execute_tool_command("adb", ["devices"], combine_output=True)
            if process:
                adb_output, _ = process.communicate()
                
                if adb_output and "device" in adb_output and len(adb_output.strip().splitlines()) > 1:
                    lines = adb_output.strip().splitlines()
                    if len(lines) > 1 and '\t' in lines[1]:
                        status, color_hex = "Connected (ADB)", "#4caf50"
                        serial = lines[1].split('\t')[0]
                        
                        model_proc = self.execute_tool_command("adb", ["-s", serial, "shell", "getprop", "ro.product.model"])
                        if model_proc:
                            model_out, _ = model_proc.communicate()
                            if model_out:
                                model = model_out.strip()
                else:
                    fb_process = self.execute_tool_command("fastboot", ["devices"], combine_output=True)
                    if fb_process:
                        fb_output, _ = fb_process.communicate()
                        
                        if fb_output and "fastboot" in fb_output.strip():
                            status, color_hex = "Connected (Fastboot)", "#4caf50"
                            serial = fb_output.strip().split('\t')[0]
                            
                            prod_proc = self.execute_tool_command("fastboot", ["getvar", "product"], combine_output=True)
                            if prod_proc:
                                prod_out, _ = prod_proc.communicate()
                                if prod_out and ': ' in prod_out:
                                    # Fastboot output typically looks like: "product: redfin\nFinished. Total time: 0.001s"
                                    for line in prod_out.splitlines():
                                        if 'product:' in line.lower() or ('product' in line.lower() and ':' in line):
                                            model = line.split(':', 1)[1].strip()
                                            break
        except Exception:
            pass
            
        if self.status_running:
            try:
                if self.winfo_exists():
                    self.after(0, self.set_status_label, status, color_hex, model, serial)
            except Exception:
                pass

    def set_status_label(self, status, color_hex, model, serial):
        self.status_label.configure(text=status, text_color=color_hex)
        if status != "Disconnected":
            self.device_info_frame.grid(row=1, column=0, sticky='ew', padx=20, pady=(0, 10))
            self.device_model_label.configure(text=f"Model: {model}")
            self.device_serial_label.configure(text=f"Serial: {serial}")
        else:
            self.device_info_frame.grid_forget()

    def execute_tool_command(self, tool, args_list, capture_output=True, is_shell=False, combine_output=False):
        tool_path = self.cached_paths.get(tool)
        if not tool_path:
            tool_path = str((PLATFORM_TOOLS_DIR / tool).absolute())
        
        if is_shell:
            if IS_WINDOWS:
                args_str = " ".join(args_list) if isinstance(args_list, list) else args_list
                cmd = f'cmd.exe /K ""{tool_path}" {args_str}"'
                return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                cmd = [tool_path] + (args_list if isinstance(args_list, list) else args_list.split())
                return subprocess.Popen(['x-terminal-emulator', '-e'] + cmd)
        
        cmd = [tool_path] + (args_list if isinstance(args_list, list) else args_list.split())
        
        try:
            if capture_output:
                stderr_dest = subprocess.STDOUT if combine_output else subprocess.PIPE
                return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr_dest, 
                                       text=True, errors='replace', bufsize=1, creationflags=WIN_CREATION_FLAGS)
            else:
                return subprocess.Popen(cmd, creationflags=WIN_CREATION_FLAGS)
        except Exception as e:
            self.write_to_console(f"Execution Error: {e}\n", "error")
            return None

    def run_command_threaded(self, tool, args_list="", is_shell=False, task_name=None):
        thread = threading.Thread(target=self.run_command, args=(tool, args_list, is_shell, task_name))
        thread.daemon = True
        thread.start()

    def run_command(self, tool, args_list="", is_shell=False, task_name=None):
        self.start_progress()
        self.stop_event.clear()
        if task_name:
            self.write_to_console(f"--- Executing Command: {task_name} ---\n", "status")
        else:
            self.write_to_console("--- Executing Command ---\n", "status")
        
        try:
            process = self.execute_tool_command(tool, args_list, is_shell=is_shell, combine_output=True)
            self.current_process = process
            if process:
                if is_shell:
                    self.write_to_console(f"Interactive {tool} shell opened in a new window.\n")
                else:
                    for line in iter(process.stdout.readline, ''): 
                        self.write_to_console(line, "command_output")
                    process.stdout.close()
                    
                    return_code = process.wait()
                    if return_code != 0 and not self.stop_event.is_set():
                        self.write_to_console(f"Command failed with return code {return_code}\n", "error")
            else:
                self.write_to_console("Failed to start process.\n", "error")
        except Exception as e:
            if not self.stop_event.is_set():
                self.write_to_console(f"An application error occurred: {e}\n", "error")
        finally:
            self.current_process = None
            
        self.write_to_console("--- Command Finished ---\n\n", "status")
        self.stop_progress()

    def list_adb_devices(self): self.run_command_threaded("adb", ["devices"], task_name="List Devices")
    
    def install_apk(self):
        filepath = filedialog.askopenfilename(title="Select APK file", filetypes=(("Android Package", "*.apk"), ("All files", "*.*")))
        if filepath: self.run_command_threaded("adb", ["install", filepath], task_name="Install APK")
        
    def uninstall_apk(self):
        dialog = ctk.CTkInputDialog(text="Enter package name to uninstall:", title="Uninstall APK")
        pkg = dialog.get_input()
        if pkg: self.run_command_threaded("adb", ["uninstall", pkg], task_name="Uninstall APK")

    def adb_sideload(self):
        filepath = filedialog.askopenfilename(title="Select ZIP file", filetypes=(("ZIP Archive", "*.zip"), ("All files", "*.*")))
        if filepath: self.run_command_threaded("adb", ["sideload", filepath], task_name="Sideload ZIP")

    def adb_push(self):
        filepath = filedialog.askopenfilename(title="Select file to push")
        if filepath:
            popup = ctk.CTkToplevel(self)
            popup.title("Push File")
            popup.geometry("450x180")
            popup.resizable(False, False)
            popup.transient(self)
            popup.grab_set()

            ctk.CTkLabel(popup, text="Enter remote destination path:", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(20, 10))
            
            entry = ctk.CTkEntry(popup, width=350, font=ctk.CTkFont(family="Consolas", size=13))
            entry.pack(pady=10)
            entry.insert(0, "/sdcard/")
            entry.focus()

            def execute(event=None):
                dest = entry.get()
                if not dest:
                    return
                popup.grab_release()
                popup.destroy()
                self.run_command_threaded("adb", ["push", filepath, dest], task_name="Push File")

            btn = ctk.CTkButton(popup, text="Push File", command=execute, width=120, height=35)
            btn.pack(pady=10)
            
            popup.bind("<Return>", execute)

    def adb_pull(self):
        dialog = ctk.CTkInputDialog(text="Enter remote file path to pull (e.g., /sdcard/file.txt):", title="Pull File")
        remote_path = dialog.get_input()
        if remote_path:
            dest = filedialog.asksaveasfilename(title="Save as", initialfile=os.path.basename(remote_path))
            if dest: self.run_command_threaded("adb", ["pull", remote_path, dest], task_name="Pull File")

    def adb_connect(self):
        dialog = ctk.CTkInputDialog(text="Enter IP address and port (e.g., 192.168.1.5:5555):", title="ADB Connect")
        addr = dialog.get_input()
        if addr: self.run_command_threaded("adb", ["connect", addr], task_name="Connect")

    def prompt_bootloader_action(self, action):
        popup = ctk.CTkToplevel(self)
        popup.title(f"{action.capitalize()} Bootloader")
        popup.geometry("450x200")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()

        ctk.CTkLabel(popup, text=f"Choose command version to {action} the bootloader:", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(20, 15))

        def run_flashing():
            popup.grab_release()
            popup.destroy()
            self.run_command_threaded("fastboot", ["flashing", action], task_name=f"{action.capitalize()} Bootloader (flashing)")

        def run_oem():
            popup.grab_release()
            popup.destroy()
            self.run_command_threaded("fastboot", ["oem", action], task_name=f"{action.capitalize()} Bootloader (oem)")

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=5)

        btn_flashing = ctk.CTkButton(btn_frame, text=f"fastboot flashing {action}\n(Modern/Pixel)", command=run_flashing, height=45, fg_color=("#00bcd4", "#00838f"), hover_color=("#00acc1", "#006064"), text_color=("black", "white"))
        btn_flashing.pack(side="left", padx=10, expand=True, fill='x')

        btn_oem = ctk.CTkButton(btn_frame, text=f"fastboot oem {action}\n(Legacy/Other)", command=run_oem, height=45, fg_color=("#ff9800", "#f57c00"), hover_color=("#fb8c00", "#e65100"), text_color=("black", "white"))
        btn_oem.pack(side="right", padx=10, expand=True, fill='x')

    def flash_image(self, partition):
        filepath = filedialog.askopenfilename(title=f"Select {partition.replace('_', ' ')} Image", filetypes=(("Image File", "*.img"), ("All files", "*.*")))
        if filepath: self.run_command_threaded("fastboot", ["flash", partition, filepath], task_name=f"Flash {partition}")

    def fastboot_boot(self):
        filepath = filedialog.askopenfilename(title="Select Boot Image", filetypes=(("Image File", "*.img"), ("All files", "*.*")))
        if filepath: self.run_command_threaded("fastboot", ["boot", filepath], task_name="Boot Image")

    def reset_efs(self):
        if not messagebox.askyesno("Confirm EFS Reset", "WARNING: This is a dangerous operation. Are you sure you want to continue?"): return
        commands = [
            ["adb", "shell", "su", "-c", "dd if=/dev/zero of=/dev/block/bootdevice/by-name/modemst1"],
            ["adb", "shell", "su", "-c", "dd if=/dev/zero of=/dev/block/bootdevice/by-name/modemst2"],
            ["adb", "shell", "su", "-c", "dd if=/dev/zero of=/dev/block/bootdevice/by-name/fsg"]
        ]
        self.run_multiple_commands(commands, task_name="Reset EFS")

    def enable_diag_mode(self):
        popup = ctk.CTkToplevel(self)
        popup.title("⚠️ Warning")
        popup.geometry("450x250")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()
        
        title_lbl = ctk.CTkLabel(popup, text="Warning:", font=ctk.CTkFont(size=20, weight="bold"), text_color="#f44336")
        title_lbl.pack(pady=(20, 10))
        
        msg = "This feature is intended only for rooted Qualcomm Snapdragon devices with full root access.\n\nPlease ensure your device is properly rooted before enabling DIAG mode.\nProceed at your own risk."
        msg_lbl = ctk.CTkLabel(popup, text=msg, font=ctk.CTkFont(size=13), justify="center", wraplength=400)
        msg_lbl.pack(pady=(0, 20))
        
        def proceed():
            popup.grab_release()
            popup.destroy()
            commands = [
                ["adb", "shell", "su", "-c", "resetprop ro.bootmode usbradio"],
                ["adb", "shell", "su", "-c", "resetprop ro.build.type userdebug"],
                ["adb", "shell", "su", "-c", "setprop sys.usb.config diag,diag_mdm,adb"],
                ["adb", "shell", "su", "-c", "diag_mdlog"]
            ]
            self.run_multiple_commands(commands, task_name="Enable Diag Mode")
            
        def cancel():
            popup.grab_release()
            popup.destroy()
            
        popup.protocol("WM_DELETE_WINDOW", cancel)
        
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)
        
        btn_cancel = ctk.CTkButton(btn_frame, text="Cancel", command=cancel, width=120, height=35, fg_color="#757575", hover_color="#616161")
        btn_cancel.pack(side="left", padx=30)
        
        btn_proceed = ctk.CTkButton(btn_frame, text="Proceed", command=proceed, width=120, height=35, fg_color="#d32f2f", hover_color="#b71c1c")
        btn_proceed.pack(side="right", padx=30)

    def run_multiple_commands(self, command_list, task_name=None):
        def run_all():
            if task_name:
                self.write_to_console(f"--- Executing Task: {task_name} ---\n", "status")
            for cmd_parts in command_list:
                tool = cmd_parts[0]
                args = cmd_parts[1:]
                self.run_command(tool, args)
        threading.Thread(target=run_all, daemon=True).start()

    def start_scrcpy(self):
        scrcpy_path = self.cached_paths.get("scrcpy")
        if scrcpy_path:
            subprocess.Popen([scrcpy_path], creationflags=WIN_CREATION_FLAGS)
        else:
            messagebox.showerror("File Not Found", "scrcpy was not found in platform-tools.")

    def install_magisk(self):
        magisk_path = PLATFORM_TOOLS_DIR / "Magisk.apk"
        if magisk_path.exists():
            self.run_command_threaded("adb", ["install", str(magisk_path.absolute())], task_name="Install Magisk")
        else:
            messagebox.showerror("File Not Found", "Magisk.apk not found in platform-tools.")

    def install_drivers(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Driver Installation Notice")
        popup.geometry("450x200")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()

        ctk.CTkLabel(popup, text="Driver Installation Notice", font=ctk.CTkFont(size=18, weight="bold"), text_color="#00bcd4").pack(pady=(20, 10))
        
        msg = "This process will install the required ADB and Fastboot drivers on your computer.\nPlease continue only if you understand the changes being made to your system."
        ctk.CTkLabel(popup, text=msg, font=ctk.CTkFont(size=13), justify="center", wraplength=400).pack(pady=(0, 20))

        def proceed():
            popup.grab_release()
            popup.destroy()
            driver_path = PLATFORM_TOOLS_DIR / "drivers.exe"
            if driver_path.exists():
                try:
                    if IS_WINDOWS:
                        import ctypes
                        ctypes.windll.shell32.ShellExecuteW(None, "runas", str(driver_path.absolute()), None, None, 1)
                    else:
                        subprocess.Popen([str(driver_path.absolute())])
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to start driver installation: {e}")
            else:
                messagebox.showerror("File Not Found", "drivers.exe not found in platform-tools.")

        def cancel():
            popup.grab_release()
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", cancel)

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)

        btn_cancel = ctk.CTkButton(btn_frame, text="Cancel", command=cancel, width=120, height=35, fg_color="#757575", hover_color="#616161")
        btn_cancel.pack(side="left", padx=30)

        btn_proceed = ctk.CTkButton(btn_frame, text="Continue", command=proceed, width=120, height=35, fg_color="#4caf50", hover_color="#388e3c")
        btn_proceed.pack(side="right", padx=30)
        
    def save_logs(self):
        log_content = self.console_output.get("1.0", tk.END)
        filepath = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Documents", "*.txt"), ("All Files", "*.*")], title="Save Logs As")
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(log_content)
                messagebox.showinfo("Success", "Logs saved successfully.")
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to save logs: {e}")

    def check_tools_on_startup(self):
        self.cached_paths = {}
        if not PLATFORM_TOOLS_DIR.is_dir():
            messagebox.showerror("Critical Error", f"The '{PLATFORM_TOOLS_DIR}' directory was not found.\nPlease ensure it is in the same folder as this application.")
            self.after(100, self.on_closing)
            return

        missing_tools = []
        for tool in REQUIRED_TOOLS:
            tool_path = PLATFORM_TOOLS_DIR / tool
            if IS_WINDOWS:
                tool_exe = PLATFORM_TOOLS_DIR / f"{tool}.exe"
                if tool_exe.exists():
                    self.cached_paths[tool] = str(tool_exe.absolute())
                elif tool_path.exists():
                    self.cached_paths[tool] = str(tool_path.absolute())
                else:
                    missing_tools.append(tool)
            else:
                if tool_path.exists():
                    self.cached_paths[tool] = str(tool_path.absolute())
                else:
                    missing_tools.append(tool)

        if missing_tools:
            tools_list = ", ".join(missing_tools)
            messagebox.showwarning("Missing Tools", f"The following essential tools were not found in '{PLATFORM_TOOLS_DIR}':\n{tools_list}\n\nSome features may not work correctly.")

if __name__ == "__main__":
    app = AndroidToolkit()
    app.mainloop()
