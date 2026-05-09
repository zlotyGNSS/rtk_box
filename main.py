# main.py
import serial, time, threading
from gpiozero import Button, LED, Buzzer

# Import naszych "Szefów Działów"
import config
from geo_math import GeodesyExpert
from gml_handler import MapInspector
from gnss_engine import GNSSManager

class RTK_Orchestrator:
    def __init__(self):
        # 1. Zatrudniamy specjalistów (inicjalizacja klocków)
        self.geo = GeodesyExpert(config.GTX_FILE)
        self.mapa = MapInspector(config.GML_FILE)
        self.ser = serial.Serial(config.SERIAL_PORT, config.BAUD, timeout=0.1)
        self.gnss = GNSSManager(self.ser)
        
        self.led = LED(config.LED_PIN)
        self.buzzer = Buzzer(config.BUZZER_PIN)
        self.btn = Button(config.BUTTON_PIN)

        # 2. Wspólny stan mrowiska (Szyna danych)
        self.state = {'lat': None, 'lon': None, 'x': 0, 'y': 0, 'h': 0, 'q': 0, 'dist': 999}

    def run(self):
        print("SYSTEM STARTUJĘ...")
        # Startujemy poprawki NTRIP
        self.gnss.start_ntrip(self.state)
        
        try:
            while True:
                # Dyrektor pyta antenę: "Co słychać?"
                raw, parsed = self.gnss.reader.read()
                
                if parsed and parsed.identity in ["GGA", "GNGGA", "GNS"]:
                    if parsed.lat:
                        # Dyrektor wysyła dane do Eksperta Matematyka
                        x, y, h = self.geo.compute_local_coords(parsed.lon, parsed.lat, parsed.alt, getattr(parsed, 'sep', 0))
                        
                        # Dyrektor wysyła dane do Inspektora Mapy
                        dz, dist = self.mapa.analyze_position(x, y)
                        
                        # Dyrektor aktualizuje stan mrowiska
                        q = getattr(parsed, 'quality', 0)
                        self.state.update({'lat': parsed.lat, 'lon': parsed.lon, 'x': x, 'y': y, 'h': h, 'q': q, 'dist': dist})
                        
                        # Dyrektor zarządza sygnalizacją
                        self._manage_feedback(q, dist)
                        
                        # Raport do konsoli
                        print(f"[{dz}] Dystans: {dist:.2f}m | Status: {q} | H: {h:.3f}   ", end='\r')

        except KeyboardInterrupt:
            self.ser.close()

    def _manage_feedback(self, q, dist):
        # Logika diody i buzzera
        if q == 4: # FIXED
            self.led.on()
            if dist < 0.05: self.buzzer.on()
            else: self.buzzer.off()
        else:
            self.led.blink(0.1, 0.1)
            self.buzzer.off()

if __name__ == "__main__":
    app = RTK_Orchestrator()
    app.run()
