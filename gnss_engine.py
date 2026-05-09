# gnss_engine.py
import socket, base64, time, threading, pynmeagps
import config

class GNSSManager:
    def __init__(self, serial_conn):
        self.ser = serial_conn
        self.reader = pynmeagps.NMEAReader(self.ser)
        # Włączamy statystyki satelitów (GSV) i precyzji (GSA)
        self.ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x03\x01\x2a\x10') 
        self.ser.write(b'\xb5\x62\x06\x01\x03\x00\xf0\x02\x01\x26\x0c')

    def start_ntrip(self, state):
        threading.Thread(target=self._ntrip_loop, args=(state,), daemon=True).start()

    def _ntrip_loop(self, state):
        auth = base64.b64encode(f"{config.NTRIP_USER}:{config.NTRIP_PASS}".encode()).decode()
        while True:
            try:
                with socket.create_connection((config.NTRIP_HOST, config.NTRIP_PORT), timeout=10) as s:
                    s.sendall(f"GET /{config.NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n".encode())
                    while True:
                        lat, lon = (state['lat'], state['lon']) if state['lat'] else (52.84, 17.72)
                        gga = pynmeagps.NMEAMessage("GP", "GGA", 0, time=time.strftime("%H%M%S", time.gmtime()), 
                                                    lat=lat, NS="N", lon=lon, EW="E", quality=1, numSV=12, alt=100.0, sep=33.0)
                        s.sendall(gga.serialize())
                        d = s.recv(4096)
                        if d: self.ser.write(d)
                        time.sleep(10)
            except: time.sleep(5)
