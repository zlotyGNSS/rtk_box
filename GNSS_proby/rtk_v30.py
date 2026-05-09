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
dop = {'p': 99.9, 'h': 99.9, 'v': 99.9} 

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
        print(f"\n[INFO] Czekaj na FIXED! PDOP: {current_data['pdop']:.2f}"); buzzer.beep(0.3, 0.1, 1); return
    threading.Thread(target=measure).start()

def measure():
    global is_measuring, point_counter, current_data, LOG_FILE
    is_measuring = True; samples = []
    print(f"\n[POMIAR] Uśrednianie punktu {point_counter + 1}...")
    for i in range(AVERAGING_EPOCHS):
        if current_data and current_data['q_txt'] == "FIXED":
            samples.append(current_data); buzzer.beep(0.05, 0.05, 1)
            print(f"\rPostęp: {i+1}/{AVERAGING_EPOCHS}s | PDOP: {current_data['pdop']:.2f}", end="")
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
        buzzer.beep(0.5, 0.1, 1); print(f"\n[OK] Zapisano pkt {point_counter} (PDOP: {avg['pdop']:.2f})")
    is_measuring = False

def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                sock.sendall(f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n".encode())
                while True:
                    l, n = (current_data['lat'], current_data['lon']) if current_data else (52.85, 17.71)
                    gga = pynmeagps.NMEAMessage("GP", "GGA", 0, time=time.strftime("%H%M%S", time.gmtime()), lat=l, NS="N", lon=n, EW="E", quality=1
