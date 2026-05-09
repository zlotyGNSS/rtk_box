import serial, socket, threading, base64, time, struct
import numpy as np
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

# Sztuczna pozycja do startu NTRIP
HOME_LAT, HOME_LON = 52.8500, 17.7160
curr_lat, curr_lon = HOME_LAT, HOME_LON

# --- SILNIK OBLICZENIOWY ---
class GeoidManager:
    def __init__(self, path):
        with open(path, 'rb') as f:
            h = struct.unpack('>ddddii', f.read(40))
        self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
        data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
        lats = np.linspace(self.y_min, self.y_min + (self.rows-1)*self.y_step, self.rows)
        lons = np.linspace(self.x_min, self.x_min + (self.cols-1)*self.x_step, self.cols)
        self.interp = RegularGridInterpolator((lats, lons), data, bounds_error=False, fill_value=None)

    def get_n(self, lat, lon): return float(self.interp((lat, lon)))

def ntrip_handler(ser):
    global curr_lat, curr_lon
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\n"
                           f"User-Agent: NTRIP-v8\r\n"
                           f"Authorization: Basic {auth}\r\n"
                           f"Connection: close\r\n\r\n")
                sock.sendall(headers.encode())
                print("\n[NTRIP] Połączono i pobieram poprawki...")
                
                while True:
                    # Wysyłaj aktualną pozycję GGA do serwera co 10s
                    now = time.strftime("%H%M%S", time.gmtime())
                    gga = pynmeagps.NMEAMessage("GP", "GGA", time=now, lat=curr_lat, NS="N", 
                                                lon=curr_lon, EW="E", quality=1, numSV=12, 
                                                HDOP=1.0, alt=100.0, altUnit="M", sep=33.0, sepUnit="M")
                    sock.sendall(gga.serialize())
                    
                    # Odbieraj dane przez 10 sekund i ładuj do u-bloxa
                    sock.settimeout(1)
                    start = time.time()
                    while time.time() - start < 10:
                        try:
                            data = sock.recv(2048)
                            if not data: break
                            ser.write(data)
                        except socket.timeout: continue
        except: time.sleep(5)

# --- START ---
geoid = GeoidManager(GTX_FILE)
tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

print("\n" + "="*60)
print("             RTK BOX v8 - TRYB NMEA (ŻYWY)")
print("="*60)

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed:
            # Szukamy ramki GGA (zawiera pozycję i jakość RTK)
            if parsed.identity == "GGA" or parsed.identity == "GNGGA":
                lat, lon = parsed.lat, parsed.lon
                if lat == 0 or lat is None:
                    print(f"[{time.strftime('%H:%M:%S')}] Szukam satelitów (SV: {parsed.numSV})...", end='\r')
                    continue

                curr_lat, curr_lon = lat, lon
                q = parsed.quality # 1=Fix, 2=DGPS, 4=RTK Fixed, 5=RTK Float
                
                status = "FIXED (cm)" if q == 4 else "FLOAT (dm)" if q == 5 else "3D Fix (m)"
                x, y = tr.transform(lon, lat)
                n = geoid.get_n(lat, lon)
                h_norm = parsed.alt - n
                
                print(f"[{time.strftime('%H:%M:%S')}] SV:{parsed.numSV:02} | {status:10} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m", end='\r')
except KeyboardInterrupt:
    print("\nZatrzymano.")
finally:
    ser.close()
