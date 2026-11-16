"""Geographic datasets (FASE 10.5): one row per imported file, content-addressed like the CAD geometry.

The source file is kept under DATA_DIR/geodata/files/<sha[:2]>/<sha><ext>; the normalised form (lon/lat GeoJSON
for vectors, npz for grids / soundings / series, json for harmonics) and a preview under DATA_DIR/geodata/<id>/.
A study references datasets by id; its hash uses their ``sha256`` + import ``params`` (traceability)."""
from sqlalchemy import BigInteger, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import BaseModel

GEO_KINDS = ('coastline', 'bathymetry', 'zones', 'points', 'forcing')


class GeoDataset(BaseModel):
    __tablename__ = 'geo_datasets'

    project_id        = Column(UUID(as_uuid=True), ForeignKey('projects.id', ondelete='SET NULL'), index=True)
    name              = Column(String(255), nullable=False)
    kind              = Column(String(16), nullable=False, index=True)      # GEO_KINDS
    fmt               = Column(String(16))                                  # file extension
    original_filename = Column(String(500))
    file_uri          = Column(String(1000), nullable=False)               # relative to DATA_DIR
    sha256            = Column(String(64), nullable=False, index=True)
    size_bytes        = Column(BigInteger)
    params            = Column(JSONB, default=dict)      # import options: crs, convention, time_unit
    source_crs        = Column(Text)                     # CRS of the file ('EPSG:xxxx' or WKT)
    bbox              = Column(JSONB)                    # [west, south, east, north] lon/lat
    summary           = Column(JSONB, default=dict)      # counts, depth range, series columns…
    processed_uri     = Column(String(1000))             # normalised data, relative to DATA_DIR
    preview_uri       = Column(String(1000))             # PNG of a bathymetry grid (map overlay)

    def to_dict(self):
        d = super().to_dict()
        d.pop('file_uri', None)
        d.pop('processed_uri', None)
        d['has_preview'] = bool(d.pop('preview_uri', None))
        return d
