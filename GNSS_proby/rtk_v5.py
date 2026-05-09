import serial, socket, threading, base64, time, struct
import numpy as np
from pyubx2 import UBXReader
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer

# --- KONFIGURACJA ---
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
GTX_FILE = 'geoida_PL.gtx'

NTRIP_HOST = "91.198.76.2" 
NTRIP_PORT = 8080
NTRIP_MOUNT = "RTN4G_VRS_RTCM32"
NTRIP_USER = "kzlotnic"
NTRIP_PASS = "Bartek1!!"

# Startowa pozycja dla serwera (Żnin)
HOME_LAT, HOME_LON = 52.8500, 17.7160
curr_lat, curr_lon = HOME_LAT, HOME_LON

# --- GEOIDA I UKŁAD 2177 ---
class GeoidManager:
    def __init__(self, path):
        try:
            with open(path, 'rb') as f:
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            lats = np.linspace(self.y_min, self.y_min + (self.rows-1)*self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols-1)*self.x_step, self.cols)
            self.interp = RegularGridInterpolator((lats, lons), data, bounds_error=False, fill_value=None)
            print("[+] Geoida wczytana.")
        except: print("[!] Błąd geoidy!"); exit()
    def get_n(self, lat, lon): return float(self.interp((lat, lon)))

class Proj2177:
    def __init__(self): self.tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
    def transform(self, lat, lon): return self.tr.transform(lon, lat)

# --- OBSŁUGA NTRIP ---
def ntrip_thread(ser):
    global curr_lat, curr_lon
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=5) as sock:
                headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\n"
                           f"User-Agent: NTRIP-v5\r\n"
                           f"Authorization: Basic {auth}\r\n"
                           f"Connection: close\r\n\r\n")
                sock.sendall(headers.encode())
                print(f"\n[NTRIP] Połączono z {NTRIP_MOUNT}")
                
                while True:
                    # Wysyłaj GGA co 10s
                    now = time.strftime("%H%M%S", time.gmtime())
                    gga = pynmeagps.NMEAMessage("GP", "GGA", time=now, lat=curr_lat, NS="N", 
                                                lon=curr_lon, EW="E", quality=1, numSV=12, 
                                                HDOP=1.0, alt=100.0, altUnit="M", sep=33.0, sepUnit="M")
                    sock.sendall(gga.serialize())
                    
                    # Odbieraj poprawki przez 10 sekund
                    start_time = time.time()
                    while time.time() - start_time < 10:
                        sock.settimeout(1)
                        data = sock.recv(2048)
                        if not data: break
                        ser.write(data)
        except:
            time.sleep(2)

# --- MAIN ---
def main():
    global curr_lat, curr_lon
    geoid = GeoidManager(GTX_FILE); proj = Proj2177()
    try: ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
    except: print("Błąd portu!"); return
    
    threading.Thread(target=ntrip_thread, args=(ser,), daemon=True).start()
    ubr = UBXReader(ser)
    
    print("=== MONITOR RTK v5 ===")
    while True:
        try:
            (raw, parsed) = ubr.read()
            if parsed:
                # Obsługa binarna (UBX)
                if parsed.identity == "NAV-PVT":
                    lat, lon = parsed.lat/10**7, parsed.lon/10**7
                    h_ell = parsed.height/1000.0
                    sv, rtk = parsed.numSV, getattr(parsed, "carrSoln", 0)
                    fix = parsed.fixType
                # Obsługa tekstowa (NMEA) - jako zapas
                elif parsed.identity == "GGA":
                    lat, lon, h_ell = parsed.lat, parsed.lon, parsed.alt
                    sv, rtk, fix = parsed.numSV, parsed.quality, 3
                else: continue

                if fix >= 2:
                    curr_lat, curr_lon = lat, lon
                    x, y = proj.transform(lat, lon)
                    n = geoid.get_n(lat, lon)
                    st = "FIXED" if rtk == 2 else "FLOAT" if rtk == 1 else "3D"
                    print(f"[{time.strftime('%H:%M:%S')}] SV:{sv:02} {st} | X:{x:.2f} Y:{y:.2f} | H:{h_ell-n:.3f}m", end='\r')
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] Szukanie satelitów... (SV: {getattr(parsed, 'numSV', 0)})", end='\r')
        except KeyboardInterrupt: break

main()
