import serial
import socket
import threading
import base64
import time
import struct
import numpy as np
from pyubx2 import UBXReader
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer

# =================================================================
# 1. KONFIGURACJA
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

# Pozycja startowa (Żnin) - aby utrzymać połączenie przed FIXem
HOME_LAT = 52.8500
HOME_LON = 17.7160

# Zmienne współdzielone
current_lat = HOME_LAT
current_lon = HOME_LON
has_real_fix = False

# =================================================================
# 2. SILNIK GEOIDY I TRANSFORMACJI
# =================================================================
class GeoidManager:
    def __init__(self, path):
        print(f"[*] Wczytywanie geoidy: {path}...")
        try:
            with open(path, 'rb') as f:
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            lats = np.linspace(self.y_min, self.y_min + (self.rows - 1) * self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols - 1) * self.x_step, self.cols)
            self.interp = RegularGridInterpolator((lats, lons), data, bounds_error=False, fill_value=None)
            print("[+] Geoida gotowa.")
        except Exception as e:
            print(f"[!] Błąd krytyczny geoidy: {e}")
            exit()

    def get_undulation(self, lat, lon):
        return float(self.interp((lat, lon)))

class CoordinateTransformer:
    def __init__(self):
        # EPSG:4326 (WGS84) -> EPSG:2177 (Polska 2000 południk 18)
        self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)

    def to_2177(self, lat, lon):
        return self.transformer.transform(lon, lat)

# =================================================================
# 3. OBSŁUGA NTRIP (ŁĄCZNOŚĆ Z SERWEREM)
# =================================================================
def ntrip_handler(ser):
    global current_lat, current_lon
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                print(f"\n[NTRIP] Zalogowano. Pobieram poprawki dla {NTRIP_MOUNT}...")
                
                headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\n"
                           f"User-Agent: NTRIP-v4-Client\r\n"
                           f"Authorization: Basic {auth}\r\n"
                           f"Connection: close\r\n\r\n")
                sock.sendall(headers.encode())

                last_gga = 0
                while True:
                    # Wysyłaj GGA co 10 sekund, by serwer nie zerwał połączenia
                    if time.time() - last_gga > 10:
                        now = time.strftime("%H%M%S", time.gmtime())
                        gga = pynmeagps.NMEAMessage("GP", "GGA", 
                                                    time=now, 
                                                    lat=current_lat, NS="N", 
                                                    lon=current_lon, EW="E", 
                                                    quality=1, numSV=15, HDOP=0.9, 
                                                    alt=100.0, altUnit="M", 
                                                    sep=33.0, sepUnit="M")
                        sock.sendall(gga.serialize())
                        last_gga = time.time()

                    sock.settimeout(0.5)
                    try:
                        data = sock.recv(4096)
                        if not data: break
                        ser.write(data)
                    except socket.timeout:
                        continue
        except Exception:
            time.sleep(5)

# =================================================================
# 4. PĘTLA GŁÓWNA
# =================================================================
def main():
    global current_lat, current_lon, has_real_fix
    
    geoid = GeoidManager(GTX_FILE)
    proj = CoordinateTransformer()
    
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
    except Exception as e:
        print(f"[!] Błąd portu: {e}")
        return

    # Uruchom NTRIP w tle
    threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
    
    ubr = UBXReader(ser)
    print("\n" + "="*60)
    print("             RTK BOX v4 - MONITOR POZYCJI")
    print("="*60)

    try:
        while True:
            (raw, parsed) = ubr.read()
            if parsed:
                if parsed.identity == "NAV-PVT":
                    # u-blox podaje lat/lon pomnożone przez 10^7
                    lat = parsed.lat / 10**7
                    lon = parsed.lon / 10**7
                    num_sv = parsed.numSV
                    fix_type = parsed.fixType 
                    
                    if fix_type >= 2:
                        current_lat, current_lon = lat, lon
                        has_real_fix = True

                    # Status RTK
                    rtk_val = getattr(parsed, "carrSoln", 0)
                    if rtk_val == 2: status = "FIXED (cm)"
                    elif rtk_val == 1: status = "FLOAT (dm)"
                    else: status = "3D Fix (m)"
                    
                    if fix_type < 2:
                        print(f"[{time.strftime('%H:%M:%S')}] Szukanie satelitów... SV: {num_sv}   ", end='\r')
                        continue

                    # Obliczenia
                    h_ell = parsed.height / 1000.0 # mm -> m
                    x_2177, y_2177 = proj.to_2177(lat, lon)
                    n = geoid.get_undulation(lat, lon)
                    h_norm = h_ell - n

                    # Wynik na ekran
                    output = (f"[{time.strftime('%H:%M:%S')}] SV:{num_sv:02} | {status:10} | "
                             f"X:{x_2177:.2f} Y:{y_2177:.2f} | H:{h_norm:.3f}m")
                    print(output, end='\r')
                    
    except KeyboardInterrupt:
        print("\n\nZatrzymano. Do zobaczenia!")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
