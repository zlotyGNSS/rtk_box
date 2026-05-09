# main.py - v33.2 (Modular Master Quality)
import time, csv, threading
import numpy as np
from gpiozero import Button, LED, Buzzer
import config
from gnss_engine import GNSSEngine
from gml_handler import GMLHandler
from geo_math import GeoMath

class RTK_Orchestrator:
    def __init__(self):
        self.engine = GNSSEngine()
        self.gml = GMLHandler(config.GML_FILE)
        self.led = LED(config.LED_PIN)
        self.buzzer = Buzzer(config.BUZZER_PIN)
        self.btn = Button(config.BUTTON_PIN)
        self.is_measuring = False
        self.point_counter = 0
        self.log_file = f"pomiar_v33_{time.strftime('%Y%m%d_%H%M%S')}.csv"

    def setup(self):
        self.engine.start_ntrip()
        self.btn.when_pressed = self.handle_measure
        with open(self.log_file, 'w', newline='') as f:
            csv.writer(f).writerow(["Nr", "Czas", "X", "Y", "H", "Sigma_cm", "PDOP", "SV"])
        print("="*85 + "\n   RTK BOX v33.2 - SYSTEM MODUŁOWY (PL-2000 + GEOIDA)\n" + "="*85)

    def handle_measure(self):
        if self.is_measuring or not self.engine.current_pos: return
        if self.engine.current_pos['q'] != 4:
            self.buzzer.beep(0.3, 0.1, 1); return
        threading.Thread(target=self.do_measurement).start()

    def do_measurement(self):
        self.is_measuring = True
        samples = []
        print(f"\n[POMIAR] Punkt {self.point_counter + 1}...")
        for i in range(config.AVERAGING_EPOCHS):
            pos = self.engine.current_pos
            if pos and pos['q'] == 4:
                x, y, h = GeoMath.wgs84_to_2000(pos['lat'], pos['lon'], pos['alt'], pos['sep'])
                samples.append({'x': x, 'y': y, 'h': h})
                self.buzzer.beep(0.05, 0.05, 1)
                curr_std = np.std([s['x'] for s in samples]) * 100 if len(samples) > 1 else 0
                print(f"\rPostęp: {i+1}/{config.AVERAGING_EPOCHS}s | Sigma: {curr_std:.1f} cm", end="")
            time.sleep(1)
        
        if len(samples) == config.AVERAGING_EPOCHS:
            self.point_counter += 1
            avg_x = np.mean([s['x'] for s in samples])
            avg_y = np.mean([s['y'] for s in samples])
            avg_h = np.mean([s['h'] for s in samples])
            std = np.std([s['x'] for s in samples]) * 100
            with open(self.log_file, 'a', newline='') as f:
                csv.writer(f).writerow([self.point_counter, time.strftime('%H:%M:%S'), round(avg_x, 3), round(avg_y, 3), round(avg_h, 3), round(std, 2), self.engine.current_pos['pdop'], self.engine.current_pos['sv']])
            self.buzzer.beep(0.5, 0.1, 1)
            print(f"\n[ZAPISANO] X:{avg_x:.3f} Y:{avg_y:.3f}")
        self.is_measuring = False

    def run(self):
        self.setup()
        try:
            while True:
                pos = self.engine.update()
                if pos and not self.is_measuring:
                    # Transformacja do wyświetlania
                    x, y, h = GeoMath.wgs84_to_2000(pos['lat'], pos['lon'], pos['alt'], pos['sep'])
                    dist = self.gml.get_distance(pos['lat'], pos['lon'])
                    st_txt = "FIXED" if pos['q'] == 4 else "FLOAT" if pos['q'] == 5 else "3D"
                    
                    # Kontrola diody
                    self.led.off()
                    if pos['q'] == 4: self.led.on()
                    elif pos['q'] == 5: self.led.blink(0.1, 0.1)

                    print(f"[{time.strftime('%H:%M:%S')}] SV:{pos['sv']:02} | P:{pos['pdop']:.1f} | {st_txt:6} | X:{x:.3f} Y:{y:.3f} | Dist:{dist:.2f}m", end='\r')
        except KeyboardInterrupt: pass

if __name__ == "__main__":
    RTK_Orchestrator().run()
