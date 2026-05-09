# gml_handler.py
import geopandas as gpd
from shapely.geometry import Point

class MapInspector:
    def __init__(self, path):
        try:
            self.gdf = gpd.read_file(path, engine='pyogrio')
            self.boundaries = self.gdf.geometry.boundary
            self.id_col = 'idDzialki' if 'idDzialki' in self.gdf.columns else self.gdf.columns[0]
        except: self.gdf = None

    def analyze(self, x, y):
        if self.gdf is None: return "BRAK GML", 999.0
        p = Point(x, y)
        mask = self.gdf.contains(p)
        dz = self.gdf[mask][self.id_col].values[0] if mask.any() else "POZA"
        dist = self.boundaries.distance(p).min()
        return dz, dist
