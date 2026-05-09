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
dop_values = {'pdop': 99.9, 'hdop': 99.9, 'vdop': 99.9} # Bufor na parametry jakości

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
        print(f"\n[BLOKADA] Brak FIXED! Czekaj..."); buzzer.beep(0.3, 0.1, 1); return
    threading.Thread(target=measure).start()

def measure():
    global is_measuring, point_counter, current_data, LOG_FILE
    is_measuring = True; samples = []
    print(f"\n[POMIAR] Uśrednianie punktu {point_counter + 1}...")
    for i in range(AVERAGING_EPOCHS):
        if current_data and current_data['q_txt'] == "FIXED":
            samples.append(current_data); buzzer.beep(0.05, 0.05, 1)
            print(f"\rSekunda: {i+1}/{AVERAGING_EPOCHS} | PDOP: {current_data['pdop']:.1f}", end="")
        else:
            print("\n[BŁĄD] Utrata FIXED!"); buzzer.beep(0.5, 0.1, 2)
            is_measuring = False; return
        time.sleep(1)
    
    if len(samples) == AVERAGING_EPOCHS:
        avg_x = sum(p['x'] for p in samples) / len(samples)
        avg_y = sum(p['y'] for p in samples) / len(samples)
        avg_h = sum(p['h'] for p in samples) / len(samples)
        avg_pdop = sum(p['pdop'] for p in samples) / len(samples)
        
        point_counter += 1
        with open(LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([point_counter, time.strftime('%H:%M:%S'), "FIXED", 
                                    round(avg_x, 3), round(avg_y, 3), round(avg_h, 3), 
                                    round(avg_pdop, 2), current_data['sv']])
        buzzer.beep(0.5, 0.1, 1); print(f"\n[OK] Zapisano z PDOP: {avg_pdop:.2f}")
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
# Włączamy GSV (Satelity) i GSA (DOPy)
ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x03\x01\x2a\x10') 
ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x02\x01\x26\x0c') # ENABLE GSA

geoid = GeoidManager(GTX_FILE); tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
LOG_FILE = f"pomiar_v28_{time.strftime('%Y%m%d_%H%M%S')}.csv"
btn = Button(BUTTON_PIN); btn.when_pressed = handle_button
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

with open(LOG_FILE, 'w', newline='') as f:
    csv.writer(f).writerow(["Nr", "Czas", "Status", "X", "Y", "H", "PDOP", "SV"])

print("="*75 + "\n   RTK BOX v28 - PRECISION MONITOR (DOP & QUALITY)\n" + "="*75)

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed:
            # 1. Wyciągamy DOPy z ramek GSA
            if "GSA" in parsed.identity:
                dop_values['pdop'] = float(parsed.PDOP)
                dop_values['hdop'] = float(parsed.HDOP)
                dop_values['vdop'] = float(parsed.VDOP)

            # 2. Wyciągamy Satelity z GSV
            if "GSV" in parsed.identity:
                sats_visible[parsed.identity[:2]] = parsed.numSV

            # 3. Pozycja i jakość z GGA/GNS
            if parsed.identity in ["GGA", "GNGGA", "GNS", "GNGNS"]:
                if parsed.lat and parsed.lat != 0:
                    q = 0
                    if parsed.identity in ["GNS", "GNGNS"]:
                        q = 4 if 'R' in parsed.posMode else 5 if 'F' in parsed.posMode else 1
                    else:
                        q = parsed.quality
                    
                    real_sv = sum(sats_visible.values()) if sats_visible else parsed.numSV
                    h_norm = (parsed.alt + parsed.sep) - geoid.get_n(parsed.lat, parsed.lon)
                    x, y = tr.transform(parsed.lon, parsed.lat)
                    
                    led.off()
                    if q == 4: led.on()
                    elif q == 5: led.blink(0.1, 0.1)
                    else: led.blink(1.0, 1.0)
                    
                    st_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                    current_data = {
                        'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h_norm, 
                        'q_txt': st_txt, 'sv': real_sv, 'pdop': dop_values['pdop']
                    }
                    
                    if not is_measuring:
                        print(f"[{time.strftime('%H:%M:%S')}] SV:{real_sv:02} | PDOP:{dop_values['pdop']:.1f} | {st_txt:6} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m ", end='\r')
except KeyboardInterrupt: pass
finally: led.off(); buzzer.off(); ser.close()
