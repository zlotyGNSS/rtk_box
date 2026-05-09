# main.py - v33.3 (Master Height Edition)
import time
from gnss_engine import GNSSEngine
from gml_handler import GMLHandler
from geo_math import GeoMath
import config

class RTK_Orchestrator:
    def __init__(self):
        self.gnss = GNSSEngine()
        self.gml = GMLHandler(config.GML_FILE)
        
    def run(self):
        print(f"--- RTK BOX v33.3 READY (PL-2000 + GTX) ---")
        
        try:
            while True:
                raw, parsed = self.gnss.reader.read()
                
                if parsed:
                    # Pobieramy dane (teraz także 'sep')
                    lon, lat, alt, sep, fix, sv, pdop = self.gnss.get_data()
                    
                    # Pełna transformacja (X, Y, H)
                    x_n, y_e, h_c = GeoMath.wgs84_to_2000_full(lat, lon, alt, sep)
                    
                    dist = self.gml.calculate_distance(lat, lon)
                    status = "W POBLIŻU" if dist < 100 else "POZA"
                    
                    # WYŚWIETLANIE (Z pełną wysokością)
                    output = (
                        f"[{status}] "
                        f"X:{x_n:.3f} Y:{y_e:.3f} H:{h_c:.3f}m | "
                        f"Dist: {dist:.2f}m | FIX:{fix} | SV:{sv} | P:{pdop}"
                    )
                    print(output, end="\r", flush=True)

        except KeyboardInterrupt:
            print("\n\n[STOP] System zatrzymany. Do zobaczenia w Wybranowie!")

if __name__ == "__main__":
    RTK_Orchestrator().run()
