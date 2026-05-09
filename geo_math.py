# geo_math.py - v33.3 (PL-2000 + Korekta Geoidy)
import math
import struct
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer
import config

class GeoidManager:
    def __init__(self, path):
        try:
            with open(path, 'rb') as f:
                # Czytanie nagłówka GTX
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            # Wczytanie siatki poprawek
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            lats = np.linspace(self.y_min, self.y_min + (self.rows-1)*self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols-1)*self.x_step, self.cols)
            self.interp = RegularGridInterpolator((lats, lons), data, bounds_error=False, fill_value=None)
            print(f"[OK] Geoida wczytana poprawnie: {path}")
        except Exception as e:
            print(f"[BŁĄD] Nie udało się wczytać geoidy: {e}")
            self.interp = None

    def get_n(self, lat, lon):
        """Pobiera poprawkę N (undulacja geoidy) dla danej pozycji"""
        if self.interp:
            return float(self.interp((lat, lon)))
        return 0.0

class GeoMath:
    # Inicjalizacja Transformer-a (EPSG:2177 dla Żnina)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
    # Inicjalizacja Geoidy (używa ścieżki z config.py)
    geoid = GeoidManager(config.GTX_FILE)

    @staticmethod
    def wgs84_to_2000_full(lat, lon, alt, sep):
        """Pełne przeliczenie: X, Y (PL-2000) oraz H (Poprawione o GTX)"""
        # 1. Transformacja na układ płaski PL-2000
        y_east, x_north = GeoMath.transformer.transform(lon, lat)
        
        # 2. Korekta wysokości (z elipsoidalnej na normalną)
        # H_norm = (H_elip + Sep_NMEA) - N_geoidy
        n_val = GeoMath.geoid.get_n(lat, lon)
        h_corrected = (alt + sep) - n_val
        
        return round(x_north, 3), round(y_east, 3), round(h_corrected, 3)

    @staticmethod
    def calculate_distance(lat1, lon1, lat2, lon2):
        """Klasyczny dystans w metrach dla GML"""
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi, dlam = math.radians(lat2-lat1), math.radians(lon2-lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
