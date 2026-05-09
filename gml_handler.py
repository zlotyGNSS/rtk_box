# gml_handler.py - v33.3 (Zsynchronizowany)
from geo_math import GeoMath

class GMLHandler:
    def __init__(self, filename):
        self.filename = filename
        # Cel: Wybranowo
        self.target_lat = 52.8439534
        self.target_lon = 17.7554311

    def calculate_distance(self, lat, lon):
        """Ta nazwa musi być identyczna z tą w main.py!"""
        return GeoMath.calculate_distance(lat, lon, self.target_lat, self.target_lon)
