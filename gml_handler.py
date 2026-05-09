# gml_handler.py - v33 Master Quality
import math

class GMLHandler:
    def __init__(self, gml_file):
        self.gml_file = gml_file
        # Współrzędne celu (np. Wybranowo) - wczytane z configu lub na sztywno
        # Dla testu w Żninie używamy Twoich współrzędnych celu:
        self.target_lat = 52.8439534  # Przykładowe Wybranowo
        self.target_lon = 17.7554311

    def calculate_distance(self, lat, lon):
        """Liczy dystans w linii prostej (Haversine formula)"""
        if lat == 0 or lon == 0:
            return 999999.0
            
        R = 6371000  # Promień Ziemi w metrach
        phi1 = math.radians(self.target_lat)
        phi2 = math.radians(lat)
        d_phi = math.radians(lat - self.target_lat)
        d_lambda = math.radians(lon - self.target_lon)

        a = math.sin(d_phi / 2)**2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(d_lambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c
