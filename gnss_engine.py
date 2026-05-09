# gnss_engine.py
import socket, base64, time, threading, pynmeagps
import config

class GNSSManager:
    def __init__(self, serial_conn):
        self.ser = serial_conn
        self.reader = pynmeagps.NMEAReader(self.ser)

    def start_ntrip(self, state_ref):
        # Wątek NTRIP pracujący w tle
        threading.Thread(target=self._ntrip_loop, args=(state_ref,), daemon=True).start()

    def _ntrip_loop(self, state):
        auth = base64.b64encode(f"{config.NTRIP_USER}:{config.NTRIP_PASS}".encode()).decode()
        last_gga = 0
        while True:
            try:
                with socket.create_connection((config.NTRIP_HOST, config.NTRIP_PORT), timeout=10) as sock:
                    sock.sendall(f"GET /{config.NTRIP_MOUNT} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n".encode())
                    while True:
                        if time.time() - last_gga > 10:
                            lat = state['lat'] if state['lat'] else 52.84
                            lon = state['lon'] if state['lon'] else 17.72
                            gga = pynmeagps.NMEAMessage("GP", "GGA", 0, time=time.strftime("%H%M%S", time.gmtime()), 
                                                        lat=lat, NS="N", lon=lon, EW="E", quality=1, numSV=12, alt=100.0)
                            sock.sendall(gga.serialize())
                            last_gga = time.time()
                        data = sock.recv(4096)
                        if data: self.ser.write(data)
            except: time.sleep(5)
