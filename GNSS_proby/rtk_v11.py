import serial, socket, threading, base64, time, struct, csv
import numpy as np
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer
from gpiozero import Button # Biblioteka do obsługi przycisków

# --- KONFIGURACJA ---
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
GTX_FILE = 'geoida_PL.gtx'
BUTTON_PIN = 17  # GPIO 17

NTRIP_HOST = "91.198.76.2" 
NTRIP_PORT = 8080
NTRIP_MOUNT = "RTN4G_VRS_RTCM32"
NTRIP_USER = "kzlotnic"
NTRIP_PASS = "Bartek1!!"

# Globalne zmienne do przechowywania ostatniej pozycji
last_valid_data = None
point_counter = 0

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

# Funkcja zapisu punktu (wywoływana przyciskiem)
def save_point():
    global last_valid_data, point_counter, LOG_FILE
    if last_valid_data:
        point_counter += 1
        with open(LOG_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([point_counter] + last_valid_data)
        print(f"\n[ZAPISANO] Punkt nr {point_counter} | X: {last_valid_data[3]} Y: {last_valid_data[4]} H: {last_valid_data[5]}")
    else:
        print("\n[BŁĄD] Nie można zapisać - brak FIXa!")

def ntrip_handler(ser):
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n")
                sock.sendall(headers.encode())
                while True:
                    now = time.strftime("%H%M%S", time.gmtime())
                    # Wysyłamy pozycję do serwera (używamy statycznego Żnina jeśli brak danych)
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
LOG_FILE = f"pomiar_reczny_{time.strftime('%Y%m%d_%H%M%S')}.csv"
geoid = GeoidManager(GTX_FILE)
tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)

# Inicjalizacja przycisku (Pull-Up oznacza, że przycisk zwieramy do masy)
button = Button(BUTTON_PIN)
button.when_pressed = save_point

threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

with open(LOG_FILE, mode='w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["Nr_Punktu", "Czas", "Satelity", "Status", "X_2177", "Y_2177", "H_Kronsztad"])

print("\n" + "="*65)
print(f"             RTK BOX v11 - TRYB POMIARU PRZYCISKIEM")
print(f"             Zapis do: {LOG_FILE}")
print("="*65)
print("Czekaj na FIX i naciśnij przycisk (GPIO 17), aby zapisać punkt.")

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed and parsed.identity in ["GGA", "GNGGA"]:
            if parsed.lat and parsed.lat != 0:
                h_ell = parsed.alt + parsed.sep 
                n = geoid.get_n(parsed.lat, parsed.lon)
                h_norm = h_ell - n
                q = parsed.quality 
                status = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                x, y = tr.transform(parsed.lon, parsed.lat)
                
                # Aktualizujemy "bufor" ostatniej pozycji
                timestamp = time.strftime('%H:%M:%S')
                last_valid_data = [timestamp, parsed.numSV, status, round(x, 3), round(y, 3), round(h_norm, 3), parsed.lat, parsed.lon]
                
                print(f"[{timestamp}] SV:{parsed.numSV:02} | {status:6} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m ", end='\r')
except KeyboardInterrupt:
    print("\n\nKoniec pracy.")
finally:
    ser.close()
