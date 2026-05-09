import serial, socket, threading, base64, time, struct, csv
import numpy as np
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer
from gpiozero import Button, LED, Buzzer # Nowe zabawki

# --- KONFIGURACJA ---
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
GTX_FILE = 'geoida_PL.gtx'

# Piny GPIO
BUTTON_PIN = 17 
LED_PIN = 27    
BUZZER_PIN = 22 

NTRIP_HOST = "91.198.76.2" 
NTRIP_PORT = 8080
NTRIP_MOUNT = "RTN4G_VRS_RTCM32"
NTRIP_USER = "kzlotnic"
NTRIP_PASS = "Bartek1!!"

# --- INICJALIZACJA HARDWARE ---
led = LED(LED_PIN)
buzzer = Buzzer(BUZZER_PIN)
last_valid_data = None
point_counter = 0
current_quality = 0 # Przechowujemy status, żeby nie zmieniać migania LED w kółko

# --- SILNIK GEOIDY ---
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

# --- FUNKCJE SYGNAŁÓW I ZAPISU ---
def save_point():
    global last_valid_data, point_counter, LOG_FILE
    if last_valid_data:
        point_counter += 1
        with open(LOG_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([point_counter] + last_valid_data)
        
        # Sygnał dźwiękowy potwierdzenia zapisu (krótkie piknięcie)
        buzzer.beep(on_time=0.1, off_time=0.05, n=1)
        print(f"\n[ZAPISANO] Punkt nr {point_counter}")
    else:
        # Sygnał błędu (długie niskie "buuu")
        buzzer.beep(on_time=1.0, n=1)
        print("\n[BŁĄD] Brak danych do zapisu!")

def update_led_status(quality):
    global current_quality
    if quality == current_quality: return
    current_quality = quality
    
    led.prefix_blink = False # Reset
    if quality == 4: # FIXED
        led.on() # Świeci ciągle
        # Opcjonalnie: krótki sygnał dźwiękowy, że wskoczył FIX!
        buzzer.beep(on_time=0.05, off_time=0.05, n=2)
    elif quality == 5: # FLOAT
        led.blink(on_time=0.2, off_time=0.2) # Miga szybko
    else: # 3D / Brak fixa
        led.blink(on_time=1.0, off_time=1.0) # Miga powoli

# --- NTRIP ---
def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n")
                sock.sendall(headers.encode())
                while True:
                    now = time.strftime("%H%M%S", time.gmtime())
                    lat_n = last_valid_data[6] if last_valid_data else 52.85
                    lon_n = last_valid_data[7] if last_valid_data else 17.71
                    gga = pynmeagps.NMEAMessage("GP", "GGA", time=now, lat=lat_n, NS="N", lon=lon_n, EW="E", quality=1, numSV=12, HDOP=1.0, alt=100.0, altUnit="M", sep=33.0, sepUnit="M")
                    sock.sendall(gga.serialize())
                    sock.settimeout(1); start = time.time()
                    while time.time() - start < 10:
                        try:
                            data = sock.recv(2048)
                            if not data: break
                            ser.write(data)
                        except socket.timeout: continue
        except: time.sleep(5)

# --- START ---
LOG_FILE = f"pomiar_headless_{time.strftime('%Y%m%d_%H%M%S')}.csv"
geoid = GeoidManager(GTX_FILE); tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)

button = Button(BUTTON_PIN)
button.when_pressed = save_point

threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

with open(LOG_FILE, mode='w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["Nr_Punktu", "Czas", "Satelity", "Status", "X_2177", "Y_2177", "H_Kronsztad"])

print("RTK BOX v12 READY. System powiadomień aktywny.")

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed and parsed.identity in ["GGA", "GNGGA"]:
            if parsed.lat and parsed.lat != 0:
                h_ell = parsed.alt + parsed.sep 
                h_norm = h_ell - geoid.get_n(parsed.lat, parsed.lon)
                q = parsed.quality 
                x, y = tr.transform(parsed.lon, parsed.lat)
                
                # Aktualizacja LED
                update_led_status(q)
                
                status_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                last_valid_data = [time.strftime('%H:%M:%S'), parsed.numSV, status_txt, round(x, 3), round(y, 3), round(h_norm, 3), parsed.lat, parsed.lon]
                
                print(f"[{last_valid_data[0]}] SV:{parsed.numSV:02} | {status_txt:6} | H:{h_norm:.3f}m ", end='\r')
except KeyboardInterrupt:
    print("\nWyłączanie.")
finally:
    led.off(); ser.close()
