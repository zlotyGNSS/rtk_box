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
# Dane do logowania NTRIP
NTRIP_HOST, NTRIP_PORT, NTRIP_MOUNT = "91.198.76.2", 8080, "RTN4G_VRS_RTCM32"
NTRIP_USER, NTRIP_PASS = "kzlotnic", "Bartek1!!"

# --- ZMIENNE GLOBALNE ---
led = LED(LED_PIN); buzzer = Buzzer(BUZZER_PIN)
current_data = None; is_measuring = False; point_counter = 0
sats_visible = {}
dop = {'p': 99.9, 'h': 99.9, 'v': 99.9} 

class GeoidManager:
    """Klasa obsługująca przeliczenie wysokości elipsoidalnej na ortometryczną (H)."""
    def __init__(self, path):
        try:
            with open(path, 'rb') as f:
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            lats = np.linspace(self.y_min, self.y_min + (self.rows-1)*self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols-1)*self.x_step, self.cols)
            self.interp = RegularGridInterpolator((lats, lons), data, bounds_error=False, fill_value=None)
        except: 
            print("[BŁĄD] Nie znaleziono pliku geoidy!"); self.interp = None
            
    def get_n(self, lat, lon): 
        return float(self.interp((lat, lon))) if self.interp else 0

def handle_button():
    """Obsługa fizycznego przycisku pomiaru."""
    global is_measuring, current_data
    if is_measuring or current_data is None: return
    if current_data['q_txt'] != "FIXED":
        print(f"\n[INFO] Brak FIXED! Aktualny PDOP: {current_data['pdop']:.2f}")
        buzzer.beep(0.3, 0.1, 1); return
    threading.Thread(target=measure).start()

def measure():
    """Proces uśredniania punktu i zapisu do CSV."""
    global is_measuring, point_counter, current_data, LOG_FILE
    is_measuring = True; samples = []
    print(f"\n[POMIAR] Start uśredniania (epoki: {AVERAGING_EPOCHS})...")
    
    for i in range(AVERAGING_EPOCHS):
        if current_data and current_data['q_txt'] == "FIXED":
            samples.append(current_data)
            buzzer.beep(0.05, 0.05, 1)
            print(f"\rEpoka: {i+1}/{AVERAGING_EPOCHS} | SV: {current_data['sv']} | PDOP: {current_data['pdop']:.2f}", end="")
        else:
            print("\n[BŁĄD] Przerwano pomiar - utrata statusu FIXED!"); buzzer.beep(0.5, 0.1, 2)
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
        buzzer.beep(0.5, 0.1, 1)
        print(f"\n[OK] Punkt {point_counter} zapisany pomyślnie.")
    is_measuring = False

def ntrip_handler(ser):
    """Wątek obsługujący połączenie z serwerem poprawek (NTRIP)."""
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    last_gga_time = 0
    
    while True:
        try:
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                sock.sendall(f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n".encode())
                print("[NTRIP] Połączono z casterem!")
                
                while True:
                    # Wysyłaj GGA co 10 sekund (wymagane dla VRS i stabilności sesji)
                    if time.time() - last_gga_time > 10:
                        # Pobierz aktualne dane lub ustaw domyślne dla Żnina (Wybranowo)
                        lat = current_data['lat'] if current_data else 52.84
                        lon = current_data['lon'] if current_data else 17.72
                        qual = 4 if (current_data and current_data['q_txt'] == "FIXED") else 1
                        svs = current_data['sv'] if current_data else 12
                        
                        # Generowanie ramki GGA z aktualną pozycją
                        gga = pynmeagps.NMEAMessage("GP", "GGA", 0, 
                                                    time=time.strftime("%H%M%S", time.gmtime()), 
                                                    lat=lat, NS="N", lon=lon, EW="E", 
                                                    quality=qual, numSV=svs, HDOP=1.0, alt=100.0, 
                                                    altUnit="M", sep=33.0, sepUnit="M")
                        
                        sock.sendall(gga.serialize())
                        last_gga_time = time.time()
                    
                    sock.settimeout(1)
                    try:
                        data_chunk = sock.recv(4096)
                        if data_chunk:
                            ser.write(data_chunk) # Przesłanie poprawki RTCM bezpośrednio do anteny
                    except socket.timeout:
                        continue
        except Exception as e:
            print(f"\n[NTRIP] Błąd połączenia: {e}. Reconnect za 5s...")
            time.sleep(5)

# --- INICJALIZACJA SYSTEMU ---
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
# Włączenie ramek satelitarnych w odbiorniku
ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x03\x01\x2a\x10') # GSV On
ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x02\x01\x26\x0c') # GSA On

geoid = GeoidManager(GTX_FILE)
# Konwerter z GPS (WGS84) na układ geodezyjny PL-2000 Strefa 6
tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)

LOG_FILE = f"pomiar_v30_2_{time.strftime('%Y%m%d_%H%M%S')}.csv"
with open(LOG_FILE, 'w', newline='') as f:
    csv.writer(f).writerow(["Nr", "Czas", "Status", "X", "Y", "H", "PDOP", "HDOP", "VDOP", "SV"])

# Konfiguracja przycisku
btn = Button(BUTTON_PIN)
btn.when_pressed = handle_button

# Uruchomienie NTRIP w tle
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()
nmr = pynmeagps.NMEAReader(ser)

print("="*85)
print("   RTK BOX v30.2 - THE PRECISION TRINITY | GEOPRO PYTHON EDITION")
print("="*85)

try:
    while True:
        (raw, parsed) = nmr.read()
        if parsed:
            # Pobieranie dokładności (DOP)
            if "GSA" in parsed.identity:
                dop['p'], dop['h'], dop['v'] = float(parsed.PDOP), float(parsed.HDOP), float(parsed.VDOP)
            
            # Pobieranie ilości satelitów
            if "GSV" in parsed.identity:
                sats_visible[parsed.identity[:2]] = parsed.numSV

            # Przetwarzanie pozycji (GGA / GNS)
            if parsed.identity in ["GGA", "GNGGA", "GNS", "GNGNS"]:
                if parsed.lat and parsed.lat != 0:
                    # Wykrywanie statusu FIX/FLOAT na podstawie trybu pracy odbiornika
                    q = 4 if ('R' in getattr(parsed, 'posMode', '')) or (getattr(parsed, 'quality', 0) == 4) else 5 if ('F' in getattr(parsed, 'posMode', '')) or (getattr(parsed, 'quality', 0) == 5) else 1
                    
                    sv_sum = sum(sats_visible.values()) if sats_visible else getattr(parsed, 'numSV', 0)
                    
                    # Obliczenie wysokości ortometrycznej (nad poziomem morza)
                    # H = (h_elipsoidalna + separacja_geoidy) - poprawka_z_pliku_GTX
                    h_norm = (parsed.alt + getattr(parsed, 'sep', 0)) - geoid.get_n(parsed.lat, parsed.lon)
                    
                    # Transformacja na metry (Układ 2000)
                    x, y = tr.transform(parsed.lon, parsed.lat)
                    
                    # Kontrola diody LED
                    led.off()
                    if q == 4: led.on()             # Stałe światło = FIXED (można mierzyć)
                    elif q == 5: led.blink(0.1, 0.1) # Szybkie miganie = FLOAT
                    else: led.blink(1.0, 1.0)       # Powolne miganie = BRAK POPRAWEK
                    
                    st_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                    
                    # Aktualizacja danych globalnych dla innych wątków
                    current_data = {
                        'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h_norm, 
                        'q_txt': st_txt, 'sv': sv_sum, 
                        'pdop': dop['p'], 'hdop': dop['h'], 'vdop': dop['v']
                    }
                    
                    if not is_measuring:
                        # Wyświetlanie statusu w jednej linii (efekt odświeżania)
                        print(f"[{time.strftime('%H:%M:%S')}] SV:{sv_sum:02} | P:{dop['p']:.1f} | {st_txt:6} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m ", end='\r')

except KeyboardInterrupt:
    print("\n[INFO] Zamykanie programu...")
finally:
    led.off(); buzzer.off(); ser.close()
