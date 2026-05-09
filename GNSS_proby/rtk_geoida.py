import serial
import socket
import threading
import base64
import time
import struct
import numpy as np
from pyubx2 import UBXReader
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer  # <--- Nowa biblioteka do układu 2177

# =================================================================
# KONFIGURACJA
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
# NOWA KLASA: KONWERSJA NA UKŁAD 2177
# =================================================================
class CoordinateTransformer:
    def __init__(self):
        # Definiujemy transformację:
        # Z WGS84 (EPSG:4326 - to co daje GPS) 
        # Na PL-2000 strefa 6 (EPSG:2177 - polski układ płaski)
        # always_xy=True sprawia, że wynik to (X, Y), a nie (Y, X)
        self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)

    def to_2177(self, lat, lon):
        """Zamienia stopnie na metry w układzie 2177"""
        # W pyproj dla always_xy=True podajemy (lon, lat)
        x_2177, y_2177 = self.transformer.transform(lon, lat)
        return x_2177, y_2177

# =================================================================
# KLASA GEOIDY (BEZ ZMIAN)
# =================================================================
class GeoidManager:
    def __init__(self, path):
        with open(path, 'rb') as f:
            h = struct.unpack('>ddddii', f.read(40))
        self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
        data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
        lats = np.linspace(self.y_min, self.y_min + (self.rows - 1) * self.y_step, self.rows)
        lons = np.linspace(self.x_min, self.x_min + (self.cols - 1) * self.x_step, self.cols)
        self.interp = RegularGridInterpolator((lats, lons), data)

    def get_undulation(self, lat, lon):
        try: return self.interp((lat, lon))
        except: return None

# =================================================================
# FUNKCJA NTRIP (BEZ ZMIAN)
# =================================================================
def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    headers = f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n"
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                sock.sendall(headers.encode())
                while True:
                    data = sock.recv(2048)
                    if not data: break
                    ser.write(data) 
        except Exception:
            time.sleep(5)

# =================================================================
# GŁÓWNA PĘTLA
# =================================================================
def main():
    geoid = GeoidManager(GTX_FILE)
    proj = CoordinateTransformer() # Inicjalizacja przelicznika 2177
    
    ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
    threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
    ubr = UBXReader(ser)

    print("System gotowy. Wyświetlam współrzędne 2177...")

    for (raw, parsed) in ubr:
        if parsed.identity == "NAV-PVT":
            lat, lon = parsed.lat, parsed.lon
            h_ell = parsed.height / 1000.0
            rtk_val = getattr(parsed, "carrSoln", 0)
            
            # 1. Obliczamy współrzędne płaskie X i Y
            x_2177, y_2177 = proj.to_2177(lat, lon)
            
            # 2. Obliczamy wysokość normalną (H)
            n = geoid.get_undulation(lat, lon)
            
            if n is not None:
                h_norm = h_ell - n
                status = "FIXED" if rtk_val == 2 else "FLOAT" if rtk_val == 1 else "NO RTK"
                
                print("-" * 50)
                print(f"STATUS: {status} | Satelity: {parsed.numSV}")
                # X w układzie 2000 to zazwyczaj ok. 5-6 mln metrów, Y to ok. 6 mln metrów
                print(f"XY (2177): X = {x_2177:.3f}, Y = {y_2177:.3f}")
                print(f"H (2177):  {h_norm:.3f} m")

if __name__ == "__main__":
    main()
