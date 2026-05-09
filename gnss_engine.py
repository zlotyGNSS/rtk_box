# gnss_engine.py - v33.2
import serial, socket, threading, base64, time
import pynmeagps
import config

class GNSSEngine:
    def __init__(self):
        self.ser = serial.Serial(config.SERIAL_PORT, config.BAUD, timeout=0.1)
        self.nmr = pynmeagps.NMEAReader(self.ser)
        self.dop = {'p': 99.9, 'h': 99.9, 'v': 99.9}
        self.sats_visible = {}
        self.current_pos = None

    def start_ntrip(self):
        auth = base64.b64encode(f"{config.NTRIP_USER}:{config.NTRIP_PASS}".encode()).decode()
        def worker():
            while True:
                try:
                    with socket.create_connection((config.NTRIP_HOST, config.NTRIP_PORT), timeout=10) as sock:
                        sock.sendall(f"GET /{config.NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n".encode())
                        while True:
                            # Wysyłaj GGA by VRS wiedział gdzie jesteś
                            l, n = (self.current_pos['lat'], self.current_pos['lon']) if self.current_pos else (52.84, 17.75)
                            gga = pynmeagps.NMEAMessage("GP", "GGA", 0, time=time.strftime("%H%M%S", time.gmtime()), lat=l, NS="N", lon=n, EW="E", quality=1, numSV=12, HDOP=1.0, alt=100.0, altUnit="M", sep=33.0, sepUnit="M")
                            sock.sendall(gga.serialize())
                            d = sock.recv(4096)
                            if d: self.ser.write(d)
                except: time.sleep(5)
        threading.Thread(target=worker, daemon=True).start()

    def update(self):
        (raw, parsed) = self.nmr.read()
        if parsed:
            if "GSA" in parsed.identity:
                self.dop['p'], self.dop['h'], self.dop['v'] = float(parsed.PDOP), float(parsed.HDOP), float(parsed.VDOP)
            if "GSV" in parsed.identity:
                self.sats_visible[parsed.identity[:2]] = parsed.numSV
            
            if parsed.identity in ["GGA", "GNGGA"]:
                q = 4 if getattr(parsed, 'quality', 0) == 4 else 5 if getattr(parsed, 'quality', 0) == 5 else 1
                sv = sum(self.sats_visible.values()) if self.sats_visible else parsed.numSV
                self.current_pos = {
                    'lat': parsed.lat, 'lon': parsed.lon, 
                    'alt': parsed.alt, 'sep': parsed.sep,
                    'q': q, 'sv': sv, 'pdop': self.dop['p'],
                    'hdop': self.dop['h'], 'vdop': self.dop['v']
                }
        return self.current_pos
