"""Desktop application for analyzing current waveform data and exporting PDF reports."""

# kütüphaneler
import io, os, sys, json, subprocess
from datetime import datetime
import bcrypt
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import Button

# pdf üretimi için reportlab
try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Image, Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    ReportLabVar = True
except Exception as e:
    print(f"reportlab yüklenemedi: {e}")
    ReportLabVar = False

# arayüz
import tkinter as tk
from tkinter import filedialog, messagebox
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    SurukleBirakVar = True
except Exception as e:
    print(f"tkinterdnd2 yüklenemedi: {e}")
    SurukleBirakVar = False
    TkinterDnD = tk.Tk

# genel ayarlar ve sabitler
AyarDosyasi = "current_settings.json"
UygulamaAyarDosyasi = "app_config.json"
VarsayilanUygulamaAyarlari = {
    "organization_name": "Custom Organization",
    "current_window_title": "Current Analysis Program",
    "current_report_title": "Current Analysis Report",
    "scale_auth": {
        "enabled": False,
        "username": "",
        "password_hash": "",
    },
    "pdf_auto_open": True,
}

def SozlukleriBirlestir(temel: dict, gelen: dict) -> dict:
    # Recursively merges the loaded application settings with the defaults.
    sonuc = dict(temel)
    for anahtar, deger in gelen.items():
        if isinstance(deger, dict) and isinstance(sonuc.get(anahtar), dict):
            sonuc[anahtar] = SozlukleriBirlestir(sonuc[anahtar], deger)
        else:
            sonuc[anahtar] = deger
    return sonuc

def UygulamaAyarlariniYukle() -> dict:
    # Loads the optional application configuration from the local JSON file.
    if os.path.exists(UygulamaAyarDosyasi):
        try:
            with open(UygulamaAyarDosyasi, "r", encoding="utf-8") as f:
                return SozlukleriBirlestir(VarsayilanUygulamaAyarlari, json.load(f))
        except Exception as e:
            print("uygulama ayarlari okunamadi:", e)
    return dict(VarsayilanUygulamaAyarlari)

UygulamaAyarlari = UygulamaAyarlariniYukle()

HesaplananDegerlerSirasi = [
    ("Max Current (Ip)", "red"), ("Time to Peak (Tp)", "black"),
    ("Half Peak Time (T2)", "black"), ("Rise Time (T1)", "black"),
    ("Signal Beginning", "darkgreen"), ("Time to Zero (T0)", "darkgreen"),
    ("Total Duration (Td)", "darkgreen"), ("Pulse Avg Current", "blue"),
    ("Avg Current", "blue"), ("Charge", "purple"),
    ("Charge (Q)", "purple"), ("Action Integral", "purple"),
]

Renkler1 = {
    "red": "#E74C3C",
    "black": "#2C3E50",
    "blue": "#3498DB",
    "darkgreen": "#27AE60",
    "purple": "#9B59B6",
}

Renkler2 = {
    "primary": "#3498DB",
    "secondary": "#f59e0b",
    "accent": "#71C832",
    "danger": "#CC0000",
    "warning": "#f59e0b",
    "bg_main": "#f8fafc",
    "bg_secondary": "#ffffff",
    "text_primary": "#111827",
    "text_secondary": "#6b7280",
    "border": "#e5e7eb",
    "result_bg": "#FFFDD0",
}

# uygulama durumu
GorunumGecmisi = []
SonSonucSatirlari = []
SonMetrikler = None
SonPdfYolu = None

GenelVeri = None
SeciliDosyaYolu = ""
OlcekFaktoru = 1.0

Kok = None
SolCerceve = None
SagCerceve = None
DosyaEtiketi = None
UstCizgi = None
AcButonu = None

ModDegeri = None
ModButonlari = {}
GrafikKanvasi = None
GrafikAracCubugu = None

# ayar okuma ve yazma
def AyarlariYukle():
    # Loads the persisted user settings from disk when the file exists.
    if os.path.exists(AyarDosyasi):
        try:
            with open(AyarDosyasi, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def AyarlariKaydet(ayarlar: dict):
    # Saves the current user settings to the local JSON file.
    try:
        with open(AyarDosyasi, "w", encoding="utf-8") as f:
            json.dump(ayarlar, f, indent=2)
    except Exception as e:
        print("ayarlar kaydedilemedi:", e)

Ayarlar = AyarlariYukle()
OlcekFaktoru = Ayarlar.get("scale_factor", 1.0)
SonMod = Ayarlar.get("mode", "A")

# yardımcılar
def DurumDegiskenleriniSifirla():
    # Resets the shared runtime state used by the current analysis workflow.
    global GorunumGecmisi, SonSonucSatirlari, \
        GenelVeri, GrafikKanvasi, GrafikAracCubugu, \
        SonMetrikler
    GorunumGecmisi = []
    SonSonucSatirlari = []
    GenelVeri = None
    GrafikKanvasi = None
    GrafikAracCubugu = None
    SonMetrikler = None

def ZamanAkimOku(yol: str) -> tuple:
    # Reads the input file and returns cleaned time-current data.
    if not os.path.exists(yol):
        raise FileNotFoundError(f"dosya yok: {yol}")

    with open(yol, "rb") as f:
        ham = f.read()

    metin = None
    for enc in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            metin = ham.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if metin is None:
        raise ValueError("dosya çözülemedi...")

    satirlar = metin.splitlines()
    if not satirlar:
        raise ValueError("dosya boş")

    maks_sutun = max(s.count(",") + 1 for s in satirlar)
    duzelt = []
    for s in satirlar:
        parcalar = s.strip().split(",")
        if len(parcalar) < maks_sutun:
            parcalar += [""] * (maks_sutun - len(parcalar))
        duzelt.append(parcalar)

    baslangic = 0
    for i, p in enumerate(duzelt):
        try:
            float(p[0].replace(",", ".").replace("+", ""))
            float(p[1].replace(",", ".").replace("+", ""))
            baslangic = i
            break
        except Exception:
            continue

    from io import StringIO
    arabellek = StringIO("\n".join(",".join(p) for p in duzelt[baslangic:]) + "\n")
    df = None
    for ayir in [",", ";", "\t"]:
        try:
            arabellek.seek(0)
            df = pd.read_csv(arabellek, sep=ayir, header=None, engine="python", dtype=str)
            if df.shape[1] >= 2:
                break
        except Exception:
            continue
    if df is None or df.shape[1] < 2:
        raise ValueError("HATA!")

    df = df.iloc[:, :2]
    df.columns = ["time", "current"]
    df["time"] = pd.to_numeric(df["time"].astype(str).str.replace(",", ".").str.replace("+", ""), errors="coerce")
    df["current"] = pd.to_numeric(df["current"].astype(str).str.replace(",", ".").str.replace("+", ""), errors="coerce")
    df = df.dropna().sort_values("time").reset_index(drop=True)

    if df.empty:
        raise ValueError("sayısal veri yok")

    return df, baslangic, len(df)

def ZamanBiriminiTahminEtVeMs(zaman: np.ndarray):
    # Normalizes detected time values into milliseconds for downstream calculations.
    genislik = np.nanmax(zaman) - np.nanmin(zaman)
    if genislik <= 0:
        return zaman * 1e3, "unknown"
    if np.nanmax(zaman) < 0.02:
        return zaman * 1e3, "s"
    if np.nanmax(zaman) < 200:
        return zaman, "ms"
    return zaman * 1e-3, "us"

def AgresifYumusat(x: np.ndarray, pencere: int = 15) -> np.ndarray:
    # Applies repeated moving-average smoothing to the waveform data.
    if pencere <= 1 or len(x) < pencere:
        return x
    cekirdek = np.ones(pencere) / pencere
    y = np.convolve(x, cekirdek, mode="same")
    y = np.convolve(y, cekirdek, mode="same")
    return y

def TetikZamaniniDogrulaHesapla(zaman_ms: np.ndarray, akim: np.ndarray, tepe_indeks: int, tepe_deger: float):
    # Calculates trigger and threshold crossing times around the waveform peak.
    zaman_yukari = zaman_ms[:tepe_indeks + 1]
    y = np.abs(akim[:tepe_indeks + 1])
    A = abs(tepe_deger)

    def IlkKesisim(seviye, bas_indeks=0):
        # Finds the first interpolated threshold crossing in the rising segment.
        for i in range(max(1, bas_indeks), len(y)):
            if y[i-1] < seviye <= y[i]:
                t1, t2 = zaman_yukari[i-1], zaman_yukari[i]
                y1, y2 = y[i-1], y[i]
                if y2 != y1:
                    return t1 + (seviye - y1) * (t2 - t1) / (y2 - y1)
                else:
                    return t2
        idx = np.argmin(np.abs(y[bas_indeks:] - seviye)) + bas_indeks
        return zaman_yukari[idx]

    t_05 = IlkKesisim(0.05 * A)
    t_30 = IlkKesisim(0.30 * A)

    if abs(t_30 - t_05) > 1e-12:
        m = (0.30 * A - 0.05 * A) / (t_30 - t_05)
        b = 0.05 * A - m * t_05
        tetik_zamani = -b / m if abs(m) > 1e-12 else t_05
    else:
        tetik_zamani = t_05

    t_10 = IlkKesisim(0.10 * A)
    t_90 = IlkKesisim(0.90 * A, bas_indeks=1)

    return (
        tetik_zamani,
        t_10, 0.10 * A,
        t_30, 0.30 * A,
        t_90, 0.90 * A,
        t_05, 0.05 * A
    )

# varyant hesaplamaları A B C D
def MetrikleriHesaplaA(zaman_ms: np.ndarray, akim: np.ndarray, taban: float, zaman_olcek: float = 1.0):
    # Calculates variant A waveform metrics from the aligned current signal.
    akim_abs = np.abs(akim - taban)
    tepe_indeks = np.argmax(akim_abs)
    tepe_deger = akim[tepe_indeks]
    tepe_zaman_ham = zaman_ms[tepe_indeks]

    (tetik, t10, _, t30, _, t90, _, t05, _) = TetikZamaniniDogrulaHesapla(
        zaman_ms, akim - taban, tepe_indeks, tepe_deger - taban
    )

    zaman_hizali = zaman_ms - tetik
    tepe = tepe_zaman_ham - tetik

    akim_sonra = np.abs(akim - taban)[tepe_indeks:]
    t_sonra = zaman_hizali[tepe_indeks:]
    yarinin_altinda = np.where(akim_sonra <= abs(tepe_deger - taban) * 0.50)[0]
    T2 = t_sonra[yarinin_altinda[0]] if len(yarinin_altinda) else zaman_hizali[-1]

    sifir_esik = abs(tepe_deger - taban) * 0.0025
    sifirin_altinda = np.where(akim_sonra <= sifir_esik)[0]
    T0 = t_sonra[sifirin_altinda[0]] if len(sifirin_altinda) else zaman_hizali[-1]

    Td = tetik + T0

    tetik_idx = np.argmin(np.abs(zaman_hizali - 0))
    bitis_idx = np.argmin(np.abs(zaman_hizali - T0))
    nabiz_akim = akim[tetik_idx:bitis_idx + 1]
    nabiz_zaman_ms = zaman_ms[tetik_idx:bitis_idx + 1]

    nabiz_zaman_s = nabiz_zaman_ms * 1e-3
    EylemIntegrali = np.trapezoid(nabiz_akim ** 2, nabiz_zaman_s)

    return {
        "Ip": tepe_deger,
        "Tp": tepe * zaman_olcek,
        "T1_rise": (t90 - t10) * zaman_olcek,
        "T2_halffall": T2 * zaman_olcek,
        "T0_zero": T0 * zaman_olcek,
        "Td_duration": Td * zaman_olcek,
        "trigger_time": tetik * zaman_olcek,
        "ActionIntegral": EylemIntegrali,
    }

def SonuclariBicimlendirA(metrik: dict, dosya_adi: str):
    # Formats variant A metrics into display-ready result rows.
    pol = "POZİTİF POLARİTE " if metrik["Ip"] > 0 else "NEGATİF POLARİTE "
    baslik = f'{pol}"{dosya_adi}" Analiz edildi'
    ogeler = [
        ("Max Current (Ip)", f"{metrik['Ip'] / 1e3:.5f} kA"),
        ("Time to Peak (Tp)", f"{metrik['Tp']*1e6:.5f} µs"),
        ("Half Peak Time (T2)", f"{metrik['T2_halffall']*1e6:.5f} µs"),
        ("Rise Time (T1)", f"{metrik['T1_rise']*1e6:.5f} µs"),
        ("Time to Zero (T0)", f"{metrik['T0_zero']*1e6:.5f} µs"),
        ("Action Integral", f"{metrik['ActionIntegral']/1e3:.5f} ×10⁶ A²s"),
    ]
    genislik = max(len(k) for k, _ in ogeler)
    return [baslik] + [f"{k:<{genislik}} = {v}" for k, v in ogeler]

def MetrikleriHesaplaB(zaman_ms: np.ndarray, akim: np.ndarray, taban: float, zaman_olcek: float = 1.0):
    # Calculates variant B waveform metrics from the aligned current signal.
    akim_abs = np.abs(akim - taban)
    tepe_indeks = np.argmax(akim_abs)
    tepe_deger = akim[tepe_indeks]
    tepe_zaman_ham = zaman_ms[tepe_indeks]

    (tetik, t10, _, t30, _, t90, _, t05, _) = TetikZamaniniDogrulaHesapla(
        zaman_ms, akim - taban, tepe_indeks, tepe_deger - taban
    )

    zaman_hizali = zaman_ms - tetik
    tepe = tepe_zaman_ham - tetik

    akim_sonra = np.abs(akim - taban)[tepe_indeks:]
    t_sonra = zaman_hizali[tepe_indeks:]
    yarinin_altinda = np.where(akim_sonra <= abs(tepe_deger - taban) * 0.50)[0]
    T2 = t_sonra[yarinin_altinda[0]] if len(yarinin_altinda) else zaman_hizali[-1]

    sifir_esik = abs(tepe_deger - taban) * 0.0025
    sifirin_altinda = np.where(akim_sonra <= sifir_esik)[0]
    T0 = (zaman_ms - tetik)[tepe_indeks:][sifirin_altinda[0]] if len(sifirin_altinda) else zaman_ms[-1] - tetik

    tetik_idx = np.argmin(np.abs(zaman_hizali - 0))
    bitis_idx = np.argmin(np.abs(zaman_hizali - T0))
    nabiz_akim = akim[tetik_idx:bitis_idx + 1]
    nabiz_zaman_ms = zaman_ms[tetik_idx:bitis_idx + 1]

    nabiz_zaman_s = nabiz_zaman_ms * 1e-3
    NabizOrtalama = np.mean(nabiz_akim)
    Yuk = np.trapezoid(nabiz_akim, nabiz_zaman_s)

    return \
        {
        "Ip": tepe_deger,
        "Tp": tepe * zaman_olcek,
        "T1_rise": (t90 - t10) * zaman_olcek,
        "T2_halffall": T2 * zaman_olcek,
        "T0_zero": T0 * zaman_olcek,
        "trigger_time": tetik * zaman_olcek,
        "PulseAvgCurrent": NabizOrtalama,
        "Charge": Yuk,
        }

def SonuclariBicimlendirB(metrik: dict, dosya_adi: str):
    # Formats variant B metrics into display-ready result rows.
    pol = "POZİTİF POLARİTE " if metrik["Ip"] > 0 else "NEGATİF POLARİTE "
    baslik = f'{pol}"{dosya_adi}" Analiz edildi'
    ogeler = \
        [
        ("Max Current (Ip)", f"{metrik['Ip']:.5f} A"),
        ("Pulse Avg Current", f"{metrik['PulseAvgCurrent']:.5f} A"),
        ("Time to Peak (Tp)", f"{metrik['Tp']*1e3:.5f} ms"),
        ("Half Peak Time (T2)", f"{metrik['T2_halffall']*1e3:.5f} ms"),
        ("Rise Time (T1)", f"{metrik['T1_rise']*1e3:.5f} ms"),
        ("Time to Zero (T0)", f"{metrik['T0_zero']*1e3:.5f} ms"),
        ("Charge (Q)", f"{metrik['Charge']*1e3:.5f} C"),
        ]
    genislik = max(len(k) for k, _ in ogeler)
    return [baslik] + [f"{k:<{genislik}} = {v}" for k, v in ogeler]

def MetrikleriHesaplaC(zaman_ms: np.ndarray, akim: np.ndarray, taban: float):
    # Calculates variant C waveform metrics from the aligned current signal.
    akim_abs = np.abs(akim - taban)
    tepe_indeks = np.argmax(akim_abs)
    Ip = akim[tepe_indeks]

    def TetikZamaniBul(zaman_ms, akim, taban):
        # Estimates the trigger time for variant C using threshold intersections.
        akim_abs = np.abs(akim - taban)
        tepe_indeks = np.argmax(akim_abs)
        tepe_deger = akim[tepe_indeks]
        c_abs = np.abs(akim[:tepe_indeks + 1])
        akim_05 = abs(tepe_deger - taban) * 0.05
        akim_30 = abs(tepe_deger - taban) * 0.30
        idx_05 = np.argmin(np.abs(c_abs - akim_05))
        idx_30 = np.argmin(np.abs(c_abs - akim_30))
        t_05 = zaman_ms[idx_05]; i_05 = c_abs[idx_05]
        t_30 = zaman_ms[idx_30]; i_30 = c_abs[idx_30]
        if abs(t_30 - t_05) > 1e-6 and abs(i_30 - i_05) > 1e-6:
            m = (i_30 - i_05) / (t_30 - t_05)
            b = i_05 - m * t_05
            tetik = -b / m if abs(m) > 1e-6 else t_05
        else:
            tetik = t_05
        return tetik

    tetik = TetikZamaniBul(zaman_ms, akim, taban)
    hizali = zaman_ms - tetik

    sifir_esik = abs(Ip - taban) * 0.0025
    akim_sonra = akim_abs[tepe_indeks:]
    t_sonra = hizali[tepe_indeks:]
    sifirin_altinda = np.where(akim_sonra <= sifir_esik)[0]
    T0_hizali = t_sonra[sifirin_altinda[0]] if len(sifirin_altinda) else hizali[-1]

    tetik_idx = np.argmin(np.abs(hizali - 0))
    bitis_idx = np.argmin(np.abs(hizali - T0_hizali))
    nabiz_akim = akim[tetik_idx:bitis_idx + 1]
    nabiz_zaman_ms = zaman_ms[tetik_idx:bitis_idx + 1]

    NabizOrtalama = np.mean(nabiz_akim)
    nabiz_zaman_s = nabiz_zaman_ms * 1e-3
    Yuk = np.trapezoid(nabiz_akim, nabiz_zaman_s)

    return \
        {
        "Ip": Ip,
        "PulseAvgCurrent": NabizOrtalama,
        "T0_zero": T0_hizali,
        "Charge": Yuk,
        "trigger_time": tetik,
        "Td_duration": T0_hizali,
       }

def SonuclariBicimlendirC(metrik: dict, dosya_adi: str):
    # Formats variant C metrics into display-ready result rows.
    pol = "POZİTİF POLARİTE " if metrik["Ip"] > 0 else "NEGATİF POLARİTE "
    baslik = f'{pol}"{dosya_adi}" Analiz edildi'
    ogeler = [
        ("Max Current (Ip)", f"{metrik['Ip']:.5f} A"),
        ("Avg Current", f"{metrik['PulseAvgCurrent']:.5f} A"),
        ("Time to Zero (T0)", f"{metrik['T0_zero']*1e3:.5f} ms"),
        ("Charge (Q)", f"{metrik['Charge']*1e3:.5f} C"),
    ]
    genislik = max(len(k) for k, _ in ogeler)
    return [baslik] + [f"{k:<{genislik}} = {v}" for k, v in ogeler]

MetrikleriHesaplaD = MetrikleriHesaplaA
def SonuclariBicimlendirD(metrik: dict, dosya_adi: str):
    # Formats variant D metrics into display-ready result rows.
    return SonuclariBicimlendirA(metrik, dosya_adi)

Varyantlar = \
    {
    "A": {"title": "A", "compute": MetrikleriHesaplaA, "format": SonuclariBicimlendirA},
    "B": {"title": "B", "compute": MetrikleriHesaplaB, "format": SonuclariBicimlendirB},
    "C": {"title": "C", "compute": MetrikleriHesaplaC, "format": SonuclariBicimlendirC},
    "D": {"title": "D", "compute": MetrikleriHesaplaD, "format": SonuclariBicimlendirD},
   }

# görsel ve pdf
def AnaGrafikSekliOlustur(zaman_hizali, akim_yumusat, taban, metrikler):
    # Builds the main current plot and its interactive guide markers.
    fig, ax = plt.subplots(figsize=(8, 5.1), dpi=140)
    fig.patch.set_facecolor(Renkler2["bg_secondary"])
    ax.set_facecolor(Renkler2["bg_secondary"])

    akim_ka = akim_yumusat / 1000.0
    taban_ka = taban / 1000.0
    ciz_ka = akim_ka.copy()
    ciz_ka[zaman_hizali < 0] = taban_ka

    ax.plot(zaman_hizali, ciz_ka, linewidth=3.0, color=Renkler2["primary"], alpha=0.9, label="Akım (kA)")
    ax.axhline(taban_ka, linestyle=":", label="Baseline", color="gray")

    dikeyler = []
    dikeyler.append(ax.axvline(0, linestyle="--", color="gold", alpha=0.9, linewidth=2, label="Trigger (Start)"))

    if "Tp" in metrikler:
        tepe_x = metrikler["Tp"]
    else:
        tepe_ind = np.argmax(np.abs((akim_yumusat - taban)))
        tepe_x = zaman_hizali[tepe_ind]
    dikeyler.append(ax.axvline(tepe_x, linestyle="--", color="red", alpha=0.6, label="Peak"))

    if "T2_halffall" in metrikler:
        dikeyler.append(ax.axvline(metrikler["T2_halffall"], linestyle="--", color="purple", alpha=0.6, label="T2 (half)"))

    dikeyler.append(ax.axvline(metrikler["T0_zero"], linestyle="--", color="black", alpha=0.6, label=f"T0 ~{metrikler['T0_zero']:.3f} ms"))

    td = metrikler.get("Td_duration", metrikler.get("T0_zero", 0.0))
    pay = td * 0.05 if td > 0 else 0.1
    ax.set_xlim(-pay, td + pay)

    ax.set_xlabel("Time (ms)", fontsize=12, fontweight="bold", color=Renkler2["text_primary"], labelpad=10)
    ax.set_ylabel("Current (kA)", fontsize=12, fontweight="bold", color=Renkler2["text_primary"], labelpad=15)
    ax.set_title("Akım - Zaman Grafiği", fontsize=16, fontweight="bold", color=Renkler2["secondary"], pad=15)
    ax.grid(True, alpha=0.3, color=Renkler2["text_secondary"], linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(Renkler2["border"])
        spine.set_linewidth(1.2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=Renkler2["text_primary"], labelsize=10)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout(pad=0.1)

    # göster/gizle butonu
    btn_ax = fig.add_axes([0.005, 0.93, 0.11, 0.06])
    btn_ax.set_zorder(10)
    btn_ax.set_navigate(False)

    btn = Button(btn_ax, "Hide", color="#e0e7ef", hovercolor="#d1d5db")
    btn.label.set_fontsize(12)
    btn.label.set_fontweight("bold")
    btn.label.set_color("#0a2533")

    durum = {"gizli": False}

    def Tetikle(_evt=None):
        # Toggles the visibility of the reference lines on the chart.
        durum["gizli"] = not durum["gizli"]
        for ln in dikeyler:
            ln.set_visible(not durum["gizli"])
        btn.label.set_text("Show" if durum["gizli"] else "Hide")
        fig.canvas.draw()

    btn.on_clicked(Tetikle)
    fig._hide_show_button = btn
    fig._hide_show_state = durum
    fig._hide_show_lines = dikeyler

    return fig

def PdfRaporUret(pdf_yolu: str, sonuc_satirlari: list, fig):
    # Creates the PDF report with the formatted results and rendered chart.
    if not ReportLabVar:
        raise RuntimeError("reportlab kurulu değil")

    w, h = A4
    kenar = 65
    doc = SimpleDocTemplate(
        pdf_yolu, pagesize=A4,
        leftMargin=kenar, rightMargin=kenar,
        topMargin=65, bottomMargin=20
    )

    # font tercihi
    try:
        pdfmetrics.registerFont(TTFont("Turkish", "arial.ttf"))
        font_adi = "Turkish"
    except Exception:
        try:
            pdfmetrics.registerFont(TTFont("Turkish", "DejaVuSans.ttf"))
            font_adi = "Turkish"
        except Exception:
            font_adi = "Helvetica"

    icerik = []
    tarih_saat = datetime.now().strftime("%d.%m.%Y %H:%M")
    stil_tarih = ParagraphStyle("tarih", alignment=2, fontName=font_adi, fontSize=10, textColor="#888888")
    icerik.append(Paragraph(tarih_saat, stil_tarih))
    icerik.append(Spacer(1, 12))

    stil_hdr = ParagraphStyle("Header", fontName=font_adi, fontSize=21, alignment=TA_CENTER, textColor="#1e3a8a", spaceAfter=8)
    stil_rpt = ParagraphStyle("Report", fontName=font_adi, fontSize=13, alignment=TA_CENTER, textColor="#111827", spaceAfter=8)
    stil_anl = ParagraphStyle("Analiz", fontName=font_adi, fontSize=16, alignment=TA_CENTER, textColor="#f59e0b", spaceAfter=10)

    icerik.append(Paragraph(UygulamaAyarlari["organization_name"], stil_hdr))
    icerik.append(Spacer(1, 3))
    icerik.append(Paragraph(UygulamaAyarlari["current_report_title"], stil_rpt))
    icerik.append(Spacer(1, 6))
    icerik.append(Paragraph("Analiz Sonuçları", stil_anl))
    icerik.append(Spacer(1, 12))

    veri = [[sonuc_satirlari[0], "", ""]]
    for s in sonuc_satirlari[1:]:
        if " = " in s:
            k, v = s.split(" = ", 1)
            veri.append([k, "=", v])
        else:
            veri.append([s, "", ""])

    tablo_gen = w - 2 * kenar
    sutun_gen = [tablo_gen * 0.36, tablo_gen * 0.08, tablo_gen * 0.56]
    tbl = Table(veri, colWidths=sutun_gen, hAlign="CENTER")
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), font_adi),
        ("FONTSIZE", (0,0), (-1,0), 13),
        ("TEXTCOLOR", (0,0), (-1,0), "#1e3a8a"),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("FONTNAME", (0,1), (-1,-1), font_adi),
        ("FONTSIZE", (0,1), (-1,-1), 12),
        ("TEXTCOLOR", (0,1), (-1,-1), "#111827"),
        ("ALIGN", (1,1), (1,-1), "CENTER"),
        ("ALIGN", (0,0), (0,-1), "LEFT"),
        ("ALIGN", (2,1), (2,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("BACKGROUND", (0,1), (-1,-1), colors.whitesmoke),
        ("GRID", (0,0), (-1,-1), 0.18, colors.lightgrey),
    ]))
    icerik.append(tbl)
    icerik.append(Spacer(1, 5))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=Renkler2["bg_secondary"], bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)

    img = Image(buf)
    img.drawWidth = tablo_gen
    img.drawHeight = tablo_gen * 0.56
    img.hAlign = "CENTER"
    icerik.append(img)

    doc.build(icerik)

# uygulama akışı
def AnalizYap(dosya):
    # Runs the selected current analysis workflow for the provided file path.
    global SeciliDosyaYolu, SonSonucSatirlari, GenelVeri, SonMetrikler
    if not dosya or not os.path.exists(dosya):
        messagebox.showerror("Hata!", "geçerli dosya seçilmedi")
        return
    try:
        if UstCizgi and DosyaEtiketi:
            UstCizgi.config(bg=Renkler2["warning"])
            DosyaEtiketi.config(text=f"{os.path.basename(dosya)} analiz ediliyor...", bg=Renkler2["warning"], fg="white")
            Kok.update_idletasks()
        SeciliDosyaYolu = dosya
        df, _, _ = ZamanAkimOku(dosya)
        if df is None or df.empty:
            messagebox.showerror("Hata!", "geçerli ölçüm verisi bulunamadı")
            return
        GenelVeri = df.copy()
        if df.shape[0] < 10:
            messagebox.showerror("Hata!", "yetersiz veri noktası (minimum 10)")
            return

        zaman_ham = df["time"].to_numpy()
        akim_ham = df["current"].to_numpy() * OlcekFaktoru

        zaman_ms, _ = ZamanBiriminiTahminEtVeMs(zaman_ham)
        kesme = int(max(1, len(zaman_ms) * 0.05))
        taban = np.mean(akim_ham[:kesme])
        akim_yumusat = AgresifYumusat(akim_ham - taban, pencere=15) + taban

        mod = ModDegeri.get()
        hesap_fn = Varyantlar[mod]["compute"]
        SonMetrikler = hesap_fn(zaman_ms, akim_yumusat, taban)
        if not SonMetrikler:
            messagebox.showerror("Hata!", "hesaplama sonuçları eksik")
            return

        SonSonucSatirlari = Varyantlar[mod]["format"](SonMetrikler, os.path.basename(dosya))

        SonucPaneliniGuncelle()
        GrafikGuncelle()
        messagebox.showinfo("Başarılı", f"'{os.path.basename(dosya)}' dosyası ({mod}) analiz edildi")

    except Exception as e:
        messagebox.showerror("Hata!", f"analiz sırasında hata oluştu:\n{e}")

def GrafikGuncelle():
    # Rebuilds the chart area with the latest processed current data.
    global GrafikKanvasi, GrafikAracCubugu, GorunumGecmisi

    if GrafikKanvasi:
        try:
            eski = GrafikKanvasi.figure
            if hasattr(eski, "canvas") and eski.canvas:
                eski.canvas.mpl_disconnect_all()
        except Exception:
            pass
        GrafikKanvasi.get_tk_widget().destroy()
        GrafikKanvasi = None

    if GrafikAracCubugu:
        try:
            GrafikAracCubugu.destroy()
        except Exception:
            pass

    if GenelVeri is None or GenelVeri.empty or SonMetrikler is None:
        return

    zaman_ham = GenelVeri["time"].to_numpy()
    akim_ham = GenelVeri["current"].to_numpy() * OlcekFaktoru
    zaman_ms, _ = ZamanBiriminiTahminEtVeMs(zaman_ham)
    kesme = int(max(1, len(zaman_ms) * 0.05))
    taban = np.mean(akim_ham[:kesme])
    akim_yumusat = AgresifYumusat(akim_ham - taban, pencere=15) + taban

    zaman_hizali = zaman_ms - SonMetrikler["trigger_time"]

    fig = AnaGrafikSekliOlustur(zaman_hizali, akim_yumusat, taban, SonMetrikler)

    GrafikKanvasi = FigureCanvasTkAgg(fig, master=SagCerceve)
    GrafikKanvasi.draw()
    kanvas_widget = GrafikKanvasi.get_tk_widget()
    kanvas_widget.pack(fill="both", expand=True, padx=5, pady=5)

    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
    class OzellestirilmisAracCubugu(NavigationToolbar2Tk):
        def __init__(self, canvas, window):
            # Initializes the custom toolbar without packing it into the layout.
            super().__init__(canvas, window)
            self.pack_forget()
    GrafikAracCubugu = OzellestirilmisAracCubugu(GrafikKanvasi, SagCerceve)

    GorunumGecmisi.clear()
    ax = fig.axes[0]
    GorunumGecmisi.append((ax.get_xlim(), ax.get_ylim()))

    def GeriAl():
        # Restores the previous zoom or pan view from the history stack.
        if len(GorunumGecmisi) > 1:
            GorunumGecmisi.pop()
            xlim, ylim = GorunumGecmisi[-1]
            ax.set_xlim(xlim); ax.set_ylim(ylim)
            GrafikKanvasi.draw()

    geri_btn = tk.Button(master=kanvas_widget, text="↶", font=("Segoe UI", 15, "bold"),
                         bg=Renkler2["secondary"], fg="white", bd=0, relief="flat",
                         command=GeriAl, cursor="hand2")
    geri_btn.place(in_=kanvas_widget, relx=0.02, rely=0.98, anchor="sw")

    pan_bas = {"x": None, "y": None}

    def FareTeker(event):
        # Zooms the chart around the current mouse position.
        if event.inaxes != ax or not GrafikKanvasi:
            return
        GorunumGecmisi.append((ax.get_xlim(), ax.get_ylim()))
        faktor = 1.15 if event.button == "down" else 1/1.15
        x0, x1 = ax.get_xlim(); xc = event.xdata
        if xc is None: return
        dx = (x1 - x0) * faktor
        yeni_x0 = xc - dx * (xc - x0) / (x1 - x0)
        yeni_x1 = xc + dx * (x1 - xc) / (x1 - x0)
        ax.set_xlim(yeni_x0, yeni_x1)
        GrafikKanvasi.draw()

    def FareBas(event):
        # Captures the initial mouse position for chart panning.
        if event.button == 1 and event.inaxes == ax and event.xdata is not None:
            pan_bas["x"], pan_bas["y"] = event.xdata, event.ydata
            GorunumGecmisi.append((ax.get_xlim(), ax.get_ylim()))

    def FareHareket(event):
        # Pans the chart while the left mouse button is held down.
        if pan_bas["x"] is None or event.inaxes != ax or not GrafikKanvasi:
            return
        if event.xdata is None or event.ydata is None:
            return
        dx = event.xdata - pan_bas["x"]
        dy = event.ydata - pan_bas["y"]
        x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
        ax.set_xlim(x0 - dx, x1 - dx)
        ax.set_ylim(y0 - dy, y1 - dy)
        GrafikKanvasi.draw_idle()

    def FareBirak(event):
        # Clears the panning state after the mouse button is released.
        pan_bas["x"] = pan_bas["y"] = None

    if GrafikKanvasi and GrafikKanvasi.get_tk_widget().winfo_exists():
        GrafikKanvasi.mpl_connect("scroll_event", FareTeker)
        GrafikKanvasi.mpl_connect("button_press_event", FareBas)
        GrafikKanvasi.mpl_connect("motion_notify_event", FareHareket)
        GrafikKanvasi.mpl_connect("button_release_event", FareBirak)

def DosyayiVarsayilanUygulamaIleAc(yol: str):
    # Opens the given file with the default operating system application.
    if not yol or not os.path.exists(yol):
        raise FileNotFoundError("dosya bulunamadi")
    if os.name == "nt":
        os.startfile(yol)
    elif sys.platform == "darwin":
        subprocess.call(["open", yol])
    else:
        subprocess.call(["xdg-open", yol])

def PdfAc():
    # Opens the last generated PDF report when it is available.
    global SonPdfYolu
    if SonPdfYolu and os.path.exists(SonPdfYolu):
        try:
            DosyayiVarsayilanUygulamaIleAc(SonPdfYolu)
        except Exception as e:
            messagebox.showerror("Hata!", f"pdf açılamadı:\n{e}")
    else:
        messagebox.showwarning("Uyarı", "henüz pdf oluşturulmadı veya dosya yok")

def PdfOlustur():
    # Builds and saves a PDF report for the current analysis result.
    global SonSonucSatirlari, GenelVeri, SeciliDosyaYolu, OlcekFaktoru, SonPdfYolu
    if not ReportLabVar:
        messagebox.showerror("Hata!", "reportlab kurulu değil (pip install reportlab)")
        return
    if not SonSonucSatirlari or GenelVeri is None or SonMetrikler is None:
        messagebox.showwarning("Uyarı", "önce bir dosya analiz edin")
        return

    ad = BasitGirdiPenceresi(Kok, "PDF Adı Belirle", "PDF dosya adını girin:")
    if not ad: return
    dizin = filedialog.askdirectory(title="PDF Kaydedilecek Klasörü Seç")
    if not dizin: return
    pdf_yolu = os.path.join(dizin, ad + ".pdf")

    zaman_ham = GenelVeri["time"].to_numpy()
    akim_ham = GenelVeri["current"].to_numpy() * OlcekFaktoru
    zaman_ms, _ = ZamanBiriminiTahminEtVeMs(zaman_ham)
    kesme = int(max(1, len(zaman_ms) * 0.05))
    taban = np.mean(akim_ham[:kesme])
    akim_yumusat = AgresifYumusat(akim_ham - taban, pencere=15) + taban
    hizali = zaman_ms - SonMetrikler["trigger_time"]
    fig = AnaGrafikSekliOlustur(hizali, akim_yumusat, taban, SonMetrikler)

    try:
        PdfRaporUret(pdf_yolu, SonSonucSatirlari, fig)
        SonPdfYolu = pdf_yolu
        AcButonu.config(state="normal")
        messagebox.showinfo("Başarılı", f"pdf kaydedildi:\n{pdf_yolu}")
        if UygulamaAyarlari.get("pdf_auto_open", True):
            try:
                DosyayiVarsayilanUygulamaIleAc(pdf_yolu)
            except Exception as e:
                messagebox.showwarning("Uyarı", f"pdf kaydedildi fakat otomatik açılamadı:\n{e}")
    except Exception as e:
        messagebox.showerror("Hata!", f"pdf oluşturulurken hata:\n{e}")

# küçük arayüz yardımcıları
def MerkezliPencereAc(ebeveyn, w, h, baslik, bg="#f8fafc"):
    # Creates a modal child window centered on the parent application window.
    dlg = tk.Toplevel(ebeveyn)
    dlg.withdraw()
    dlg.title(baslik)
    dlg.resizable(False, False)
    dlg.configure(bg=bg)
    dlg.transient(ebeveyn)
    dlg.grab_set()

    ebeveyn.update_idletasks()
    x = ebeveyn.winfo_rootx() + ebeveyn.winfo_width() // 2 - w // 2
    y = ebeveyn.winfo_rooty() + ebeveyn.winfo_height() // 2 - h // 2
    dlg.geometry(f"{w}x{h}+{x}+{y}")

    dlg.deiconify()
    return dlg

def BasitGirdiPenceresi(ebeveyn, baslik, mesaj):
    # Shows a small modal dialog that collects a single text value.
    dialog = MerkezliPencereAc(ebeveyn, 350, 160, baslik)
    tk.Label(dialog, text=mesaj, font=("Segoe UI", 12, "bold"),
             bg="#f8fafc", fg="#1e3a8a").pack(pady=(22, 5))

    giris = tk.Entry(dialog, font=("Segoe UI", 13), justify="center",
                     width=26, bd=2, relief="groove")
    giris.pack(pady=(5, 10)); giris.focus_set()

    sonuc = {"val": None}

    def Tamam():
        # Confirms the current dialog value and closes the window.
        v = giris.get().strip()
        if v:
            sonuc["val"] = v
            dialog.destroy()

    def Iptal():
        # Closes the current dialog without applying a new value.
        dialog.destroy()

    btn_kutu = tk.Frame(dialog, bg="#f8fafc"); btn_kutu.pack(pady=5)
    tk.Button(btn_kutu, text="OK", font=("Segoe UI", 11, "bold"),
              bg="#1e3a8a", fg="white", width=9, command=Tamam).pack(side="left", padx=7)
    tk.Button(btn_kutu, text="Cancel", font=("Segoe UI", 11, "bold"),
              bg="#e5e7eb", fg="#374151", width=9, command=Iptal).pack(side="left", padx=7)

    giris.bind("<Return>", lambda e: Tamam())
    dialog.wait_window()
    return sonuc["val"]

def ModernOlcekPenceresi(ebeveyn, mevcut_olcek):
    # Shows the scale factor editor dialog and validates numeric input.
    dialog = MerkezliPencereAc(ebeveyn, 370, 160, "Ölçek Değiştir")
    tk.Label(dialog, text=f"Yeni ölçek faktörünü girin (şu an: {mevcut_olcek}):",
             font=("Segoe UI", 11, "bold"), bg="#f8fafc", fg="#1e3a8a").pack(pady=(18, 7))

    giris = tk.Entry(dialog, font=("Segoe UI", 13), justify="center", width=20, bd=2, relief="groove")
    giris.pack(pady=(0, 10)); giris.insert(0, str(mevcut_olcek)); giris.focus_set()

    sonuc = {"olcek": None}

    def Tamam():
        # Confirms the current dialog value and closes the window.
        try:
            val = float(giris.get())
            if val > 0:
                sonuc["olcek"] = val
                dialog.destroy()
        except Exception:
            giris.config(bg="#fee2e2")

    def Iptal():
        # Closes the current dialog without applying a new value.
        dialog.destroy()

    btn_kutu = tk.Frame(dialog, bg="#f8fafc"); btn_kutu.pack(pady=5)
    tk.Button(btn_kutu, text="OK", font=("Segoe UI", 11, "bold"),
              bg="#1e3a8a", fg="white", width=9, command=Tamam).pack(side="left", padx=6)
    tk.Button(btn_kutu, text="Cancel", font=("Segoe UI", 11, "bold"),
              bg="#e5e7eb", fg="#374151", width=9, command=Iptal).pack(side="left", padx=6)

    giris.bind("<Return>", lambda e: Tamam())
    dialog.wait_window()
    return sonuc["olcek"]

def YoneticiGirisPaneli(ebeveyn, basarili_cb):
    # Prompts for scale access only when local admin protection is enabled.
    giris_bilgileri = UygulamaAyarlari.get("scale_auth", {})
    kullanici_adi = str(giris_bilgileri.get("username", "") or "")
    hash_degeri = giris_bilgileri.get("password_hash", "")
    koruma_acik = bool(giris_bilgileri.get("enabled")) and bool(kullanici_adi) and bool(hash_degeri)

    if not koruma_acik:
        basarili_cb()
        return

    giris = MerkezliPencereAc(ebeveyn, 400, 325, "Yönetici Girişi")

    ana = tk.Frame(giris, bg="#f8fafc", bd=0)
    ana.pack(expand=True, fill="both", padx=22, pady=18)

    tk.Label(ana, text="YÖNETİCİ GİRİŞİ", font=("Segoe UI", 17, "bold"),
             fg="#1e3a8a", bg="#f8fafc").pack(pady=(5, 17))

    tk.Label(ana, text="Kullanıcı Adı:", font=("Segoe UI", 11, "bold"),
             bg="#f8fafc").pack(anchor="w", padx=4)
    e_user = tk.Entry(ana, font=("Segoe UI", 12), bd=2, relief="groove")
    e_user.pack(fill="x", padx=2, pady=(2, 13))
    e_user.insert(0, kullanici_adi)

    tk.Label(ana, text="Şifre:", font=("Segoe UI", 11, "bold"),
             bg="#f8fafc").pack(anchor="w", padx=4)
    f = tk.Frame(ana, bg="#f8fafc"); f.pack(fill="x", pady=(2, 0))
    e_pw = tk.Entry(f, font=("Segoe UI", 12), show="*", bd=2, relief="groove")
    e_pw.pack(side="left", fill="x", expand=True)
    goster_var = tk.BooleanVar(value=False)

    def SifreGoster():
        # Toggles password visibility in the admin login dialog.
        e_pw.config(show="" if goster_var.get() else "*")

    tk.Checkbutton(f, text="Şifreyi göster", variable=goster_var, command=SifreGoster,
                   bg="#f8fafc", fg="#6b7280", font=("Segoe UI", 9),
                   activebackground="#f8fafc").pack(side="left", padx=(12,0))

    hata = tk.Label(ana, text="", fg="#ef4444", bg="#f8fafc",
                    font=("Segoe UI", 10, "bold"))
    hata.pack(pady=(7,4))

    def Dogrula():
        # Validates the provided admin credentials against the local config.
        sakli_hash = hash_degeri.encode() if isinstance(hash_degeri, str) else hash_degeri
        if e_user.get().strip() == kullanici_adi and bcrypt.checkpw(e_pw.get().encode(), sakli_hash):
            giris.destroy()
            basarili_cb()
        else:
            hata.config(text="kullanıcı adı veya şifre hatalı")

    def Iptal():
        # Closes the current dialog without applying a new value.
        giris.destroy()

    b = tk.Frame(ana, bg="#f8fafc"); b.pack(fill="x", pady=(10, 0))
    tk.Button(b, text="GİRİŞ YAP", command=Dogrula, font=("Segoe UI", 12, "bold"),
              bg="#10b981", fg="white", bd=0, width=11).pack(side="left", expand=True, padx=(0,6))
    tk.Button(b, text="İPTAL", command=Iptal, font=("Segoe UI", 12, "bold"),
              bg="#e5e7eb", fg="#374151", bd=0, width=11).pack(side="left", expand=True, padx=(6,0))

    e_user.bind('<Return>', lambda e: Dogrula())
    e_pw.bind('<Return>', lambda e: Dogrula())
    e_user.focus_set()

# buton işlemleri
def OlcegiDegistir():
    # Starts the protected scale-change workflow for the current session.
    def Sonra():
        # Applies the new scale factor after successful authorization.
        global OlcekFaktoru
        yeni = ModernOlcekPenceresi(Kok, OlcekFaktoru)
        if yeni is not None:
            OlcekFaktoru = yeni
            Ayarlar["scale_factor"] = OlcekFaktoru
            AyarlariKaydet(Ayarlar)
            if SeciliDosyaYolu:
                UygulamayiSifirla(clear_file=False)
                AnalizYap(SeciliDosyaYolu)
    YoneticiGirisPaneli(Kok, Sonra)

def DosyaSec():
    # Opens a file picker and starts the analysis for the selected CSV file.
    f = filedialog.askopenfilename(title="CSV Dosyası Seç",
                                   filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
                                   initialdir=os.path.expanduser("~"))
    if f:
        UygulamayiSifirla(clear_file=True)
        AnalizYap(f)

def SurukleBirak(event):
    # Processes files dropped onto the application window.
    try:
        yol_ham = event.data.strip()
        if yol_ham.startswith("{") and yol_ham.endswith("}"):
            yol_ham = yol_ham[1:-1]
        yol = yol_ham.strip().replace('"', "")
        if not os.path.isfile(yol):
            raise FileNotFoundError(f"dosya bulunamadı: {yol}")
        UygulamayiSifirla(clear_file=True)
        AnalizYap(yol)
    except Exception as e:
        messagebox.showerror("Sürükle-Bırak Hatası", f"dosya okunamadı:\n{e}")

def ModDegisti(mod=None):
    # Switches the active analysis mode and resets the visible state.
    if mod is not None:
        ModDegeri.set(mod)

    Ayarlar["mode"] = ModDegeri.get()
    AyarlariKaydet(Ayarlar)

    # burası düzeltildi: sadece sözlüğe bakıp title alıyoruz
    Kok.title(f"{UygulamaAyarlari['current_window_title']} - {Varyantlar[ModDegeri.get()]['title']}")

    UygulamayiSifirla(clear_file=True)
    ModButonlariniGuncelle()
    SonucPaneliniGuncelle()

def ModSeciciOlustur(ebeveyn):
    # Creates the mode selector buttons shown in the header area.
    kap = tk.Frame(ebeveyn, bg=Renkler2["bg_secondary"])
    kap.place(relx=0.02, rely=0.5, anchor="w")

    tk.Label(kap, text="MOD:", bg=Renkler2["bg_secondary"],
             fg=Renkler2["text_primary"], font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 8))

    sar = tk.Frame(kap, bg="#e5e7eb", bd=1, relief="solid")
    sar.pack(side="left")

    def Sec(mod: str):
        # Handles clicks on a mode selector button.
        if ModDegeri.get() == mod:
            return
        ModDegisti(mod)

    def ButonOlustur(etiket):
        # Creates a styled mode button bound to the requested mode key.
        return tk.Button(
            sar, text=etiket, bd=0, relief="flat",
            font=("Segoe UI", 11, "bold"),
            cursor="hand2", padx=14, pady=6,
            command=lambda m=etiket: Sec(m)
        )

    for m in ["A", "B", "C", "D"]:
        b = ButonOlustur(m)
        b.pack(side="left", padx=2, pady=2)
        ModButonlari[m] = b

    ModButonlariniGuncelle()
    return kap

def UygulamayiSifirla(clear_file=True):
    # Clears the current analysis outputs and resets the UI panels.
    global SonSonucSatirlari, SonMetrikler, GorunumGecmisi, SonPdfYolu
    global GrafikKanvasi, GrafikAracCubugu, GenelVeri, SeciliDosyaYolu

    SonSonucSatirlari = []
    SonMetrikler = None
    GorunumGecmisi.clear()
    SonPdfYolu = None

    if clear_file:
        GenelVeri = None
        SeciliDosyaYolu = ""

    try:
        if GrafikKanvasi:
            if hasattr(GrafikKanvasi.figure, "canvas") and GrafikKanvasi.figure.canvas:
                GrafikKanvasi.figure.canvas.mpl_disconnect_all()
            GrafikKanvasi.get_tk_widget().destroy()
    except Exception:
        pass
    GrafikKanvasi = None

    try:
        if GrafikAracCubugu:
            GrafikAracCubugu.destroy()
    except Exception:
        pass
    GrafikAracCubugu = None

    UstCizgi.config(bg=Renkler2["accent"])
    DosyaEtiketi.config(text="Analiz Sonucu Bekleniyor…", bg=Renkler2["accent"], fg="white")

    for w in SolCerceve.winfo_children():
        w.destroy()
    for w in SagCerceve.winfo_children():
        w.destroy()

    if AcButonu:
        AcButonu.config(state="disabled")

def ModButonlariniGuncelle():
    # Refreshes the visual state of the mode selector buttons.
    secili = ModDegeri.get()
    for m, b in ModButonlari.items():
        if m == secili:
            b.configure(bg=Renkler2["secondary"], fg="white",
                        activebackground=Renkler2["secondary"], activeforeground="white")
        else:
            b.configure(bg="#ffffff", fg="#374151",
                        activebackground="#f3f4f6", activeforeground="#111827")

def SonucPaneliniGuncelle():
    # Rebuilds the left-side results panel from the latest analysis rows.
    for w in SolCerceve.winfo_children():
        w.destroy()

    if not SonSonucSatirlari:
        UstCizgi.config(bg=Renkler2["accent"])
        DosyaEtiketi.config(text="Analiz Sonucu Bekleniyor…", bg=Renkler2["accent"], fg="white")

        bos = tk.Frame(SolCerceve, bg=Renkler2["bg_secondary"], relief="solid", bd=1)
        bos.pack(fill="x", padx=10, pady=20)
        tk.Label(bos, text="Dosya Bekleniyor", font=("Segoe UI", 14, "bold"),
                 bg=Renkler2["bg_secondary"], fg=Renkler2["text_secondary"]).pack(pady=30)
        tk.Label(bos, text="analiz için bir csv dosyası seçin\nveya sürükleyip bırakın",
                 font=("Segoe UI", 11), bg=Renkler2["bg_secondary"],
                 fg=Renkler2["text_secondary"], justify="center").pack(pady=(0,30))
        return

    baslik = SonSonucSatirlari[0]
    pozitif = "POZİTİF" in baslik
    bar_renk = Renkler2["accent"] if pozitif else Renkler2["danger"]

    UstCizgi.config(bg=bar_renk)
    DosyaEtiketi.config(text=baslik, bg=bar_renk, fg="white")

    ana = tk.Frame(SolCerceve, bg=Renkler2["bg_main"])
    ana.pack(fill="both", expand=True, padx=5, pady=5)

    kart = tk.Frame(ana, bg=bar_renk, relief="flat")
    kart.pack(fill="x", pady=(0, 8))
    tk.Label(kart, text="HESAPLANAN DEĞERLER", font=("Segoe UI", 21, "bold"),
             bg=bar_renk, fg="white").pack(pady=15)

    for s in SonSonucSatirlari[1:]:
        renk_key = "black"
        s_bas = s.split(" = ")[0] if " = " in s else s
        for lbl, renk in HesaplananDegerlerSirasi:
            if s_bas.strip() == lbl:
                renk_key = renk
                break
        if " = " in s:
            bas, deger = s.split(" = ", 1)
        else:
            bas, deger = s, ""

        kart_cerceve = tk.Frame(ana, bg=Renkler2["bg_secondary"], relief="solid", bd=1)
        kart_cerceve.pack(fill="x", padx=5, pady=6, expand=False, ipady=4)
        renk_cubuk = tk.Frame(kart_cerceve, bg=Renkler1.get(renk_key, "#999"), width=4)
        renk_cubuk.pack(side="left", fill="y")
        icerik = tk.Frame(kart_cerceve, bg=Renkler2["bg_secondary"])
        icerik.pack(side="left", fill="both", expand=True, padx=15)
        tk.Label(icerik, text=bas, font=("Segoe UI", 18, "bold"),
                 bg=Renkler2["bg_secondary"], fg=Renkler2["text_primary"],
                 anchor="w", width=20, justify="left").grid(row=0, column=0, sticky="w", padx=(0,2))
        tk.Label(icerik, text="=", font=("Segoe UI", 16, "bold"),
                 bg=Renkler2["bg_secondary"], fg="#888888",
                 anchor="center", width=2).grid(row=0, column=1, sticky="we", padx=(2,2))
        tk.Label(icerik, text=deger, font=("Segoe UI", 16, "bold"),
                 bg=Renkler2["bg_secondary"], fg=Renkler1.get(renk_key, "#666"),
                 anchor="w").grid(row=0, column=2, sticky="w", padx=(2,0))
        icerik.grid_columnconfigure(0, weight=0, minsize=180)
        icerik.grid_columnconfigure(1, weight=0, minsize=18)
        icerik.grid_columnconfigure(2, weight=1)

# ana arayüz
if __name__ == "__main__":
    DurumDegiskenleriniSifirla()
    try:
        Kok = TkinterDnD.Tk() if SurukleBirakVar else tk.Tk()
    except Exception as e:
        print("program başlatma hatası:", e)
        sys.exit(1)

    if SonMod not in Varyantlar:
        SonMod = "A"
    ModDegeri = tk.StringVar(value=SonMod)

    baslik = f"{UygulamaAyarlari['current_window_title']} - {Varyantlar[ModDegeri.get()]['title']}"
    Kok.title(baslik)
    Kok.geometry("1600x900"); Kok.configure(bg=Renkler2["bg_main"]); Kok.minsize(900, 520)

    ust_panel = tk.Frame(Kok, bg=Renkler2["bg_secondary"], relief="flat", bd=2)
    ust_panel.pack(side=tk.TOP, fill="x", padx=10, pady=(10, 5))
    UstCizgi = tk.Frame(ust_panel, height=80, bg=Renkler2["accent"]); UstCizgi.pack(fill="x")

    ModSeciciOlustur(UstCizgi)

    DosyaEtiketi = tk.Label(UstCizgi, text="Analiz Sonucu Bekleniyor…",
                            font=("Segoe UI", 18, "bold"), bg=Renkler2["accent"],
                            fg="white", anchor="center")
    DosyaEtiketi.pack(expand=True, pady=20)

    buton_panel = tk.Frame(Kok, bg=Renkler2["bg_main"], height=80)
    buton_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)
    buton_panel.pack_propagate(False)
    buton_panel.grid_columnconfigure(0, weight=1)
    buton_panel.grid_columnconfigure(1, weight=1)
    buton_panel.grid_columnconfigure(2, weight=1)

    def ButonYap(yazi, komut, bg, hover=None):
        # Creates a styled action button for the main control bar.
        if hover is None: hover = bg
        f = tk.Frame(buton_panel, bg=Renkler2["bg_main"])
        b = tk.Button(f, text=yazi, command=komut, font=("Segoe UI", 12, "bold"),
                      bg=bg, fg="white", bd=0, relief="flat",
                      padx=20, pady=10, cursor="hand2",
                      activebackground=hover, activeforeground="white")
        b.pack(fill="both", expand=True)
        return f

    ButonYap("CSV DOSYASI SEÇ", DosyaSec, "#69A4C5", "#4479a2").grid(row=0, column=0, sticky="ew", padx=(0,5), pady=10)
    ButonYap("SKALA AYARLA", OlcegiDegistir, Renkler2["warning"], "#d97706").grid(row=0, column=1, sticky="ew", padx=5, pady=10)
    ButonYap("PDF OLUŞTUR", PdfOlustur, Renkler2["accent"], "#059669").grid(row=0, column=2, sticky="ew", padx=(5,0), pady=10)

    ac_kutu = tk.Frame(buton_panel, bg=Renkler2["bg_main"])
    AcButonu = tk.Button(
        ac_kutu,
        text="PDF AÇ",
        command=PdfAc,
        font=("Segoe UI", 12, "bold"),
        bg="#1e3a8a",
        fg="white",
        activebackground="#2563eb",
        activeforeground="white",
        disabledforeground="#e5e7eb",
        bd=0,
        relief="flat",
        padx=20,
        pady=10,
        cursor="hand2",
        state="disabled"
    )
    AcButonu.pack(fill="both", expand=True)
    ac_kutu.grid(row=0, column=3, sticky="ew", padx=(5, 0), pady=10)

    calisma_alani = tk.Frame(Kok, bg=Renkler2["bg_main"])
    calisma_alani.pack(fill="both", expand=True, padx=10, pady=5)
    calisma_alani.grid_columnconfigure(0, weight=0, minsize=500)
    calisma_alani.grid_columnconfigure(1, weight=1)
    calisma_alani.grid_rowconfigure(0, weight=1)

    SolCerceve = tk.Frame(calisma_alani, bg=Renkler2["bg_main"], width=500)
    SolCerceve.grid(row=0, column=0, sticky="nsew", padx=(0,10))
    SolCerceve.grid_propagate(False)

    SagCerceve = tk.Frame(calisma_alani, bg=Renkler2["bg_secondary"], relief="solid", bd=1)
    SagCerceve.grid(row=0, column=1, sticky="nsew")

    if SurukleBirakVar:
        try:
            Kok.tk.call("package", "require", "tkdnd")
            Kok.drop_target_register(DND_FILES)
            Kok.dnd_bind("<<Drop>>", SurukleBirak)
        except tk.TclError as e:
            print("tkdnd etkin değil:", e)

    SonucPaneliniGuncelle()
    Kok.mainloop()
