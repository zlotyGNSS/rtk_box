# geo_math.py
import struct
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from pyproj import Transformer

class GeodesyExpert:
    def __init__(self, gtx_path):
        self.tr = Transformer.from_crs("EPSG:4326", "EPSG:2177", always_xy=True)
        self.geoid = self._load_geoid(gtx_path)

    def _load_geoid(self, path):
        try:
            with open(path, 'rb') as f:
                h = struct.unpack('>ddddii', f.read(40))
            data = np.fromfile(path, dtype='>f4', offset=40).reshape((h[4], h[5]))
            lats = np.linspace(h[0], h[0] + (h[4]-1)*h[2], h[4])
            lons = np.linspace(h[1], h[1] + (h[5]-1)*h[3], h[5])
            return RegularGridInterpolator((lats, lons), data, bounds_error=False)
        except: return None

    def process(self, lon, lat, alt, sep):
        x, y = self.tr.transform(lon, lat)
        n = float(self.geoid((lat, lon))) if self.geoid else 0
        h = (alt + sep) - n
        return x, y, h
