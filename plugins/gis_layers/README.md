# GIS Layers Plugin

Manages geographic data sources for the TRITIUM-SC Command Center map.

## Providers

| Provider | Type | Description |
|----------|------|-------------|
| `osm` | tile | OpenStreetMap raster tiles (no API key) |
| `satellite` | tile | Satellite imagery (Esri World Imagery default) |
| `buildings` | feature | Building footprint polygons (stub/mock) |
| `terrain` | feature | Elevation data points (stub/mock) |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/gis/layers` | List available layers |
| GET | `/api/gis/layers/{name}/tiles/{z}/{x}/{y}` | Proxy tile request |
| GET | `/api/gis/layers/{name}/features?bbox=w,s,e,n` | GeoJSON features |

## Adding Custom Providers

Subclass `LayerProvider` from `providers.py` and register it with the plugin:

```python
from plugins.gis_layers.providers import LayerProvider, BBox

class MyProvider(LayerProvider):
    @property
    def layer_id(self) -> str:
        return "my-layer"

    @property
    def layer_name(self) -> str:
        return "My Custom Layer"

    def query(self, bounds: BBox) -> dict:
        return {"type": "FeatureCollection", "features": [...]}
```
