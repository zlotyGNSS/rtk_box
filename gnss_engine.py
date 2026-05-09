# gnss_engine.py - v33.3
import serial
from pynmeagps import NMEAReader
import config

class GNSSEngine:
    def __init__(self):
        self.stream = serial.Serial(config.SERIAL_PORT, config.BAUD, timeout=0.1)
        self.reader = NMEAReader(self.stream)
        # Dodajemy 'sep' do zmiennych początkowych
        self.lon, self.lat, self.alt, self.sep = 0, 0, 0, 0
        self.fix, self.sv, self.pdop = 0, 0, 99.9

    def get_data(self):
        raw, parsed = self.reader.read()
        if parsed:
            if parsed.msgID == "GGA":
                self.lat = parsed.lat
                self.lon = parsed.lon
                self.alt = parsed.alt
                self.sep = parsed.sep # <-- Kluczowe dla wysokości H!
                self.fix = parsed.quality
                self.sv = parsed.numSV
            if parsed.msgID == "GSA":
                self.pdop = parsed.PDOP
        return self.lon, self.lat, self.alt, self.sep, self.fix, self.sv, self.pdop
