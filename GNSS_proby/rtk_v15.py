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
AVERAGING_EPOCHS = 10  # Czas uśredniania (sekundy)

# Piny GPIO
BUTTON_PIN, LED_PIN, BUZZER_PIN = 17, 27, 22

# Dane NTRIP (ASG-EUPOS)
NTRIP_HOST, NTRIP_PORT, NTRIP_MOUNT = "91.198.76.2", 8080, "RTN4G_VRS_RTCM32"
NTRIP_USER, NTRIP_PASS = "kzlotnic", "Bartek1!!"

# --- INICJALIZACJA ---
led = LED(LED_PIN)
buzzer = Buzzer(BUZZER_PIN)
current_data = None  # Bufor aktualnej sekundy
is_measuring = False 
point_counter = 0

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

# --- LOGIKA POMIARU PRECYZYJNEGO ---
def handle_button():
    global is_measuring, current_data
    if is_measuring or current_data is None: return

    # BLOKADA: Sprawdzamy czy jest FIXED (quality 4)
    if current_data['q'] != 4:
        print(f"\n[BŁĄD] Brak statusu FIXED! Obecny status: {current_data['status']}")
        buzzer.beep(on_time=1.0, n=1) # Długi dźwięk błędu
        return

    # Jeśli jest FIXED, startujemy uśrednianie
    threading.Thread(target=measure_with_averaging).start()

def measure_with_averaging():
    global is_measuring, point_counter, current_data, LOG_FILE
    is_measuring = True
    samples = []
    
    print(f"\n[POMIAR] Rozpoczynam uśrednianie punktu nr {point_counter + 1}...")
    
    for i in range(AVERAGING_EPOCHS):
        if current_data and current_data['q'] == 4:
            samples.append(current_data)
            buzzer.beep(on_time=0.05, off_time=0.05, n=1) # "Tyknięcie" sekundy
            # Pasek postępu w konsoli
            progress = i + 1
            print(f"\rPobieranie epok: [{'#' * progress}{'.' * (AVERAGING_EPOCHS-progress)}] {progress}s", end="")
        else:
            print(f"\n[BŁĄD] Utracono status FIXED podczas pomiaru! Przerywam.")
            buzzer.beep(on_time=0.5, off_time=0.1, n=3)
            is_measuring = False
            return
        time.sleep(1)
        
    if len(samples) == AVERAGING_EPOCHS:
        avg_x = sum(p['x'] for p in samples) / len(samples)
        avg_y = sum(p['y'] for p in samples) / len(samples)
        avg_h = sum(p['h'] for p in samples) / len(samples)
        
        point_counter += 1
        with open(LOG_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([point_counter, time.strftime('%H:%M:%S'), "FIXED", round(avg_x, 3), round(avg_y, 3), round(avg_h, 3)])
        
        buzzer.beep(on_time=0.5, n=1) # Sukces
        print(f"\n[SUKCES] Zapisano punkt {point_counter}: X:{avg_x:.2f} Y:{avg_y:.2f} H:{avg_h:.3f}")
    
    is_measuring = False

def update_led(quality):
    led.off()
    if quality == 4: led.on()            # FIXED - świeci ciągle
    elif quality == 5: led.blink(0.2, 0.2) # FLOAT - miga szybko
    else: led.blink(1.0, 1.0)            # 3D/Brak - miga powoli

def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n")
                sock.sendall(headers.encode())
                while True:
                    l, n = (current_data['lat'], current_data['lon']) if current_data else (52.85, 17.71)
                    gga = pynmeagps.NMEAMessage("GP", "GGA", time=time.strftime("%H%M%S", time.gmtime()), 
                                                lat=l, NS="N", lon=n, EW="E", quality=1, numSV=15, 
                                                HDOP=0.8, alt=100.0, altUnit="M", sep=33.0, sepUnit="M")
                    sock.sendall(gga.serialize())
                    sock.settimeout(1); start = time.time()
                    while time.time() - start < 10:
                        try:
                            d = sock.recv(2048); ser.write(d) if d else None
                        except: break
        except: time.sleep(5)

# --- MAIN ---
LOG_FILE = f"pomiar_v15_{time.strftime('%Y%m%d_%H%M%S')}.csv"
geoid = GeoidManager(GTX_FILE); tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)

btn = Button(BUTTON_PIN); btn.when_pressed = handle_button
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

with open(LOG_FILE, mode='w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["Nr", "Czas", "Status", "X_2177", "Y_2177", "H_Kronsztad"])

print("\n" + "="*70)
print(f"             RTK BOX v15.0 - STRAŻNIK PRECYZJI")
print(f"             POMIAR TYLKO NA STATUSIE FIXED")
print("="*70)

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed and parsed.identity in ["GGA", "GNGGA"]:
            if parsed.lat and parsed.lat != 0:
                h_ell = parsed.alt + parsed.sep 
                h_norm = h_ell - geoid.get_n(parsed.lat, parsed.lon)
                x, y = tr.transform(parsed.lon, parsed.lat)
                q = parsed.quality
                status_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                
                update_led(q)
                
                # Buforowanie danych
                current_data = {
                    'lat': parsed.lat, 'lon': parsed.lon, 
                    'x': x, 'y': y, 'h': h_norm, 
                    'q': q, 'status': status_txt
                }
                
                if not is_measuring:
                    print(f"[{time.strftime('%H:%M:%S')}] SV:{parsed.numSV:02} | {status_txt:6} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m ", end='\r')
except KeyboardInterrupt:
    print("\nWyłączanie systemu.")
finally:
    led.off(); buzzer.off(); ser.close()
