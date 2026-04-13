import os
import io
import sys
import numpy as np
import pandas as pd
import matplotlib
import bcrypt
import json

matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.ticker as mticker

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except (ImportError, Exception) as e:
    print(f"tkinterdnd2 yüklenemedi: {e}")
    DND_AVAILABLE = False
    TkinterDnD = tk.Tk


from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader


SETTINGS_FILE = "voltage_settings.json"
APP_CONFIG_FILE = "app_config.json"
DEFAULT_APP_CONFIG = {
    "organization_name": "Custom Organization",
    "voltage_window_title": "Voltage Analysis Program",
    "voltage_report_title": "Voltage Analysis Report",
    "scale_auth": {
        "enabled": False,
        "username": "",
        "password_hash": "",
    },
    "pdf_auto_open": True,
}

def merge_dicts(base, extra):
    # Recursively merges the loaded application settings with the defaults.
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged

def load_app_config():
    # Loads the optional application configuration from the local JSON file.
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                return merge_dicts(DEFAULT_APP_CONFIG, json.load(f))
        except Exception as e:
            print(f"Uygulama ayarlari okunamadi: {e}")
    return dict(DEFAULT_APP_CONFIG)

def load_settings():
    # Loads the persisted voltage settings from disk when available.
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
            return settings
        except Exception:
            pass
    return {}

def save_settings(settings):
    # Saves the current voltage settings to the local JSON file.
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Ayarlar kaydedilemedi: {e}")

APP_CONFIG = load_app_config()

# Global variables
view_history = []
last_pdf_path = None
pdf_open_button = None

# Color mappings for result display
DEGERLER_SIRALAMA = [
    ("Max Voltaj Değeri", "red"),
    ("Min Voltaj Değeri", "red"),
    ("T (90-30%) Değeri", "black"),
    ("T1 Degeri", "black"),
    ("T2 (t=Time(%50 - O1))", "black"),
    ("TPeak Değeri", "black"),
    ("T görünür Değeri", "black"),
    ("TPSwitching Değeri", "darkgreen"),
    ("Tchop Front Değeri", "darkgreen"),
    ("Tchop Tail Değeri", "darkgreen"),
    ("%90 Voltaj Değeri", "blue"),
    ("%30 Voltaj Değeri", "blue"),
    ("%90-%30 Fark Değeri", "blue"),
    ("Türev Değeri", "purple"),
]

RENKLER = {
    "red": "#E74C3C",
    "black": "#2C3E50",
    "blue": "#3498DB",
    "darkgreen": "#27AE60",
    "purple": "#9B59B6"
}

COLORS = {
    'primary': '#3498DB',
    'secondary': '#f59e0b',
    'accent': '#71C832',
    'danger': '#CC0000',
    'warning': '#f59e0b',
    'bg_main': '#f8fafc',
    'bg_secondary': '#ffffff',
    'text_primary': '#111827',
    'text_secondary': '#6b7280',
    'border': '#e5e7eb',
    'result_bg': '#FFFDD0'
}

secili_dosya_yolu = ""
last_sonuc_rows = []
global_df = None
graph_canvas = None
graph_toolbar = None
settings = load_settings()
scale_factor = settings.get("scale_factor", 1.0)
EPS = 1e-9


def create_modern_button(parent, text, command, bg_color, hover_color=None, width=180, height=45):
    # Creates a styled button container for the main control area.
    if hover_color is None:
        hover_color = bg_color

    btn_frame = tk.Frame(parent, bg=COLORS['bg_main'])
    btn = tk.Button(
        btn_frame, text=text, command=command,
        font=('Segoe UI', 12, 'bold'), bg=bg_color, fg='white',
        bd=0, relief='flat', padx=20, pady=10, cursor='hand2',
        activebackground=hover_color, activeforeground='white'
    )

    def on_enter(e): btn.config(bg=hover_color)
        # Applies the hover color when the pointer enters the button.

    def on_leave(e): btn.config(bg=bg_color)
        # Restores the base color when the pointer leaves the button.

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    btn.pack(fill='both', expand=True)
    return btn_frame

#Tam ortalı, hash şifreli Modern admin girişi
def admin_giris_paneli_modern(parent, on_success):
    # Prompts for scale access only when local admin protection is enabled.
    auth_config = APP_CONFIG.get("scale_auth", {})
    username = str(auth_config.get("username", "") or "")
    password_hash = auth_config.get("password_hash", "")
    auth_enabled = bool(auth_config.get("enabled")) and bool(username) and bool(password_hash)

    if not auth_enabled:
        on_success()
        return

    giris_pencere = tk.Toplevel(parent)
    giris_pencere.title("Yönetici Girişi")
    giris_pencere.geometry("400x325")
    giris_pencere.resizable(False, False)
    giris_pencere.configure(bg="#f8fafc")

    giris_pencere.update_idletasks()
    x = parent.winfo_rootx() + parent.winfo_width() // 2 - 200
    y = parent.winfo_rooty() + parent.winfo_height() // 2 - 160
    giris_pencere.geometry(f"+{x}+{y}")

    ana_cerceve = tk.Frame(giris_pencere, bg="#f8fafc", bd=0)
    ana_cerceve.pack(expand=True, fill="both", padx=22, pady=18)

    tk.Label(ana_cerceve, text="YÖNETİCİ GİRİŞİ",
             font=("Segoe UI", 17, "bold"), fg="#1e3a8a", bg="#f8fafc").pack(pady=(5, 17))

    tk.Label(ana_cerceve, text="Kullanıcı Adı:",
             font=("Segoe UI", 11, "bold"), bg="#f8fafc").pack(anchor="w", padx=4)
    entry_kullanici = tk.Entry(ana_cerceve, font=("Segoe UI", 12), bd=2, relief="groove")
    entry_kullanici.pack(fill="x", padx=2, pady=(2, 13))
    entry_kullanici.insert(0, username)

    tk.Label(ana_cerceve, text="Şifre:",
             font=("Segoe UI", 11, "bold"), bg="#f8fafc").pack(anchor="w", padx=4)
    frame_pw = tk.Frame(ana_cerceve, bg="#f8fafc")
    frame_pw.pack(fill="x", pady=(2, 0))

    entry_sifre = tk.Entry(frame_pw, font=("Segoe UI", 12), show="*", bd=2, relief="groove")
    entry_sifre.pack(side="left", fill="x", expand=True)

    show_var = tk.BooleanVar(value=False)

    def toggle_password():
        # Toggles password visibility in the admin login dialog.
        entry_sifre.config(show="" if show_var.get() else "*")

    cb = tk.Checkbutton(frame_pw, text="Şifreyi göster", variable=show_var,
                        command=toggle_password, bg="#f8fafc", fg="#6b7280",
                        font=("Segoe UI", 9), activebackground="#f8fafc")
    cb.pack(side="left", padx=(12, 0))

    hata_label = tk.Label(ana_cerceve, text="", fg="#ef4444",
                          bg="#f8fafc", font=("Segoe UI", 10, "bold"))
    hata_label.pack(pady=(7, 4))

    def dogrula_ve_kapat():
        # Validates the provided admin credentials against the local config.
        stored_hash = password_hash.encode() if isinstance(password_hash, str) else password_hash
        kullanici = entry_kullanici.get().strip()
        sifre = entry_sifre.get()
        if kullanici == username and bcrypt.checkpw(sifre.encode(), stored_hash):
            giris_pencere.destroy()
            on_success()
        else:
            hata_label.config(text="Kullanıcı adı veya şifre hatalı!")

    def iptal():
        # Closes the current dialog without applying a new action.
        giris_pencere.destroy()

    btn_frame = tk.Frame(ana_cerceve, bg="#f8fafc")
    btn_frame.pack(fill="x", pady=(10, 0))

    giris_btn = tk.Button(btn_frame, text="GİRİŞ YAP", command=dogrula_ve_kapat,
                          font=("Segoe UI", 12, "bold"), bg="#10b981", fg="white", bd=0, width=11)
    giris_btn.pack(side="left", expand=True, padx=(0, 6))

    iptal_btn = tk.Button(btn_frame, text="İPTAL", command=iptal,
                          font=("Segoe UI", 12, "bold"), bg="#e5e7eb", fg="#374151", bd=0, width=11)
    iptal_btn.pack(side="left", expand=True, padx=(6, 0))

    def enter_pressed(event):
        # Submits the login dialog when the Enter key is pressed.
        dogrula_ve_kapat()

    entry_kullanici.bind('<Return>', enter_pressed)
    entry_sifre.bind('<Return>', enter_pressed)

    entry_kullanici.focus_set()
    giris_pencere.transient(parent)
    giris_pencere.grab_set()
    parent.wait_window(giris_pencere)


def format_duration(sec, decimals=4):
    # Formats a time duration using a readable engineering unit.
    abs_sec = abs(sec)
    if abs_sec >= 1:
        val, unit = sec, "s"
    elif abs_sec >= 1e-3:
        val, unit = sec * 1e3, "ms"
    elif abs_sec >= 1e-6:
        val, unit = sec * 1e6, "µs"
    else:
        val, unit = sec * 1e9, "ns"
    s = f"{val:.{decimals}f}".replace(".", ",")
    return f"{s} {unit}"

def read_data(dosya):
    # Reads the input file and returns cleaned time-voltage data.
    try:
        # Önce encoding tespiti
        with open(dosya, "rb") as f:
            raw_data = f.read()

        # Encoding tespiti
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        content = None

        for encoding in encodings:
            try:
                content = raw_data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            raise ValueError("Dosya encoding'i tespit edilemedi")

        lines = content.splitlines()

        if not lines:
            raise ValueError("Dosya boş")

    except Exception as e:
        raise ValueError(f"Dosya okuma hatası: {str(e)}")

    max_cols = max(line.count(",") + 1 for line in lines)
    fixed_lines = []
    for line in lines:
        parts = line.strip().split(",")
        if len(parts) < max_cols:
            parts += [""] * (max_cols - len(parts))
        fixed_lines.append(parts)

    # Veri başlangıcını bul
    start = 0
    for i, parts in enumerate(fixed_lines):
        try:
            float(parts[0].replace(",", ".").replace("+", ""))
            float(parts[1].replace(",", ".").replace("+", ""))
            start = i
            break
        except Exception:
            continue

    buf = io.StringIO()
    for parts in fixed_lines[start:]:
        buf.write(",".join(parts) + "\n")
    buf.seek(0)

    for sep in [",", ";", "\t"]:
        buf.seek(0)
        try:
            df = pd.read_csv(buf, sep=sep, engine="python", dtype=str)
            break
        except Exception:
            continue

    if df.shape[0] < 200000 and df.shape[1] >= 6:
        df.columns = ["ProID", "Info", "dogan", "time", "volume", "said"] + list(df.columns[6:])
        df = df[["time", "volume"]]
    elif df.shape[1] >= 2:
        df = df.iloc[:, :2]
        df.columns = ["time", "volume"]
    else:
        raise ValueError("Dosya uygun formatta degil.")

    df["time"] = pd.to_numeric(df["time"].astype(str).str.replace(",", ".").str.replace("+", ""), errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"].astype(str).str.replace(",", ".").str.replace("+", ""), errors="coerce")
    df = df.dropna().sort_values("time").reset_index(drop=True)
    return df

# Sample Interval * Record Length ile tpeak hesaplandı
def calculate_basic_values(df, sample_interval=None, record_length=None):
    # Calculates peak, polarity, and timing basics from the waveform data.
    if df.empty:
        raise ValueError("DataFrame boş")

    max_v = df["volume"].max()
    min_v = df["volume"].min()

    if max_v > abs(min_v):
        idx_peak = df["volume"].idxmax()
        peak_v = max_v
        is_positive = True
    else:
        idx_peak = df["volume"].idxmin()
        peak_v = min_v
        is_positive = False

    t_peak = df.loc[idx_peak, "time"]

    if sample_interval is not None and record_length is not None:
        trigger_time = sample_interval * record_length
    else:
        trigger_time = 0.0

    Tpeak = t_peak - trigger_time

    return {
        'is_positive': is_positive,
        'idx_peak': idx_peak,
        'peak_voltage': peak_v,
        'tpeak_time': t_peak,
        'trigger_time': trigger_time,
        'Tpeak': Tpeak,
        'max_voltage': max_v,
        'min_voltage': min_v
    }


def initialize_globals():
    # Ensures the shared runtime globals are initialized before use.

    global view_history, last_sonuc_rows, global_df
    global graph_canvas, graph_toolbar, scale_factor

    if 'view_history' not in globals():
        view_history = []
    if 'last_sonuc_rows' not in globals():
        last_sonuc_rows = []
    if 'global_df' not in globals():
        global_df = None
    if 'graph_canvas' not in globals():
        graph_canvas = None
    if 'graph_toolbar' not in globals():
        graph_toolbar = None
    if 'scale_factor' not in globals():
        scale_factor = 1.0

def _first_cross_time(x, y, thresh, descending):
    # Interpolates the first threshold crossing time on the selected segment.
    """
    y =mx +b
    m=(y1-y0) / (x1-x0)
    """
    cond = y <= thresh if descending else y >= thresh
    idxs = np.where(cond)[0]
    if idxs.size == 0:
        return None
    i = idxs[0]
    if i == 0:
        return float(x[0])
    x0, x1 = x[i - 1], x[i]
    y0, y1 = y[i - 1], y[i]
    if y1 == y0:
        return float(x1)
    return float(x0 + (thresh - y0) * (x1 - x0) / (y1 - y0))


def calculate_time_values(df, b):
    # Calculates waveform timing values derived from the main peak.
    peak = b["peak_voltage"]
    max_index = b["idx_peak"]


    lower_30 = peak * 0.30
    upper_30 = peak * 0.305
    min_thr_30, max_thr_30 = min(lower_30, upper_30), max(lower_30, upper_30)

    df_30 = df[(df["volume"] >= min_thr_30) & (df["volume"] < max_thr_30)]
    if not df_30.empty:
        A = df_30["volume"].iloc[0]
    else:
        A = peak * 0.300

    C = peak * 0.500

    lower_90 = peak * 0.8989
    upper_90 = peak * 0.9015
    min_thr_90, max_thr_90 = min(lower_90, upper_90), max(lower_90, upper_90)

    df_90 = df[(df["volume"] > min_thr_90) & (df["volume"] <= max_thr_90)]
    if not df_90.empty:
        B = df_90["volume"].iloc[0]
    else:
        B = peak * 0.900

    df_up_to_peak = df.loc[:max_index]
    low, high = min(A, B), max(A, B)
    df_AB = df_up_to_peak[(df_up_to_peak["volume"] >= low) & (df_up_to_peak["volume"] <= high)]

    if df_AB.empty:
        tA = tB = T = T1 = Tv = 0.0
    else:
        tA = df_AB["time"].min()
        tB = df_AB["time"].max()
        T  = tB - tA
        T1 = T * 1.67
        Tv = T1 * 0.3

    o1 = tA - Tv
    df_after_peak = df.loc[max_index:]
    if peak >= 0:
        df_T2 = df_after_peak[df_after_peak["volume"] >= C]
    else:
        df_T2 = df_after_peak[df_after_peak["volume"] <= C]
    T2 = (df_T2["time"].max() - o1) if not df_T2.empty else 0.0

    return {
        'T0': T,
        'T1': T1,
        'Tv': Tv,
        'O1': o1,
        'T2': T2,
        'voltage_30': A,
        'voltage_90': B,
        'voltage_50': C
    }

def calculate_derivative_value(t):
    # Calculates the derivative-based metric from the 30 and 90 percent levels.
    voltage_diff = abs(t['voltage_90'] - t['voltage_30'])
    T = t['T0']

    if T == 0 or T < EPS:
        return 0.0

    dv_dt = voltage_diff / T
    return dv_dt / 1e6


def calculate_tp_switching(t):
    # Calculates the switching time estimate from the derived waveform metrics.
    T0_us = t["T0"] * 1e6
    T2_us = t["T2"] * 1e6
    K = 2.42 - 3.08e-3 * T0_us + 1.51e-4 * T2_us
    return K * T0_us


def _fit_tail_and_intersect_v90(x, y, v70, v10, v90, fallback_points=50):
    # Fits the waveform tail and estimates its 90 percent intersection time.
    if v70 > v10:
        mask = (y <= v70) & (y >= v10)
    else:
        mask = (y >= v70) & (y <= v10)

    x_fit = x[mask]
    y_fit = y[mask]

    if x_fit.size < 2:
        x_fit = x[-fallback_points:]
        y_fit = y[-fallback_points:]
        if x_fit.size < 2:
            return None

    m, b = np.polyfit(x_fit, y_fit, 1)
    if abs(m) < 1e-15:
        return None
    return float((v90 - b) / m)


def calculate_chop_values(df, b, t):
    # Calculates the visible and chop timing values after the main peak.

    ispos = b["is_positive"]
    idx = b["idx_peak"]
    pv_abs = abs(b["peak_voltage"])
    sign = 1 if ispos else -1

    df_after = df.iloc[idx:]
    x_arr = df_after["time"].to_numpy()
    y_arr = df_after["volume"].to_numpy()

    v90 = sign * pv_abs * 0.9
    v70 = sign * pv_abs * 0.7
    v10 = sign * pv_abs * 0.1

    # Trigger noktasını bul
    zero_idxs = df.index[np.abs(df["volume"]) < EPS].tolist()
    trigger_time = df.loc[zero_idxs[-1], "time"] if zero_idxs else df.loc[df.index[0], "time"]

    # Tchop Front hesaplama (O1'den)
    t90_cross_raw = _first_cross_time(x_arr, y_arr, v90, descending=ispos)
    Tchop_front = abs((t90_cross_raw - t["O1"])) if t90_cross_raw is not None else 0.0

    # Tchop Tail hesaplama
    t90_fit = _fit_tail_and_intersect_v90(x_arr, y_arr, v70, v10, v90)
    Tchop_tail = abs((t90_fit - trigger_time)) if t90_fit is not None else 0.0  # O1 yerine trigger_time

    return {
        'T_visible': t["O1"],
        'Tchop_front': Tchop_front,
        'Tchop_tail': Tchop_tail
    }

def t2_to_microseconds_only_display(T2):
    # Formats the T2 value specifically in microseconds for display.
    T2_us = T2 * 1e6
    s = f"{T2_us:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{s} µs"


def format_results(b, t, c, tp_sw, file_name, derivative_value):
    # Formats the voltage analysis metrics into display-ready result rows.

    if not all([b, t, c]) or any(v is None for v in [
        b.get('max_voltage'), b.get('min_voltage'),
        t.get('T0'), t.get('T1'), t.get('T2'),
        c.get('T_visible')
    ]):
        return ["Veri eksik veya analiz tamamlanmadı."]

    # tpeak_o1 = b['tpeak_time'] - t['O1'] o1 ile hesaplama
    # ("TPeak Değeri ", format_duration(tpeak_o1, 5)), items a koy
    pol = "POZİTİF POLARİTE " if b["peak_voltage"] > 0 else "NEGATİF POLARİTE "
    header = f'{pol}   "{file_name}"   Analiz edildi'

    items = [
        ("Max Voltaj Değeri", f"{b['max_voltage']:.5f} x {scale_factor} = {b['max_voltage'] * scale_factor:.4f} V"),
        ("Min Voltaj Değeri", f"{b['min_voltage']:.5f} x {scale_factor} = {b['min_voltage'] * scale_factor:.4f} V"),
        ("T (90-30%) Değeri", format_duration(t['T0'], 5)),
        ("T1 Degeri", format_duration(t['T1'],5)),
        ("T2 (t=Time(%50 - O1))", t2_to_microseconds_only_display(t['T2'])),
        ("TPeak Değeri ", format_duration(b['Tpeak'], 5)),
        ("T görünür Değeri", format_duration(c['T_visible'],5)),
        ("TPSwitching Değeri", f"{tp_sw:.5f} µs (K*T)"),
        ("Tchop Front Değeri", format_duration(c['Tchop_front'],5)),
        ("Tchop Tail Değeri", format_duration(c['Tchop_tail'],5)),
        ("%90 Voltaj Değeri", f"{t['voltage_90']:.5f} x {scale_factor} = {t['voltage_90'] * scale_factor:.5f} V"),
        ("%30 Voltaj Değeri", f"{t['voltage_30']:.5f} x {scale_factor} = {t['voltage_30'] * scale_factor:.5f} V"),
        ("%90-%30 Fark Değeri",
         f"{abs(t['voltage_90'] - t['voltage_30']):.5f} x {scale_factor} = {abs(t['voltage_90'] - t['voltage_30']) * scale_factor:.4f} V"),
        ("Türev Değeri",
         f"dv/dt = {derivative_value:.6f} x {scale_factor} / 1000 = {(derivative_value * scale_factor / 1000):.5f} kV/µs"),
    ]

    width = max(len(lbl) for lbl, _ in items)
    return [header] + [f"{lbl:<{width}} = {val}" for lbl, val in items]


# Ana pencere boyutu değiştiğinde tüm panelleri yeniden düzenle
def on_window_configure(event):
    # Schedules a layout refresh after the main window size changes.
    if event.widget == root:
        if hasattr(on_window_configure, 'after_id'):
            root.after_cancel(on_window_configure.after_id)
        on_window_configure.after_id = root.after(200, update_layout)

def update_layout():
    # Updates panel widths and redraws the graph for the current window size.
    root.update_idletasks()
    window_width = root.winfo_width()

    if window_width < 1200:
        left_width = min(400, window_width // 3)
    else:
        left_width = 500

    # Sol panel genişliğini güncelle
    left_frame.configure(width=left_width)
    main_workspace.grid_columnconfigure(0, minsize=left_width)

    # Grafik panelini yeniden çiz
    if global_df is not None:
        root.after(100, update_graph)

def change_scale():
    # Starts the protected scale-change workflow for the current session.
    def after_admin():
        # Applies the new scale factor after successful authorization.
        global scale_factor
        root.lift()
        root.focus_force()
        root.update_idletasks()
        new_scale = modern_scale_dialog(root, scale_factor)
        if new_scale is not None:
            scale_factor = new_scale
            # Yeni skala ayarını kaydet
            save_settings({"scale_factor": scale_factor})
            if secili_dosya_yolu:
                analiz(secili_dosya_yolu)

    admin_giris_paneli_modern(root, after_admin)


def create_modern_result_card(parent, title, value, color_key):
    # Builds a styled result card for one computed metric.
    card_frame = tk.Frame(parent, bg=COLORS['bg_secondary'], relief='solid', bd=1)
    card_frame.pack(fill='x', padx=5, pady=2.1, expand=True)

    # Sol renk şeridi
    color_bar = tk.Frame(card_frame, bg=RENKLER[color_key], width=4)
    color_bar.pack(side='left', fill='y')

    content_frame = tk.Frame(card_frame, bg=COLORS['bg_secondary'])
    content_frame.pack(side='left', fill='both', expand=True, padx=15, pady=8.4)

    # Başlık
    title_label = tk.Label(
        content_frame, text=title, font=('Segoe UI', 13, 'bold'),
        bg=COLORS['bg_secondary'], fg=COLORS['text_primary'],
        anchor='w', width=20, justify='left'
    )
    title_label.grid(row=0, column=0, sticky='w', padx=(0, 2))

    # Eşittir
    eq_label = tk.Label(
        content_frame, text='=', font=('Segoe UI', 12, 'bold'),
        bg=COLORS['bg_secondary'], fg='#888888',
        anchor='center', width=2
    )
    eq_label.grid(row=0, column=1, sticky='we', padx=(2, 2))

    # Değer
    value_label = tk.Label(
        content_frame, text=value, font=('Segoe UI', 12, 'bold'),
        bg=COLORS['bg_secondary'], fg=RENKLER[color_key], anchor='w'
    )
    value_label.grid(row=0, column=2, sticky='w', padx=(2, 0))

    content_frame.grid_columnconfigure(0, weight=0, minsize=180)
    content_frame.grid_columnconfigure(1, weight=0, minsize=18)
    content_frame.grid_columnconfigure(2, weight=1)

    return card_frame


def update_results_panel():
    # Rebuilds the left-side results panel from the latest analysis rows.
    global file_label, header_bar

    # Sol paneli temizle
    for w in left_frame.winfo_children():
        w.destroy()

    # Analiz yoksa bekleme kartı göster
    if not last_sonuc_rows:
        empty_frame = tk.Frame(left_frame, bg=COLORS['bg_secondary'], relief='solid', bd=1)
        empty_frame.pack(fill='x', padx=10, pady=20)

        tk.Label(empty_frame, text="Dosya Bekleniyor",
                 font=('Segoe UI', 14, 'bold'), bg=COLORS['bg_secondary'],
                 fg=COLORS['text_secondary']).pack(pady=30)

        tk.Label(empty_frame, text="Analiz için bir CSV dosyası seçin\nveya sürükleyip bırakın",
                 font=('Segoe UI', 11), bg=COLORS['bg_secondary'],
                 fg=COLORS['text_secondary'], justify='center').pack(pady=(0, 30))

        file_label.config(text="")
        return

    # Başlığı güncelle
    header_text = last_sonuc_rows[0]
    is_positive = "POZİTİF" in header_text
    bar_color = COLORS['accent'] if is_positive else COLORS['danger']

    header_bar.config(bg=bar_color)
    file_label.config(text=header_text, bg=bar_color, fg='white')

    # Ana konteyner
    main_container = tk.Frame(left_frame, bg=COLORS['bg_main'])
    main_container.pack(fill="both", expand=True, padx=5, pady=5)

    # Başlık kartı
    header_card = tk.Frame(main_container, bg=bar_color, relief='flat')
    header_card.pack(fill='x', pady=(0, 15))
    tk.Label(header_card, text="HESAPLANAN DEĞERLER",
             font=('Segoe UI', 14, 'bold'), bg=bar_color, fg='white').pack(pady=15)

    # Sonuç kartları
    for satir in last_sonuc_rows[1:]:
        renk_key = "black"
        satir_title = satir.split(' = ')[0] if ' = ' in satir else satir

        for lbl, renk in DEGERLER_SIRALAMA:
            if satir_title.strip() == lbl:
                renk_key = renk
                break

        if ' = ' in satir:
            title, value = satir.split(' = ', 1)
        else:
            title, value = satir, ""

        create_modern_result_card(main_container, title, value, renk_key)

    # Spacer
    spacer = tk.Frame(main_container, bg=COLORS['bg_main'])
    spacer.pack(fill='both', expand=True, pady=(0, 2))


def update_graph():
    # Rebuilds the graph area with the latest processed voltage data.

    global graph_canvas, graph_toolbar, view_history, global_df

    if graph_canvas:
        graph_canvas.get_tk_widget().destroy()
        graph_canvas = None
    if graph_toolbar:
        graph_toolbar.destroy()
        graph_toolbar = None

    if global_df is None or global_df.empty:
        return

    # Veri hazırlığı
    x_us = global_df["time"].values * 1e6
    y = (global_df["volume"].values * scale_factor) / 1000
    df_xy = pd.DataFrame({'x': x_us, 'y': y}).drop_duplicates('x', keep='last').sort_values('x')
    x_us, y = df_xy['x'].to_numpy(), df_xy['y'].to_numpy()

    # Figure oluştur - ORİJİNAL BOYUTLAR
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(8, 6), dpi=110)
    fig.patch.set_facecolor(COLORS['bg_secondary'])
    ax.set_facecolor(COLORS['bg_secondary'])

    # Çizgi çiz
    ax.plot(x_us, y, linewidth=2.5, color=COLORS['primary'], alpha=0.9)

    # Etiketler
    ax.set_xlabel("Time (us)", fontsize=12, fontweight='bold',
                  color=COLORS['text_primary'], labelpad=10)
    ax.set_ylabel("Voltage (kV)", fontsize=12, fontweight='bold',
                  color=COLORS['text_primary'], labelpad=15)
    ax.set_title("Gerilim - Zaman Analizi", fontsize=16, fontweight='bold',
                 color=COLORS['secondary'], pad=15)

    # Grid ve stil
    ax.grid(True, alpha=0.3, color=COLORS['text_secondary'], linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(COLORS['border'])
        spine.set_linewidth(1.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Tick ayarları
    ax.tick_params(colors=COLORS['text_primary'], labelsize=10)
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda val, pos: f"{val * 1e-6:.6f}")
    )
    y_min, y_max = y.min(), y.max()
    y_margin = (y_max - y_min) * 0.05
    ax.set_ylim(y_min - y_margin, y_max + y_margin)

    fig.tight_layout(pad=0.1)

    # Canvas oluştur
    graph_canvas = FigureCanvasTkAgg(fig, master=right_frame)
    graph_canvas.draw()
    canvas_widget = graph_canvas.get_tk_widget()
    canvas_widget.pack(fill="both", expand=True, padx=5, pady=5)

    # Toolbar
    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
    class CustomToolbar(NavigationToolbar2Tk):
        def __init__(self, canvas, window):
            # Initializes the custom toolbar without packing it into the layout.
            super().__init__(canvas, window)
            self.pack_forget()

    graph_toolbar = CustomToolbar(graph_canvas, right_frame)

    # View history
    view_history.clear()
    view_history.append((ax.get_xlim(), ax.get_ylim()))

    # Undo butonu
    def undo_view():
        # Restores the previous zoom or pan view from the history stack.
        if len(view_history) > 1:
            view_history.pop()
            xlim, ylim = view_history[-1]
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
            graph_canvas.draw()

    undo_btn = tk.Button(
        master=canvas_widget, text="↶", font=('Segoe UI', 15, 'bold'),
        bg=COLORS['secondary'], fg='white', bd=0, relief='flat',
        command=undo_view, cursor='hand2'
    )
    undo_btn.place(in_=canvas_widget, relx=0.02, rely=0.98, anchor='sw')

    # Mouse event handlers
    pan_start = None
    is_panning = False

    def on_scroll(event):
        # Zooms the graph around the current mouse position.
        if event.inaxes != ax:
            return
        view_history.append((ax.get_xlim(), ax.get_ylim()))
        factor = 1.15 if event.button == 'down' else 1 / 1.15
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        xc, yc = event.xdata, event.ydata
        dx = (x1 - x0) * factor
        dy = (y1 - y0) * factor
        ax.set_xlim(xc - dx * (xc - x0) / (x1 - x0), xc + dx * (x1 - xc) / (x1 - x0))
        ax.set_ylim(yc - dy * (yc - y0) / (y1 - y0), yc + dy * (y1 - yc) / (y1 - y0))
        graph_canvas.draw()

    def on_press(event):
        # Captures the initial mouse position for graph panning.
        nonlocal pan_start, is_panning
        if event.button == 1 and event.inaxes == ax:
            pan_start = (event.xdata, event.ydata)
            is_panning = False
            view_history.append((ax.get_xlim(), ax.get_ylim()))

    def on_motion(event):
        # Pans the graph while the left mouse button is held down.
        nonlocal pan_start, is_panning
        if pan_start is None or event.inaxes != ax:
            return
        if not is_panning:
            is_panning = True
        dx = event.xdata - pan_start[0]
        dy = event.ydata - pan_start[1]
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        ax.set_xlim(x0 - dx, x1 - dx)
        ax.set_ylim(y0 - dy, y1 - dy)
        graph_canvas.draw_idle()

    def on_release(event):
        # Clears the panning state after the mouse button is released.
        nonlocal pan_start, is_panning
        pan_start = None
        is_panning = False

    # Event bağlantıları
    graph_canvas.mpl_connect('scroll_event', on_scroll)
    graph_canvas.mpl_connect('button_press_event', on_press)
    graph_canvas.mpl_connect('motion_notify_event', on_motion)
    graph_canvas.mpl_connect('button_release_event', on_release)


def setup_main_workspace():
    # Builds the main responsive workspace layout for the application.
    """Ana çalışma alanını kur - responsive tasarım"""
    global main_workspace, left_frame, right_frame

    # Ana çalışma alanı
    main_workspace = tk.Frame(root, bg=COLORS['bg_main'])
    main_workspace.pack(fill="both", expand=True, padx=10, pady=5)

    # Pencere boyutuna göre sütun ayarları
    def configure_columns():
        # Configures the workspace columns for the current window width.
        window_width = root.winfo_width()
        if window_width < 1000:  # Küçük ekran
            # Tek sütun - üst alt yerleşim
            main_workspace.grid_columnconfigure(0, weight=1)
            main_workspace.grid_rowconfigure(0, weight=0, minsize=300)
            main_workspace.grid_rowconfigure(1, weight=1)

            # Sol panel (sonuçlar) - üstte
            left_frame = tk.Frame(main_workspace, bg=COLORS['bg_main'], height=300)
            left_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
            left_frame.grid_propagate(False)

            # Sağ panel (grafik) - altta
            right_frame = tk.Frame(main_workspace, bg=COLORS['bg_secondary'], relief='solid', bd=1)
            right_frame.grid(row=1, column=0, sticky="nsew")

        else:  # Normal/büyük ekran
            # İki sütun - yan yana yerleşim
            left_width = min(500, window_width // 3)
            main_workspace.grid_columnconfigure(0, weight=0, minsize=left_width)
            main_workspace.grid_columnconfigure(1, weight=1)
            main_workspace.grid_rowconfigure(0, weight=1)

            # Sol panel (sonuçlar)
            left_frame = tk.Frame(main_workspace, bg=COLORS['bg_main'], width=left_width)
            left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            left_frame.grid_propagate(False)

            # Sağ panel (grafik)
            right_frame = tk.Frame(main_workspace, bg=COLORS['bg_secondary'], relief='solid', bd=1)
            right_frame.grid(row=0, column=1, sticky="nsew")

    # İlk kurulum
    root.after(100, configure_columns)

    # Pencere boyutu değiştiğinde yeniden düzenle
    def on_window_resize(event):
        # Schedules a responsive layout refresh after the window is resized.
        if event.widget == root:
            root.after(200, configure_columns)
            if global_df is not None:
                root.after(300, update_graph)

    root.bind('<Configure>', on_window_resize)


# 6. Ana fonksiyon koruması:
def analiz(dosya):
    # Runs the selected voltage analysis workflow for the provided file path.
    """Ana analiz fonksiyonu - Güvenli versiyon"""
    global secili_dosya_yolu, last_sonuc_rows, global_df, last_pdf_path, pdf_open_button

    if not dosya or not os.path.exists(dosya):
        messagebox.showerror("Hata!", "Geçerli dosya seçilmedi.")
        return

    try:
        header_bar.config(bg=COLORS['warning'])
        file_label.config(text=f"{os.path.basename(dosya)} analiz ediliyor...", bg=COLORS['warning'], fg='white')
        root.update_idletasks()
        secili_dosya_yolu = dosya
        last_pdf_path = None
        if pdf_open_button:
            pdf_open_button.config(state="disabled")
        df = read_data(dosya)

        if df is None or df.empty:
            messagebox.showerror("Hata!", "Geçerli ölçüm verisi bulunamadı.")
            return

        global_df = df.copy()  # Güvenli kopya

        # Veri validasyonu
        if df.shape[0] < 10:  # Minimum veri kontrolü
            messagebox.showerror("Hata!", "Yetersiz veri noktası (minimum 10 gerekli).")
            return

        # Hesaplamalar - Exception handling ile
        try:
            b = calculate_basic_values(df)
            t = calculate_time_values(df, b)
            tp_sw = calculate_tp_switching(t)
            c = calculate_chop_values(df, b, t)
            derivative_value = calculate_derivative_value(t)
        except Exception as calc_error:
            messagebox.showerror("Hesaplama Hatası!", f"Hesaplama sırasında hata:\n{str(calc_error)}")
            return

        # Sonuç validasyonu
        if not all([b, t, c]):
            messagebox.showerror("Hata!", "Hesaplama sonuçları eksik!")
            return

        # Sonuçları formatla
        last_sonuc_rows = format_results(b, t, c, tp_sw, os.path.basename(dosya), derivative_value)

        # UI güncellemesi - try-catch ile
        try:
            update_results_panel()
            update_graph()
        except Exception as ui_error:
            print(f"UI güncelleme hatası: {ui_error}")

        messagebox.showinfo("Başarılı", f"'{os.path.basename(dosya)}' dosyası başarıyla analiz edildi!")

    except Exception as e:
        error_msg = f"Analiz sırasında hata oluştu:\n{str(e)}"
        print(error_msg)  # Log için
        messagebox.showerror("Hata!", error_msg)


def dosya_sec():
    # Opens a file picker and starts the analysis for the selected CSV file.
    """Dosya seçim dialogu"""
    f = filedialog.askopenfilename(
        title="CSV Dosyası Seç",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        initialdir=os.path.expanduser("~")
    )
    if f:
        analiz(f)


def on_drop(event):
    # Processes files dropped onto the application window.
    """Drag & drop handler"""
    try:
        path_raw = event.data.strip()
        if path_raw.startswith("{") and path_raw.endswith("}"):
            path_raw = path_raw[1:-1]
        path = path_raw.strip().replace('"', '')

        if not os.path.isfile(path):
            raise FileNotFoundError(f"Dosya bulunamadı: {path}")
        analiz(path)
    except Exception as e:
        messagebox.showerror("Sürükle-Bırak Hatası", f"Dosya okunamadı:\n{e}")


def dosyayi_varsayilan_uygulama_ile_ac(path):
    # Opens the given file with the default operating system application.
    if not path or not os.path.exists(path):
        raise FileNotFoundError("Dosya bulunamadi.")
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.call(["open", path])
    else:
        import subprocess
        subprocess.call(["xdg-open", path])

def pdf_ac():
    # Opens the last generated PDF report when it is available.
    global last_pdf_path
    if last_pdf_path and os.path.exists(last_pdf_path):
        try:
            dosyayi_varsayilan_uygulama_ile_ac(last_pdf_path)
        except Exception as e:
            messagebox.showerror("Hata!", f"PDF acilamadi:\n{e}")
    else:
        messagebox.showwarning("Uyarı", "Henüz PDF oluşturulmadı veya dosya yok.")

def pdf_olustur():
    # Builds and saves a PDF report for the current analysis result.
    """PDF raporu oluştur"""
    global last_sonuc_rows, global_df, secili_dosya_yolu, scale_factor, last_pdf_path, pdf_open_button

    if not last_sonuc_rows or global_df is None:
        messagebox.showwarning("Uyarı", "Önce bir dosya analiz edin.")
        return

    name = modern_pdf_name_dialog(root)
    if not name:
        return

    save_dir = filedialog.askdirectory(title="PDF Kaydedilecek Klasörü Seç")
    if not save_dir:
        return

    pdf_path = os.path.join(save_dir, name + ".pdf")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Image, Paragraph
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from datetime import datetime

        # Font ayarları
        try:
            pdfmetrics.registerFont(TTFont('Turkish', 'arial.ttf'))
            font_name = "Turkish"
        except:
            try:
                pdfmetrics.registerFont(TTFont('Turkish', 'DejaVuSans.ttf'))
                font_name = "Turkish"
            except:
                font_name = "Helvetica"

        w, h = A4
        left_margin = right_margin = 65
        doc = SimpleDocTemplate(
            pdf_path, pagesize=A4,
            leftMargin=left_margin, rightMargin=right_margin,
            topMargin=65, bottomMargin=20
        )
        story = []

        # History
        tarih_saat = datetime.now().strftime('%d.%m.%Y %H:%M')
        tarih_style = ParagraphStyle(
            name='tarih', alignment=2, fontName=font_name,
            fontSize=10, textColor='#888888'
        )
        story.append(Paragraph(tarih_saat, tarih_style))
        story.append(Spacer(1, 12))

        # Başlıklar
        style_header = ParagraphStyle(
            name='Header', fontName=font_name, fontSize=21,
            alignment=TA_CENTER, textColor='#1e3a8a', spaceAfter=8
        )
        style_report = ParagraphStyle(
            name='Report', fontName=font_name, fontSize=13,
            alignment=TA_CENTER, textColor='#111827', spaceAfter=8
        )
        style_analiz = ParagraphStyle(
            name='Analiz', fontName=font_name, fontSize=16,
            alignment=TA_CENTER, textColor='#f59e0b', spaceAfter=10
        )

        story.append(Paragraph(APP_CONFIG["organization_name"], style_header))
        story.append(Spacer(1, 3))
        story.append(Paragraph(APP_CONFIG["voltage_report_title"], style_report))
        story.append(Spacer(1, 6))
        story.append(Paragraph("Analiz Sonuçları", style_analiz))
        story.append(Spacer(1, 12))

        # Table Data
        data = []
        if last_sonuc_rows:
            data.append([last_sonuc_rows[0], "", ""])
            for satir in last_sonuc_rows[1:]:
                if ' = ' in satir:
                    parcalar = satir.split(' = ', 1)
                    data.append([parcalar[0], "=", parcalar[1]])
                else:
                    data.append([satir, "", ""])

        table_width = w - left_margin - right_margin
        col_widths = [table_width * 0.36, table_width * 0.08, table_width * 0.56]

        table = Table(data, colWidths=col_widths, hAlign='CENTER')
        table_style = TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 13),
            ('TEXTCOLOR', (0, 0), (-1, 0), '#1e3a8a'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('FONTSIZE', (0, 1), (-1, -1), 12),
            ('TEXTCOLOR', (0, 1), (-1, -1), '#111827'),
            ('ALIGN', (1, 1), (1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.18, colors.lightgrey),
        ])
        table.setStyle(table_style)
        story.append(table)
        story.append(Spacer(1, 5))

        # Graphs
        x_us = global_df["time"].values * 1e6
        y = global_df["volume"].values * scale_factor / 1000
        df_xy = pd.DataFrame({'x': x_us, 'y': y}).drop_duplicates('x', keep='last').sort_values('x')

        buf = io.BytesIO()
        fig2, ax2 = plt.subplots(figsize=(8, 5.1), dpi=210)
        fig2.patch.set_facecolor("#f8fafc")
        ax2.set_facecolor("#f8fafc")
        ax2.plot(df_xy['x'], df_xy['y'], linewidth=2.5, color='#1e3a8a')
        ax2.set_xlabel("Time (us)", fontweight='bold')
        ax2.set_ylabel("Voltage (kV)", fontweight='bold')
        ax2.set_title("Gerilim - Zaman Grafiği", fontsize=13, color='#f59e0b', pad=10)
        ax2.grid(alpha=0.3)
        for spine in ax2.spines.values():
            spine.set_visible(False)
        ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda val, pos: f"{val * 1e-6:.6f}"))
        fig2.tight_layout()
        fig2.savefig(buf, format='png', facecolor="#f8fafc")
        plt.close(fig2)
        buf.seek(0)

        img = Image(buf)
        img.drawWidth = 470
        img.drawHeight = 270
        img.hAlign = 'CENTER'
        story.append(img)

        doc.build(story)
        last_pdf_path = pdf_path
        if pdf_open_button:
            pdf_open_button.config(state="normal")
        messagebox.showinfo("Başarılı", f"PDF başarıyla kaydedildi:\n{pdf_path}")
        if APP_CONFIG.get("pdf_auto_open", True):
            try:
                dosyayi_varsayilan_uygulama_ile_ac(pdf_path)
            except Exception as e:
                messagebox.showwarning("Uyarı", f"PDF kaydedildi fakat otomatik açılamadı:\n{e}")

    except Exception as e:
        messagebox.showerror("Hata!", f"PDF oluşturulurken hata:\n{str(e)}")


def modern_pdf_name_dialog(parent):
    # Shows a small modal dialog that collects the PDF file name.
    """PDF adı girme dialogu"""
    dialog = tk.Toplevel(parent)
    dialog.title("PDF Adı Belirle")
    dialog.geometry("350x160")
    dialog.resizable(False, False)
    dialog.configure(bg="#f8fafc")
    dialog.grab_set()
    dialog.transient(parent)
    dialog.focus_force()

    # Ortala
    dialog.update_idletasks()
    x = parent.winfo_rootx() + parent.winfo_width() // 2 - 175
    y = parent.winfo_rooty() + parent.winfo_height() // 2 - 80
    dialog.geometry(f"+{x}+{y}")

    tk.Label(dialog, text="PDF dosya adını girin:",
             font=("Segoe UI", 12, "bold"), bg="#f8fafc", fg="#1e3a8a").pack(pady=(22, 5))

    entry = tk.Entry(dialog, font=("Segoe UI", 13), justify="center",
                     width=26, bd=2, relief="groove")
    entry.pack(pady=(5, 10))
    entry.focus_set()

    result = {"name": None}

    def ok():
        # Confirms the current dialog value and closes the window.
        value = entry.get().strip()
        if value:
            result["name"] = value
            dialog.destroy()

    def cancel():
        # Closes the current dialog without saving a new value.
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg="#f8fafc")
    btn_frame.pack(pady=5)

    ok_btn = tk.Button(btn_frame, text="OK", font=("Segoe UI", 11, "bold"),
                       bg="#1e3a8a", fg="white", width=9, command=ok)
    cancel_btn = tk.Button(btn_frame, text="Cancel", font=("Segoe UI", 11, "bold"),
                           bg="#e5e7eb", fg="#374151", width=9, command=cancel)
    ok_btn.pack(side="left", padx=7)
    cancel_btn.pack(side="left", padx=7)

    entry.bind("<Return>", lambda e: ok())
    dialog.wait_window()
    return result["name"]


def modern_scale_dialog(parent, current_scale):
    # Shows the scale factor editor dialog and validates numeric input.
    """Ölçek değiştirme dialogu"""
    dialog = tk.Toplevel(parent)
    dialog.title("Ölçek Değiştir")
    dialog.geometry("370x160")
    dialog.resizable(False, False)
    dialog.configure(bg="#f8fafc")
    dialog.grab_set()
    dialog.transient(parent)
    dialog.focus_force()

    # Ortala
    dialog.update_idletasks()
    x = parent.winfo_rootx() + parent.winfo_width() // 2 - 185
    y = parent.winfo_rooty() + parent.winfo_height() // 2 - 80
    dialog.geometry(f"+{x}+{y}")

    tk.Label(dialog, text=f"Yeni ölçek faktörünü girin (şu an: {current_scale}):",
             font=("Segoe UI", 11, "bold"), bg="#f8fafc", fg="#1e3a8a").pack(pady=(18, 7))

    entry = tk.Entry(dialog, font=("Segoe UI", 13), justify="center",
                     width=20, bd=2, relief="groove")
    entry.pack(pady=(0, 10))
    entry.insert(0, str(current_scale))
    entry.focus_set()

    result = {"scale": None}

    def ok():
        # Confirms the current dialog value and closes the window.
        try:
            val = float(entry.get())
            if val > 0:
                result["scale"] = val
                dialog.destroy()
        except Exception:
            entry.config(bg="#fee2e2")

    def cancel():
        # Closes the current dialog without saving a new value.
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg="#f8fafc")
    btn_frame.pack(pady=5)

    tk.Button(btn_frame, text="OK", font=("Segoe UI", 11, "bold"),
              bg="#1e3a8a", fg="white", width=9, command=ok).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Cancel", font=("Segoe UI", 11, "bold"),
              bg="#e5e7eb", fg="#374151", width=9, command=cancel).pack(side="left", padx=6)

    entry.bind("<Return>", lambda e: ok())
    dialog.wait_window()
    return result["scale"]


if __name__ == "__main__":
    # Global değişkenleri başlat
    initialize_globals()

    # Ana pencere oluştur
    try:
        root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
        # Geri kalan kod...
    except Exception as e:
        print(f"Program başlatma hatası: {e}")
        import sys

        sys.exit(1)
    if DND_AVAILABLE:
        try:
            root.tk.call('package', 'require', 'tkdnd')
            print("tkdnd paketi başarıyla yüklendi.")
        except tk.TclError as e:
            print("ERROR: tkdnd yüklü değil veya bulunamıyor:", e)

    root.title(APP_CONFIG["voltage_window_title"])
    root.geometry("1600x900")
    root.configure(bg=COLORS['bg_main'])
    root.minsize(800, 450)

    # İkon
    try:
        root.iconbitmap("icon.ico")
    except:
        pass

    # Üst başlık paneli
    header_panel = tk.Frame(root, bg=COLORS['bg_secondary'], relief='flat', bd=2)
    header_panel.pack(side=tk.TOP, fill="x", padx=10, pady=(10, 5))

    header_bar = tk.Frame(header_panel, height=80, bg=COLORS['accent'])
    header_bar.pack(fill='x')

    file_label = tk.Label(
        header_bar, text="Analiz Sonucu Bekleniyor…",
        font=('Segoe UI', 18, 'bold'), bg=COLORS['accent'],
        fg='white', anchor='center'
    )
    file_label.pack(expand=True, pady=20)

    # Buton paneli
    button_panel = tk.Frame(root, bg=COLORS['bg_main'], height=80)
    button_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)
    button_panel.pack_propagate(False)
    button_panel.grid_columnconfigure(0, weight=1)
    button_panel.grid_columnconfigure(1, weight=1)
    button_panel.grid_columnconfigure(2, weight=1)
    button_panel.grid_columnconfigure(3, weight=1)

    # Butonlar
    btn_csv = create_modern_button(
        button_panel, "CSV DOSYASI SEÇ", dosya_sec, "#69A4C5", "#4479a2"
    )
    btn_csv.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=10)

    btn_scale = create_modern_button(
        button_panel, "ÖLÇEK DEĞİŞTİR", change_scale,
        COLORS['warning'], '#d97706'
    )
    btn_scale.grid(row=0, column=1, sticky="ew", padx=5, pady=10)

    btn_pdf = create_modern_button(
        button_panel, "PDF OLUŞTUR", pdf_olustur,
        COLORS['accent'], '#059669'
    )
    btn_pdf.grid(row=0, column=2, sticky="ew", padx=(5, 5), pady=10)

    open_btn_frame = tk.Frame(button_panel, bg=COLORS['bg_main'])
    pdf_open_button = tk.Button(
        open_btn_frame,
        text="PDF AÇ",
        command=pdf_ac,
        font=('Segoe UI', 12, 'bold'),
        bg='#1e3a8a',
        fg='white',
        activebackground='#2563eb',
        activeforeground='white',
        disabledforeground='#e5e7eb',
        bd=0,
        relief='flat',
        padx=20,
        pady=10,
        cursor='hand2',
        state='disabled'
    )
    pdf_open_button.pack(fill='both', expand=True)
    open_btn_frame.grid(row=0, column=3, sticky="ew", padx=(5, 0), pady=10)

    # Ana çalışma alanı
    main_workspace = tk.Frame(root, bg=COLORS['bg_main'])
    main_workspace.pack(fill="both", expand=True, padx=10, pady=5)
    main_workspace.grid_columnconfigure(0, weight=0, minsize=500)
    main_workspace.grid_columnconfigure(1, weight=1)
    main_workspace.grid_rowconfigure(0, weight=1)

    # Sol panel (sonuçlar)
    left_frame = tk.Frame(main_workspace, bg=COLORS['bg_main'], width=500)
    left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left_frame.grid_propagate(False)

    # Sağ panel (grafik)
    right_frame = tk.Frame(main_workspace, bg=COLORS['bg_secondary'], relief='solid', bd=1)
    right_frame.grid(row=0, column=1, sticky="nsew")

    # Drag & Drop
    if DND_AVAILABLE:
        root.drop_target_register(DND_FILES)
        root.dnd_bind('<<Drop>>', on_drop)

    # İlk panel güncellemesi
    update_results_panel()

    # Ana döngü
    root.mainloop()
