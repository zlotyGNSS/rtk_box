# main.py
import serial, time, threading, csv, numpy as np
from gpiozero import Button, LED, Buzzer
import config
from geo_math import GeodesyExpert
from gml_handler import MapInspector
from gnss_engine import GNSSManager

class RTK_Orchestrator:
    def __init__(self):
        self.geo = GeodesyExpert(config.GTX_FILE)
        self.mapa = MapInspector(config.GML_FILE)
        self.ser = serial.Serial(config.SERIAL_PORT, config.BAUD, timeout=0.1)
        self.gnss = GNSSManager(self.ser)
        self.led, self.buzzer = LED(config.LED_PIN), Buzzer(config.BUZZER_PIN)
        self.btn = Button(config.BUTTON_PIN)
        self.btn.when_pressed = self.start_measurement

        self.state = {'lat': None, 'lon': None, 'x': 0, 'y': 0, 'h': 0, 'q': 0, 'dist': 999, 'is_measuring': False, 'sv': 0}
        self.dop = {'p': 99.9, 'h': 99.9, 'v': 99.9}
        self.sats = {}

    def start_measurement(self):
        if self.state['q'] == 4 and not self.state['is_measuring']:
            threading.Thread(target=self.measure_logic).start()
        elif self.state['q'] != 4:
            print("\n[BLOKADA] Brak statusu FIXED!"); self.buzzer.beep(0.3, 0.1, 1)

    def measure_logic(self):
        self.state['is_measuring'] = True
        samples = []
        print(f"\n[POMIAR] Zbieranie {config.AVERAGING_EPOCHS} epok...")
        
        for i in range(config.AVERAGING_EPOCHS):
            if self.state['q'] == 4:
                samples.append({'x': self.state['x'], 'y': self.state['y'], 'h': self.state['h']})
                self.buzzer.beep(0.05, 0.05, 1)
                # Wyliczamy bieżącą Sigmę (stabilność)
                cur_sigma = np.std([s['x'] for s in samples]) * 100 if len(samples) > 1 else 0
                print(f"\rPostęp: {i+1}s | Sigma: {cur_sigma:.1f} cm", end="")
                time.sleep(1)
            else:
                print("\n[BŁĄD] Utrata FIX!"); self.state['is_measuring'] = False; return

        # Obliczenia końcowe
        avg_x = np.mean([s['x'] for s in samples])
        avg_y = np.mean([s['y'] for s in samples])
        avg_h = np.mean([s['h'] for s in samples])
        sigma_final = np.sqrt(np.std([s['x'] for s in samples])**2 + np.std([s['y'] for s in samples])**2) * 100
        
        # Zapis do pliku
        log_name = f"pomiar_v33_{time.strftime('%Y%m%d')}.csv"
        with open(log_name, 'a', newline='') as f:
            csv.writer(f).writerow([time.strftime('%H:%M:%S'), round(avg_x, 3), round(avg_y, 3), round(avg_h, 3), round(sigma_final, 2)])
        
        quality = "IDEALNY" if sigma_final < config.SIGMA_LIMIT else "NIEPEWNY"
        print(f"\n[ZAPISANO] Sigma: {sigma_final:.1f} cm | Jakość: {quality}")
        self.buzzer.beep(0.5, 0.1, 1)
        self.state['is_measuring'] = False

    def run(self):
        self.gnss.start_ntrip(self.state)
        print("RTK BOX v33 READY.")
        while True:
            raw, parsed = self.gnss.reader.read()
            if parsed:
                if "GSA" in parsed.identity:
                    self.dop['p'], self.dop['h'], self.dop['v'] = float(parsed.PDOP), float(parsed.HDOP), float(parsed.VDOP)
                if "GSV" in parsed.identity:
                    self.sats[parsed.identity[:2]] = parsed.numSV
                if parsed.identity in ["GGA", "GNGGA", "GNS"]:
                    if parsed.lat:
                        x, y, h = self.geo.process(parsed.lon, parsed.lat, parsed.alt, getattr(parsed, 'sep', 0))
                        dz, dist = self.mapa.analyze(x, y)
                        q = getattr(parsed, 'quality', 0)
                        sv = sum(self.sats.values())
                        self.state.update({'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h, 'q': q, 'dist': dist, 'sv': sv})
                        
                        # Kontrola LED
                        if q == 4: self.led.on()
                        elif q == 5: self.led.blink(0.1, 0.1)
                        else: self.led.off()

                        if not self.state['is_measuring']:
                            print(f"[{dz}] Dist: {dist:.2f}m | FIX: {q} | SV: {sv} | P:{self.dop['p']:.1f}   ", end='\r')

if __name__ == "__main__":
    RTK_Orchestrator().run()
