# =================================================================================
# RTK BOX v30.2 - WERSJA EDUKACYJNA Z PEŁNYM OPISEM (KOMENTARZ 6.0)
# =================================================================================

import serial, socket, threading, base64, time, struct, csv
import numpy as np
import pynmeagps
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer
from gpiozero import Button, LED, Buzzer

# --- SEKCJA KONFIGURACJI ---
SERIAL_PORT = '/dev/ttyACM0'  # Port, pod którym "widać" Twoją antenę GNSS (USB)
BAUD = 115200                 # Prędkość komunikacji - standard dla szybkich odbiorników
GTX_FILE = 'geoida_PL.gtx'    # Plik z modelem różnic między elipsoidą a poziomem morza
AVERAGING_EPOCHS = 10         # Ile sekund (odczytów) program ma uśredniać dla jednego punktu

# Piny dla Raspberry Pi (GPIO)
BUTTON_PIN, LED_PIN, BUZZER_PIN = 17, 27, 22

# Dane serwera poprawek (Castera)
NTRIP_HOST = "91.198.76.2"           # Adres IP serwera (np. ASG-EUPOS)
NTRIP_PORT = 8080                    # Port serwera
NTRIP_MOUNT = "RTN4G_VRS_RTCM32"     # Nazwa strumienia poprawek (VRS = Stacja Wirtualna)
NTRIP_USER, NTRIP_PASS = "kzlotnic", "Bartek1!!" # Twoje dane dostępowe

# --- ZMIENNE GLOBALNE (Magazyn danych w pamięci RAM) ---
led = LED(LED_PIN)
buzzer = Buzzer(BUZZER_PIN)
current_data = None    # Tu zawsze ląduje ostatni "świeży" odczyt z anteny
is_measuring = False   # Flaga - czy w tej sekundzie trwa właśnie uśrednianie pomiaru
point_counter = 0      # Licznik zapisanych punktów
sats_visible = {}      # Słownik przechowujący ilość satelitów z różnych systemów (GPS/GAL/GLO)
dop = {'p': 99.9, 'h': 99.9, 'v': 99.9} # Parametry dokładności (DOP) - im niższe, tym lepiej

# =================================================================================
# KLASA: GeoidManager - Zamiana wysokości elipsoidalnej na geodezyjną
# =================================================================================
class GeoidManager:
    """
    Antena GNSS podaje wysokość nad elipsoidą (matematycznym jajkiem). 
    Geodeta potrzebuje wysokości nad poziomem morza (H). Ta klasa czyta plik .gtx 
    i wylicza 'falowanie geoidy' dla Twojej pozycji.
    """
    def __init__(self, path):
        try:
            with open(path, 'rb') as f:
                # Czytamy nagłówek pliku binarnego GTX (wymiary siatki, skoki itp.)
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            
            # Wczytujemy dane siatki poprawek
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            
            # Tworzymy osie współrzędnych dla interpolatora
            lats = np.linspace(self.y_min, self.y_min + (self.rows-1)*self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols-1)*self.x_step, self.cols)
            
            # Interpolator pozwala wyliczyć poprawkę nawet jeśli nie stoisz idealnie w węźle siatki
            self.interp = RegularGridInterpolator((lats, lons), data, bounds_error=False, fill_value=None)
        except: 
            print("[BŁĄD] Brak pliku geoidy! Wysokości będą błędne."); self.interp = None
            
    def get_n(self, lat, lon): 
        # Zwraca wartość poprawki N (odstęp geoidy od elipsoidy) w metrach
        return float(self.interp((lat, lon))) if self.interp else 0

# =================================================================================
# FUNKCJA: measure - Logika uśredniania pomiaru
# =================================================================================
def measure():
    """
    Zasada: Geodeta nie mierzy 'strzałem' jednej sekundy. 
    Program zbiera 10 epok (sekund) i wyciąga z nich średnią arytmetyczną.
    """
    global is_measuring, point_counter, current_data, LOG_FILE
    is_measuring = True
    samples = []
    
    print(f"\n[POMIAR] Rozpoczęto zbieranie danych dla punktu nr {point_counter + 1}...")
    
    for i in range(AVERAGING_EPOCHS):
        # Sprawdzamy, czy w każdej sekundzie mamy status FIXED
        if current_data and current_data['q_txt'] == "FIXED":
            samples.append(current_data)
            buzzer.beep(0.05, 0.05, 1) # Krótkie 'piknięcie' co sekundę pomiaru
            print(f"\rPostęp: {i+1}/{AVERAGING_EPOCHS}s | PDOP: {current_data['pdop']:.2f}", end="")
        else:
            print("\n[BŁĄD] Przerwano! Utrata FIX w trakcie pomiaru."); buzzer.beep(0.5, 0.1, 2)
            is_measuring = False; return
        time.sleep(1) # Czekamy na kolejną sekundę/epokę
    
    # Jeśli zebraliśmy komplet 10 sekund - liczymy średnią
    if len(samples) == AVERAGING_EPOCHS:
        avg = {k: sum(p[k] for p in samples)/len(samples) for k in ['x', 'y', 'h', 'pdop', 'hdop', 'vdop']}
        point_counter += 1
        
        # Zapisujemy wynik do pliku CSV
        with open(LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([point_counter, time.strftime('%H:%M:%S'), "FIXED", 
                                    round(avg['x'], 3), round(avg['y'], 3), round(avg['h'], 3), 
                                    round(avg['pdop'], 2), round(avg['hdop'], 2), round(avg['vdop'], 2), 
                                    current_data['sv']])
        buzzer.beep(0.4, 0.1, 1) # Dłuższy sygnał - koniec pomiaru
        print(f"\n[OK] Punkt {point_counter} zapisany pomyślnie.")
        
    is_measuring = False

# =================================================================================
# FUNKCJA: ntrip_handler - Klient poprawek RTK
# =================================================================================
def ntrip_handler(ser):
    """
    Łączy się z internetem, wysyła Twoją pozycję do serwera (GGA), 
    odbiera poprawki RTCM i przesyła je kablem do anteny.
    """
    # Kodowanie loginu i hasła do formatu zrozumiałe dla serwerów (Base64)
    auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
    last_gga_time = 0
    
    while True:
        try:
            # Tworzymy połączenie sieciowe (Socket)
            with socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10) as sock:
                # Wysyłamy żądanie o strumień poprawek
                request = f"GET /{NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n"
                sock.sendall(request.encode())
                
                while True:
                    # Serwery VRS potrzebują Twojej pozycji co 10 sekund, by wiedzieć gdzie 'jesteś'
                    if time.time() - last_gga_time > 10:
                        lat = current_data['lat'] if current_data else 52.84
                        lon = current_data['lon'] if current_data else 17.72
                        
                        # Generujemy ramkę NMEA GGA
                        gga = pynmeagps.NMEAMessage("GP", "GGA", 0, 
                                                    time=time.strftime("%H%M%S", time.gmtime()), 
                                                    lat=lat, NS="N", lon=lon, EW="E", quality=1, 
                                                    numSV=12, HDOP=1.0, alt=100.0)
                        sock.sendall(gga.serialize())
                        last_gga_time = time.time()
                    
                    # Odbieramy poprawki z serwera i wysyłamy je portem szeregowym do anteny
                    data_chunk = sock.recv(4096)
                    if data_chunk:
                        ser.write(data_chunk)
        except:
            time.sleep(5) # W razie błędu sieci, czekaj 5s i próbuj ponownie

# =================================================================================
# PĘTLA GŁÓWNA PROGRAMU
# =================================================================================

# 1. Start portu szeregowego
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)

# 2. Inicjalizacja narzędzi geodezyjnych
geoid = GeoidManager(GTX_FILE)
# Transformer: zamienia stopnie (lat, lon) na metry w polskim układzie PL-2000 (EPSG:2177)
tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)

# 3. Przygotowanie pliku wynikowego z nagłówkiem
LOG_FILE = f"pomiar_v30_2_{time.strftime('%Y%m%d_%H%M%S')}.csv"
with open(LOG_FILE, 'w', newline='') as f:
    csv.writer(f).writerow(["Nr", "Czas", "Status", "X", "Y", "H", "PDOP", "HDOP", "VDOP", "SV"])

# 4. Uruchomienie wątku NTRIP (pracuje "obok" głównego programu)
threading.Thread(target=ntrip_handler, args=(ser,), daemon=True).start()

# 5. Start czytnika NMEA
nmr = pynmeagps.NMEAReader(ser)

# 6. Fizyczny przycisk - po naciśnięciu wywołaj funkcję handle_button
btn = Button(BUTTON_PIN)
btn.when_pressed = lambda: threading.Thread(target=measure).start() if not is_measuring else None

print("SYSTEM GOTOWY. CZEKAM NA POZYCJĘ...")

try:
    while True:
        # Czytamy dane "wypluwane" przez antenę
        (raw, parsed) = nmr.read()
        if parsed:
            # GSA - ramka z parametrami dokładności (DOP) i listą satelitów
            if "GSA" in parsed.identity:
                dop['p'], dop['h'], dop['v'] = float(parsed.PDOP), float(parsed.HDOP), float(parsed.VDOP)
            
            # GSV - ramka z informacją o widocznych satelitach (ile ich jest na niebie)
            if "GSV" in parsed.identity:
                sats_visible[parsed.identity[:2]] = parsed.numSV

            # GGA / GNS - najważniejsze ramki z pozycją geograficzną
            if parsed.identity in ["GGA", "GNGGA", "GNS", "GNGNS"]:
                if parsed.lat and parsed.lat != 0:
                    
                    # Logika wykrywania statusu: 4 = FIXED (Precyzja cm), 5 = FLOAT (Precyzja dm)
                    # Sprawdzamy atrybut 'quality' w GGA lub 'posMode' w ramce GNS
                    q = 4 if (getattr(parsed, 'quality', 0) == 4 or 'R' in getattr(parsed, 'posMode', '')) else 5 if (getattr(parsed, 'quality', 0) == 5 or 'F' in getattr(parsed, 'posMode', '')) else 1
                    
                    # Obliczamy wysokość geodezyjną H (ortometryczną)
                    # (Wysokość elipsoidalna + separacja) - poprawka z geoidy .gtx
                    h_norm = (parsed.alt + getattr(parsed, 'sep', 0)) - geoid.get_n(parsed.lat, parsed.lon)
                    
                    # Transformacja na układ 2000 (metry)
                    x, y = tr.transform(parsed.lon, parsed.lat)
                    
                    # Kontrola diody LED - geodeta musi widzieć status bez patrzenia w ekran
                    if q == 4: led.on()             # Stałe światło - mierzymy!
                    elif q == 5: led.blink(0.1, 0.1) # Szybkie miganie - czekaj na FIX
                    else: led.blink(1.0, 1.0)       # Wolne miganie - brak poprawek/internetu
                    
                    # Budujemy słownik z aktualnymi danymi dla funkcji measure i wyświetlacza
                    st_txt = "FIXED" if q == 4 else "FLOAT" if q == 5 else "3D"
                    sv_sum = sum(sats_visible.values()) if sats_visible else getattr(parsed, 'numSV', 0)
                    
                    current_data = {
                        'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h_norm, 
                        'q_txt': st_txt, 'sv': sv_sum, 
                        'pdop': dop['p'], 'hdop': dop['h'], 'vdop': dop['v']
                    }
                    
                    # Jeśli nie mierzymy, wyświetlaj status na bieżąco w konsoli
                    if not is_measuring:
                        print(f"[{time.strftime('%H:%M:%S')}] SV:{sv_sum:02} | P:{dop['p']:.1f} | {st_txt:6} | X:{x:.2f} Y:{y:.2f} | H:{h_norm:.3f}m ", end='\r')

except KeyboardInterrupt:
    pass # Wyjście z programu po Ctrl+C
finally:
    # Bezpieczne zamknięcie portów i wyłączenie LED
    led.off(); ser.close()
