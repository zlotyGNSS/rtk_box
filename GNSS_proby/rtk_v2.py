import serial
import socket
import threading
import base64
import time
import struct
import numpy as np
from pyubx2 import UBXReader
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer

# =================================================================
# KONFIGURACJA (Wpisz swoje dane)
# =================================================================
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
GTX_FILE = 'geoida_PL.gtx'

NTRIP_HOST = "91.198.76.2" 
NTRIP_PORT = 8080
NTRIP_MOUNT = "RTN4G_VRS_RTCM32"
NTRIP_USER = "kzlotnic"
NTRIP_PASS = "Bartek1!!"

# =================================================================
# KLASY POMOCNICZE (Geoida i Układ 2177)
# =================================================================
class GeoidManager:
    def __init__(self, path):
        print(f"[*] Ładowanie geoidy: {path}...")
        try:
            with open(path, 'rb') as f:
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            lats = np.linspace(self.y_min, self.y_min + (self.rows - 1) * self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols - 1) * self.x_step, self.cols)
            self.interp = RegularGridInterpolator((lats, lons), data)
            print("[+] Geoida gotowa.")
        except Exception as e:
            print(f"[!] Błąd geoidy: {e}")
            exit()

    def get_undulation(self, lat, lon):
        try: return self.interp((lat, lon))
        except: return None

class CoordinateTransformer:
    def __init__(self):
        self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)

    def to_2177(self, lat, lon):
        return self.transformer.transform(lon, lat)

# =================================================================
# OBSŁUGA NTRIP (Poprawki RTK)
# =================================================================
def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\n"
               f"User-Agent: NTRIP Python\r\n"
               f"Authorization: Basic {auth}\r\n"
               f"Connection: close\r\n\r\n")

    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                print(f"\n[NTRIP] Połączono z {NTRIP_HOST}. Pobieram poprawki...")
                sock.sendall(headers.encode())
                while True:
                    data = sock.recv(2048)
                    if not data: break
                    ser.write(data) 
        except Exception:
            print("\n[NTRIP] Błąd połączenia. Ponawiam za 5s...")
            time.sleep(5)

# =================================================================
# GŁÓWNA PĘTLA (Wersja v2 - Diagnostyczna)
# =================================================================
def main():
    geoid = GeoidManager(GTX_FILE)
    proj = CoordinateTransformer()
    
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
    except Exception as e:
        print(f"[!] Nie można otworzyć portu {SERIAL_PORT}: {e}")
        return

    threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
    ubr = UBXReader(ser)

    print("\n--- ODBIORNIK RTK v2 URUCHOMIONY ---")
    print("Oczekiwanie na dane z satelitów (w domu może to trwać wiecznie)...")

    while True:
        try:
            (raw, parsed) = ubr.read()
            if parsed:
                # Wyświetlamy co sekundę typ odbieranej ramki, żeby wiedzieć że żyje
                if parsed.identity == "NAV-PVT":
                    if parsed.fixType == 0:
                        print(f"[{time.strftime('%H:%M:%S')}] Szukam satelitów... (FixType: 0)", end='\r')
                        continue

                    # Jeśli złapie Fix (nawet 2D/3D bez RTK), zacznie liczyć:
                    lat, lon = parsed.lat, parsed.lon
                    h_ell = parsed.height / 1000.0
                    rtk_val = getattr(parsed, "carrSoln", 0)
                    
                    x_2177, y_2177 = proj.to_2177(lat, lon)
                    n = geoid.get_undulation(lat, lon)
                    
                    if n is not None:
                        h_norm = h_ell - n
                        status = "FIXED (cm)" if rtk_val == 2 else "FLOAT (dm)" if rtk_val == 1 else "3D Fix (m)"
                        
                        print("\n" + "="*50)
                        print(f"CZAS: {time.strftime('%H:%M:%S')} | STATUS: {status} | SAT: {parsed.numSV}")
                        print(f"WSPÓŁRZĘDNE 2177: X: {x_2177:.3f}, Y: {y_2177:.3f}")
                        print(f"WYSOKOŚĆ H: {h_norm:.3f} m (Odchyłka N: {n:.3f})")
                        print("="*50)
                else:
                    # Opcjonalnie: odkomentuj linię poniżej, jeśli chcesz widzieć każdą ramkę NMEA
                    # print(f"Odebrano ramkę: {parsed.identity}", end='\r')
                    pass

        except KeyboardInterrupt:
            print("\nZamykanie programu...")
            break
        except Exception as e:
            print(f"\nBłąd pętli: {e}")

if __name__ == "__main__":
    main()
