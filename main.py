# main.py - v33.1 Master Quality (ZlotyGNSS Edition)
import time
from gnss_engine import GNSSEngine
from gml_handler import GMLHandler
import config

class RTK_Orchestrator:
    def __init__(self):
        # Inicjalizacja "Mózgu" (GNSSEngine) i "Inspektora Map" (GMLHandler)
        self.gnss = GNSSEngine()
        self.gml = GMLHandler(config.GML_FILE)
        
    def run(self):
        print(f"--- RTK BOX v33.1 READY ---")
        print(f"Monitoring dystansu do: {config.GML_FILE}")
        
        try:
            while True:
                # Czytamy surowe dane z anteny
                raw, parsed = self.gnss.reader.read()
                
                if parsed:
                    # Pobieramy przetworzone dane (Lon, Lat, Alt, Fix, Satellites, PDOP)
                    lon, lat, alt, fix, sv, pdop = self.gnss.get_data()
                    
                    # Logika GML: Obliczamy dystans do punktu z mapy
                    dist = self.gml.calculate_distance(lat, lon)
                    
                    # Definiujemy status (rozwiązanie błędu NameError)
                    status = "W POBLIŻU" if dist < 100 else "POZA"
                    
                    # WYŚWIETLANIE (Formatowanie Master Quality)
                    # X/Y to tutaj Lon/Lat, H to Alt
                    output = (
                        f"[{status}] "
                        f"X:{lon:.7f} Y:{lat:.7f} H:{alt:.2f}m | "
                        f"Dist: {dist:.2f}m | "
                        f"FIX: {fix} | SV: {sv} | P:{pdop}"
                    )
                    
                    # Wyświetlamy w jednej linii (używając \r, by nie przewijać ekranu bez końca)
                    print(output, end="\r", flush=True)

        except KeyboardInterrupt:
            print("\n\n[STOP] System zatrzymany przez Dyrektora. Do zobaczenia w terenie!")

if __name__ == "__main__":
    orchestrator = RTK_Orchestrator()
    orchestrator.run()
