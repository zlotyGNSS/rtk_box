import serial, socket, threading, base64, time, struct, csv
import numpy as np
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer
from gpiozero import Button, LED, Buzzer

# --- KONFIGURACJA ---
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200 # Jeśli to nie zadziała, spróbujemy 9600
GTX_FILE = 'geoida_PL.gtx'

BUTTON_PIN, LED_PIN, BUZZER_PIN = 17, 27, 22
NTRIP_HOST, NTRIP_PORT, NTRIP_MOUNT = "91.198.76.2", 8080, "RTN4G_VRS_RTCM32"
NTRIP_USER, NTRIP_PASS = "kzlotnic", "Bartek1!!"

# --- KOMENDY "BUDZIKA" (Włączanie wszystkiego co się da) ---
ENABLE_ALL_NMEA = [
    b'\xb5\x62\x06\x01\x03\x00\xf0\x00\x01\x00\x10', # GGA On
    b'\xb5\x62\x06\x01\x03\x00\xf0\x0d\x01\x02\x34', # GNS On
    b'\xb5\x62\x06\x01\x03\x00\xf0\x04\x01\x0b\x18', # RMC On
    b'\xb5\x62\x06\x17\x14\x00\x00\x41\x00\x02\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x75\x57' # NMEA 4.1
]

led = LED(LED_PIN); buzzer = Buzzer(BUZZER_PIN)
current_data = None; point_counter = 0

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
        except: self.interp = None
    def get_n(self, lat, lon): return float(self.interp((lat, lon))) if self.interp else 0

def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                sock.sendall(f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n".encode())
                while True:
                    l, n = (current_data['lat'], current_data['lon']) if current_data else (52.85, 17.71)
                    gga = pynmeagps.NMEAMessage("GP", "GGA", 0, time=time.strftime("%H%M%S", time.gmtime()), lat=l, NS="N", lon=n, EW="E", quality=1, numSV=12, HDOP=1.0, alt=100.0, altUnit="M", sep=33.0, sepUnit="M")
                    sock.sendall(gga.serialize())
                    sock.settimeout(1); d = sock.recv(4096)
                    if d: ser.write(d)
        except: time.sleep(5)

# --- START ---
print("[*] Szukam sygnału u-blox...")
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)

# Próba "obudzenia" modułu
for cmd in ENABLE_ALL_NMEA:
    ser.write(cmd)
    time.sleep(0.1)

geoid = GeoidManager(GTX_FILE); tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

print("="*70 + "\n   RTK BOX v24 - SIGNAL HUNTER (RAW MONITOR)\n" + "="*70)

try:
    while True:
        # Czytamy surowe bajty, żeby sprawdzić czy port żyje
        if ser.in_waiting > 0:
            (raw, parsed) = nmr.read()
            if parsed:
                if parsed.identity in ["GGA", "GNGGA", "GNS", "GNGNS"]:
                    if parsed.lat and parsed.lat != 0:
                        q = 4 if (hasattr(parsed, 'quality') and parsed.quality == 4) or (hasattr(parsed, 'posMode') and 'R' in parsed.posMode) else 1
                        h_norm = (parsed.alt + parsed.sep) - geoid.get_n(parsed.lat, parsed.lon)
                        x, y = tr.transform(parsed.lon, parsed.lat)
                        
                        st_txt = "FIXED" if q == 4 else "3D/FLOAT"
                        current_data = {'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h_norm, 'q': q}
                        
                        print(f"[{time.strftime('%H:%M:%S')}] {parsed.identity:5} | SV:{parsed.numSV:02} | {st_txt:8} | X:{x:.2f} Y:{y:.2f} ", end='\r')
            else:
                # Jeśli nmr.read() nic nie zwraca, a w buforze coś jest, wypisz surowe dane
                raw_line = ser.readline().decode('ascii', errors='replace').strip()
                if raw_line:
                    print(f"[RAW]: {raw_line[:60]}...") 
        else:
            time.sleep(0.1)
except KeyboardInterrupt: pass
finally: ser.close()
