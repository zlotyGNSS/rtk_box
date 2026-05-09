import serial
import socket
import threading
import base64
import time
import struct
import numpy as np
from pyubx2 import UBXReader, pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer

# =================================================================
# KONFIGURACJA
# =================================================================
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
GTX_FILE = 'geoida_PL.gtx'

# Dane NTRIP
NTRIP_HOST = "91.198.76.2" 
NTRIP_PORT = 8080
NTRIP_MOUNT = "RTN4G_VRS_RTCM32"
NTRIP_USER = "kzlotnic"
NTRIP_PASS = "Bartek1!!"

# Przybliżona pozycja (Żnin) - używana, gdy u-blox jeszcze nie ma fixa
# Zapobiega rozłączaniu przez serwer NTRIP
HOME_LAT = 52.8500
HOME_LON = 17.7160

# Globalne zmienne do wymiany danych między wątkami
current_lat = HOME_LAT
current_lon = HOME_LON
has_real_fix = False

# =================================================================
# KLASY (Geoida i Układ 2177)
# =================================================================
class GeoidManager:
    def __init__(self, path):
        print(f"[*] Wczytywanie siatki geoidy: {path}")
        try:
            with open(path, 'rb') as f:
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            lats = np.linspace(self.y_min, self.y_min + (self.rows - 1) * self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols - 1) * self.x_step, self.cols)
            self.interp = RegularGridInterpolator((lats, lons), data)
            print("[+] Geoida załadowana poprawnie.")
        except Exception as e:
            print(f"[!] BŁĄD PLIKU GEOIDY: {e}")
            exit()

    def get_undulation(self, lat, lon):
        try: return float(self.interp((lat, lon)))
        except: return None

class CoordinateTransformer:
    def __init__(self):
        self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)

    def to_2177(self, lat, lon):
        return self.transformer.transform(lon, lat)

# =================================================================
# WĄTEK NTRIP (Z feedbackiem GGA)
# =================================================================
def ntrip_handler(ser):
    global current_lat, current_lon
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                print(f"\n[NTRIP] Połączono z {NTRIP_HOST}. Autoryzacja...")
                
                headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\n"
                           f"User-Agent: NTRIP PythonClient\r\n"
                           f"Authorization: Basic {auth}\r\n"
                           f"Connection: close\r\n\r\n")
                sock.sendall(headers.encode())

                last_gga_time = 0
                while True:
                    # Wysyłaj pozycję GGA do serwera co 10 sekund (wymagane dla VRS)
                    if time.time() - last_gga_time > 10:
                        # Tworzymy ramkę NMEA GGA na podstawie aktualnej pozycji (realnej lub "home")
                        now = time.strftime("%H%M%S", time.gmtime())
                        gga = pynmeagps.NMEAMessage("GP", "GGA", 
                                                    time=now, 
                                                    lat=current_lat, NS="N", 
                                                    lon=current_lon, EW="E", 
                                                    quality=1, numSV=12, HDOP=1.0, 
                                                    alt=100.0, altUnit="M", 
                                                    sep=33.0, sepUnit="M").serialize()
                        sock.sendall(gga)
                        last_gga_time = time.time()

                    sock.settimeout(0.1)
                    try:
                        data = sock.recv(2048)
                        if not data: break
                        ser.write(data) # Przesyłamy poprawki do u-bloxa
                    except socket.timeout:
                        continue
        except Exception:
            print("[NTRIP] Czekam na stabilne połączenie...", end='\r')
            time.sleep(5)

# =================================================================
# GŁÓWNA PĘTLA PROGRAMU
# =================================================================
def main():
    global current_lat, current_lon, has_real_fix
    
    geoid = GeoidManager(GTX_FILE)
    proj = CoordinateTransformer()
    
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
    except Exception as e:
        print(f"[!] Nie można otworzyć portu {SERIAL_PORT}. Sprawdź kabel USB!")
        return

    # Start wątku NTRIP
    threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
    
    ubr = UBXReader(ser)
    print("\n" + "="*50)
    print("      SYSTEM POMIAROWY RTK v3 - START")
    print("="*50)

    try:
        while True:
            (raw, parsed) = ubr.read()
            if parsed:
                # Interesuje nas wiadomość NAV-PVT
                if parsed.identity == "NAV-PVT":
                    lat, lon = parsed.lat, parsed.lon
                    num_sv = parsed.numSV
                    fix_type = parsed.fixType # 0=no fix, 2=2D, 3=3D, 4=GNSS+DR
                    
                    # Aktualizujemy pozycję dla wątku NTRIP (tylko jeśli mamy fix)
                    if fix_type >= 2:
                        current_lat, current_lon = lat, lon
                        has_real_fix = True

                    # Status RTK (carrSoln: 0=brak, 1=Float, 2=Fixed)
                    rtk_val = getattr(parsed, "carrSoln", 0)
                    status_text = "FIXED (cm)" if rtk_val == 2 else "FLOAT (dm)" if rtk_val == 1 else "3D Fix (m)"
                    
                    if fix_type < 2:
                        print(f"[{time.strftime('%H:%M:%S')}] Szukanie satelitów... Widzę: {num_sv} ", end='\r')
                        continue

                    # Obliczenia wysokości i układu 2177
                    h_ell = parsed.height / 1000.0
                    x_2177, y_2177 = proj.to_2177(lat, lon)
                    n = geoid.get_undulation(lat, lon)

                    if n is not None:
                        h_norm = h_ell - n
                        print(f"[{time.strftime('%H:%M:%S')}] SV:{num_sv} | {status_text} | X:{x_2177:.2f} Y:{y_2177:.2f} | H:{h_norm:.3f}m    ", end='\r')
                    
    except KeyboardInterrupt:
        print("\n\nZamykanie systemu...")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
