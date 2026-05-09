import serial, socket, threading, base64, time, struct, csv
import numpy as np
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer
from collections import deque # Do płynnej analizy live

# --- KONFIGURACJA ---
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
GTX_FILE = 'geoida_PL.gtx'
AVERAGING_EPOCHS = 10 
LIVE_WINDOW = 5 # Analiza ostatnich 5 sekund dla ostrzeżeń live

# --- ZMIENNE GLOBALNE ---
current_data = None; point_counter = 0; is_measuring = False
sats_visible = {}
dop = {'p': 99.9, 'h': 99.9, 'v': 99.9}
pos_history = deque(maxlen=LIVE_WINDOW) # Kolejka na ostatnie pozycje

# [Reszta klas GeoidManager i Transformer pozostaje bez zmian]
# ... (pomijam dla czytelności, załóżmy że są w kodzie) ...

print("="*95 + "\n   RTK BOX v33 - LIVE QUALITY GUARD (SAT SUMMING + MULTIPATH ALERT)\n" + "="*95)

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed:
            # 1. Sumowanie satelitów (wyłapujemy wszystkie talkery: GP, GL, GA, GB)
            if "GSV" in parsed.identity:
                talker = parsed.identity[:2]
                sats_visible[talker] = parsed.numSV

            if "GSA" in parsed.identity:
                dop['p'], dop['h'], dop['v'] = float(parsed.PDOP), float(parsed.HDOP), float(parsed.VDOP)

            if parsed.identity in ["GGA", "GNGGA", "GNS", "GNGNS"]:
                if parsed.lat and parsed.lat != 0:
                    # Obliczamy sumę SV
                    sv_sum = sum(sats_visible.values()) if len(sats_visible) > 0 else parsed.numSV
                    
                    x, y = tr.transform(parsed.lon, parsed.lat)
                    h_norm = (parsed.alt + parsed.sep) - geoid.get_n(parsed.lat, parsed.lon)
                    q = getattr(parsed, 'quality', 1)
                    st_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                    
                    # Dodajemy do historii dla analizy LIVE
                    pos_history.append((x, y))
                    
                    # ANALIZA LIVE: Obliczamy rozrzut (Sigma) z ostatnich 5 sekund
                    live_sigma = 0
                    alert = ""
                    if len(pos_history) == LIVE_WINDOW:
                        std_x = np.std([p[0] for p in pos_history])
                        std_y = np.std([p[1] for p in pos_history])
                        live_sigma = np.sqrt(std_x**2 + std_y**2) * 100 # w cm
                        if live_sigma > 5.0 and q == 4: # Jeśli FIXED skacze powyżej 5cm
                            alert = "!! ODBICIA / BUDYNEK !!"
                        elif live_sigma > 20.0:
                            alert = "!! DUŻY DRYF !!"

                    current_data = {'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h_norm, 
                                    'q_txt': st_txt, 'sv': sv_sum, 'pdop': dop['p'], 'hdop': dop['h'], 'vdop': dop['v']}
                    
                    if not is_measuring:
                        # WYŚWIETLANIE LIVE Z ALERTEM
                        print(f"[{time.strftime('%H:%M:%S')}] SV:{sv_sum:02} | P:{dop['p']:.1f} | {st_txt:6} | Err:{live_sigma:4.1f}cm | {alert:22}", end='\r')
except KeyboardInterrupt: pass
