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

# --- KOMENDY KONFIGURACYJNE UBX (ZED-F9P) ---
# 1. Przełącz na NMEA 4.10 (pozwala na > 12 SV w komunikatach)
CFG_NMEA_V41 = b'\xb5\x62\x06\x17\x14\x00\x00\x41\x00\x02\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x75\x57'
# 2. Włącz wiadomość GNS (Global Navigation Satellite System Fix Data)
CFG_MSG_GNS = b'\xb5\x62\x06\x01\x03\x00\xf0\x0d\x01\x02\x34'
# 3. Włącz wiadomość ZDA (Czas UTC i data) - opcjonalnie
CFG_MSG_ZDA = b'\xb5\x62\x06\x01\x03\x00\xf0\x08\x01\x02\x2f'

# --- INICJALIZACJA ---
led = LED(LED_PIN)
buzzer = Buzzer(BUZZER_PIN)
current_data = None
is_measuring = False 
point_counter = 0

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
        print(f"\n[BLOKADA] Brak FIXED! Status: {current_data['q_txt']}"); buzzer.beep(0.3, 0.1, 1); return
    threading.Thread(target=measure).start()

def measure():
    global is_measuring, point_counter, current_data, LOG_FILE
    is_measuring = True; samples = []
    print(f"\n[POMIAR] Uśrednianie punktu {point_counter + 1}...")
    for i in range(AVERAGING_EPOCHS):
        if current_data and current_data['q_txt'] == "FIXED":
            samples.append(current_data)
            buzzer.beep(0.05, 0.05, 1)
            print(f"\rPostęp: {i+1}/{AVERAGING_EPOCHS}s | SV: {current_data['sv']}", end="")
        else:
            print("\n[BŁĄD] Przerwano - utrata FIX!"); buzzer.beep(0.5, 0.1, 2)
            is_measuring = False; return
        time.sleep(1)
    
    if len(samples) == AVERAGING_EPOCHS:
        avg_x = sum(p['x'] for p in samples) / len(samples)
        avg_y = sum(p['y'] for p in samples) / len(samples)
        avg_h = sum(p['h'] for p in samples) / len(samples)
        point_counter += 1
        with open(LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([point_counter, time.strftime('%H:%M:%S'), "FIXED", round(avg_x, 3), round(avg_y, 3), round(avg_h, 3)])
        buzzer.beep(0.5, 0.1, 1); print(f"\n[OK] Zapisano punkt {point_counter}")
    is_measuring = False

def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                sock.sendall(f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n".encode())
                print("[NTRIP] Połączono! Pobieram poprawki...")
                while True:
                    l, n = (current_data['lat'], current_data['lon']) if current_data else (52.85, 17.71)
                    now = time.strftime("%H%M%S", time.gmtime())
                    gga = pynmeagps.NMEAMessage("GP", "GGA", 0, time=now, lat=l, NS="N", lon=n, EW="E", quality=1, numSV=12, HDOP=1.0, alt=100.0, altUnit="M", sep=33.0, sepUnit="M")
                    sock.sendall(gga.serialize())
                    sock.settimeout(2); d = sock.recv(4096)
                    if d: ser.write(d)
        except Exception as e:
            time.sleep(5)

# --- START ---
geoid = GeoidManager(GTX_FILE); tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)

# WYŚLIJ KONFIGURACJĘ UBX DO MODUŁU
print("[*] Konfiguracja u-bloxa (Odblokowanie SV > 12)...")
ser.write(CFG_NMEA_V41)
time.sleep(0.2)
ser.write(CFG_MSG_GNS)
time.sleep(0.2)
ser.write(CFG_MSG_ZDA)

LOG_FILE = f"pomiar_v19_{time.strftime('%Y%m%d_%H%M%S')}.csv"
btn = Button(BUTTON_PIN); btn.when_pressed = handle_button
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

with open(LOG_FILE, 'w', newline='') as f:
    csv.writer(f).writerow(["Nr", "Czas", "Status", "X", "Y", "H"])

print("="*70 + "\n   RTK BOX v19 - SATELLITE UNCHAINED (>12 SV MODE)\n" + "="*70)

try:
    while True:
        (raw, parsed) = nmr.read()
        # Obsługujemy ramki GNS (nowoczesna) oraz GGA (klasyczna)
        if parsed and parsed.identity in ["GNS", "GNGNS", "GGA", "GNGGA"]:
            if parsed.lat and parsed.lat != 0:
                # Logika ustalania jakości (Quality)
                q = 0
                if parsed.identity in ["GNS", "GNGNS"]:
                    # W GNS sprawdzamy posMode (np. 'RR' oznacza RTK Fixed)
                    q = 4 if 'R' in parsed.posMode else 5 if 'F' in parsed.posMode else 1
                else:
                    q = parsed.quality
                
                # WYCIĄGANIE LICZBY SATELITÓW
                # Jeśli to GNS, pynmeagps ma pole numSV, które sumuje wszystkie konstelacje
                sv_count = parsed.numSV
                
                h_norm = (parsed.alt + parsed.sep) - geoid.get_n(parsed.lat, parsed.lon)
                x, y = tr.transform(parsed.lon, parsed.lat)
                
                # Zarządzanie LED
                led.off()
                if q == 4: led.on()
                elif q == 5: led.blink(0.1, 0.1)
                else: led.blink(1.0, 1.0)
                
                st_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                current_data = {
                    'lat': parsed.lat, 'lon': parsed.lon, 
                    'x': x, 'y': y, 'h': h_norm, 
                    'q_txt': st_txt, 'sv': sv_count
                }
                
                if not is_measuring:
                    print(f"[{time.strftime('%H:%M:%S')}] {parsed.identity:5} | SV:{sv_count:02} | {st_txt:6} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m ", end='\r')
except KeyboardInterrupt: pass
finally: led.off(); buzzer.off(); ser.close()
