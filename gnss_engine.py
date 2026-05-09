# gnss_engine.py - v33 Master Quality
import serial
from pynmeagps import NMEAReader
import config

class GNSSEngine:
    def __init__(self):
        # Inicjalizacja portu szeregowego
        self.stream = serial.Serial(config.SERIAL_PORT, config.BAUD, timeout=0.1)
        self.reader = NMEAReader(self.stream)
        
        # Schowek na najnowsze dane
        self.lon = 0.0
        self.lat = 0.0
        self.alt = 0.0
        self.fix = 0
        self.sv = 0
        self.pdop = 99.9

    def get_data(self):
        """Przeszukuje strumień NMEA i aktualizuje parametry"""
        raw, parsed = self.reader.read()
        
        if parsed:
            # Logika czytania pozycji (GGA)
            if parsed.msgID == "GGA":
                self.lat = parsed.lat
                self.lon = parsed.lon
                self.alt = parsed.alt
                self.fix = parsed.quality
                self.sv = parsed.numSV
            
            # Logika czytania jakości satelitów (GSA)
            if parsed.msgID == "GSA":
                self.pdop = parsed.PDOP

        return self.lon, self.lat, self.alt, self.fix, self.sv, self.pdop
