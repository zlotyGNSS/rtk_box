# gml_handler.py - v33.2
from geo_math import GeoMath

class GMLHandler:
    def __init__(self, filename):
        self.filename = filename
        # Przykładowy punkt Wybranowo z Twojego GML
        self.target_lat = 52.8439534
        self.target_lon = 17.7554311

    def get_distance(self, lat, lon):
        return GeoMath.calculate_distance(lat, lon, self.target_lat, self.target_lon)
