import serial, socket, threading, base64, time, struct, csv
import numpy as np
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer
from gpiozero import Button, LED, Buzzer

# --- KONFIGURACJA ---
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
GTX_FILE = 'geoida_PL.gtx'
AVERAGING_EPOCHS = 10 

BUTTON_PIN, LED_PIN, BUZZER_PIN = 17, 27, 22
NTRIP_HOST, NTRIP_PORT, NTRIP_MOUNT = "91.198.76.2", 8080, "RTN4G_VRS_RTCM32"
NTRIP_USER, NTRIP_PASS = "kzlotnic", "Bartek1!!"

# --- ZMIENNE GLOBALNE ---
led = LED(LED_PIN); buzzer = Buzzer(BUZZER_PIN)
current_data = None; is_measuring = False; point_counter = 0
sats_visible = {}
dop = {'p': 99.9, 'h': 99.9, 'v': 99.9} # Słownik na DOP-y

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

def handle_button():
    global is_measuring, current_data
    if is_measuring or current_data is None: return
    if current_data['q_txt'] != "FIXED":
        print(f"\n[INFO] Brak FIXED! Status: {current_data['q_txt']}"); buzzer.beep(0.3, 0.1, 1); return
    threading.Thread(target=measure).start()

def measure():
    global is_measuring, point_counter, current_data, LOG_FILE
    is_measuring = True; samples = []
    print(f"\n[POMIAR] Punkt {point_counter + 1}...")
    for i in range(AVERAGING_EPOCHS):
        if current_data and current_data['q_txt'] == "FIXED":
            samples.append(current_data); buzzer.beep(0.05, 0.05, 1)
            print(f"\rPostęp: {i+1}/{AVERAGING_EPOCHS}s | H:{current_data['hdop']:.1f} V:{current_data['vdop']:.1f}", end="")
        else:
            print("\n[BŁĄD] Przerwano - utrata FIXED!"); buzzer.beep(0.5, 0.1, 2)
            is_measuring = False; return
        time.sleep(1)
    
    if len(samples) == AVERAGING_EPOCHS:
        avg = {k: sum(p[k] for p in samples)/len(samples) for k in ['x', 'y', 'h', 'pdop', 'hdop', 'vdop']}
        point_counter += 1
        with open(LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([point_counter, time.strftime('%H:%M:%S'), "FIXED", 
                                    round(avg['x'], 3), round(avg['y'], 3), round(avg['h'], 3), 
                                    round(avg['pdop'], 2), round(avg['hdop'], 2), round(avg['vdop'], 2), 
                                    current_data['sv']])
        buzzer.beep(0.5, 0.1, 1); print(f"\n[OK] Punkt zapisany (H-DOP: {avg['hdop']:.2f})")
    is_measuring = False

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
                    sock.settimeout(2); d = sock.recv(4096); ser.write(d) if d else None
        except: time.sleep(5)

# --- START ---
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x03\x01\x2a\x10') # GSV On
ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x02\x01\x26\x0c') # GSA On

geoid = GeoidManager(GTX_FILE); tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
LOG_FILE = f"pomiar_v29_{time.strftime('%Y%m%d_%H%M%S')}.csv"

with open(LOG_FILE, 'w', newline='') as f:
    csv.writer(f).writerow(["Nr", "Czas", "Status", "X", "Y", "H", "PDOP", "HDOP", "VDOP", "SV"])

btn = Button(BUTTON_PIN); btn.when_pressed = handle_button
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

print("="*85 + "\n   RTK BOX v29 - FULL GEOMETRY MONITOR (H-DOP & V-DOP)\n" + "="*85)

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed:
            if "GSA" in parsed.identity:
                dop['p'], dop['h'], dop['v'] = float(parsed.PDOP), float(parsed.HDOP), float(parsed.VDOP)
            if "GSV" in parsed.identity:
                sats_visible[parsed.identity[:2]] = parsed.numSV

            if parsed.identity in ["GGA", "GNGGA", "GNS", "GNGNS"]:
                if parsed.lat and parsed.lat != 0:
                    q = 4 if ('R' in getattr(parsed, 'posMode', '')) or (getattr(parsed, 'quality', 0) == 4) else 5 if ('F' in getattr(parsed, 'posMode', '')) or (getattr(parsed, 'quality', 0) == 5) else 1
                    sv_sum = sum(sats_visible.values()) if sats_visible else parsed.numSV
                    h_norm = (parsed.alt + parsed.sep) - geoid.get_n(parsed.lat, parsed.lon)
                    x, y = tr.transform(parsed.lon, parsed.lat)
                    
                    led.off()
                    if q == 4: led.on()
                    elif q == 5: led.blink(0.1, 0.1)
                    else: led.blink(1.0, 1.0)
                    
                    st_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                    current_data = {'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h_norm, 'q_txt': st_txt, 'sv': sv_sum, 'pdop': dop['p'], 'hdop': dop['h'], 'vdop': dop['v']}
                    
                    if not is_measuring:
                        print(f"[{time.strftime('%H:%M:%S')}] SV:{sv_sum:02} | H:{dop['h']:.1f} V:{dop['v']:.1f} | {st_txt:6} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m ", end='\r')
except KeyboardInterrupt: pass
finally: led.off(); buzzer.off(); ser.close()
