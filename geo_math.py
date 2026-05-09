# geo_math.py - v33.2 (PL-2000 + Geoida)
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
                h = struct.unpack('>ddddii', f.read(40))
            self.y_min, self.x_min, self.y_step, self.x_step, self.rows, self.cols = h
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((self.rows, self.cols))
            lats = np.linspace(self.y_min, self.y_min + (self.rows-1)*self.y_step, self.rows)
            lons = np.linspace(self.x_min, self.x_min + (self.cols-1)*self.x_step, self.cols)
            self.interp = RegularGridInterpolator((lats, lons), data, bounds_error=False, fill_value=None)
        except: self.interp = None
    def get_n(self, lat, lon): return float(self.interp((lat, lon))) if self.interp else 0

class GeoMath:
    # Inicjalizacja transformera (EPSG:2177 dla Żnina - Strefa 6)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
    geoid = GeoidManager(config.GTX_FILE)

    @staticmethod
    def wgs84_to_2000(lat, lon, alt, sep):
        # Transformacja na płaszczyznę (x_east=Y, y_north=X)
        y_east, x_north = GeoMath.transformer.transform(lon, lat)
        
        # Korekta o geoidę PL-KRON86-NH
        h_norm = (alt + sep) - GeoMath.geoid.get_n(lat, lon)
        
        return round(x_north, 3), round(y_east, 3), round(h_norm, 3)

    @staticmethod
    def calculate_distance(lat1, lon1, lat2, lon2):
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi, dlam = math.radians(lat2-lat1), math.radians(lon2-lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
