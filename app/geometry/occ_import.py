"""STEP import with XDE (STEPCAFControl_Reader) and per-face signatures (pythonOCC 7.7.x)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.BRepLProp import BRepLProp_SLProps
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.GeomAbs import (
    GeomAbs_BezierSurface, GeomAbs_BSplineSurface, GeomAbs_Cone, GeomAbs_Cylinder,
    GeomAbs_OffsetSurface, GeomAbs_OtherSurface, GeomAbs_Plane, GeomAbs_Sphere,
    GeomAbs_SurfaceOfExtrusion, GeomAbs_SurfaceOfRevolution, GeomAbs_Torus,
)
from OCC.Core.GProp import GProp_GProps
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Interface import Interface_Static
from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
from OCC.Core.TDF import TDF_Label, TDF_LabelSequence
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import TopoDS_Compound, topods
from OCC.Core.TopTools import TopTools_IndexedMapOfShape
from OCC.Core.XCAFDoc import XCAFDoc_ShapeTool

from .signature import bbox_diagonal, normalise_type, signature_hash

# --- static-method shims (pythonOCC 7.7 exposes both cls.Method and cls_Method) ----


def _static(module_name: str, cls: str, method: str):
    import importlib
    mod = importlib.import_module(f"OCC.Core.{module_name}")
    obj = getattr(mod, cls, None)
    if obj is not None and hasattr(obj, method):
        return getattr(obj, method)
    return getattr(mod, f"{cls}_{method}")


_map_shapes = _static("TopExp", "topexp", "MapShapes")
_surface_props = _static("BRepGProp", "brepgprop", "SurfaceProperties")
_volume_props = _static("BRepGProp", "brepgprop", "VolumeProperties")
_bnd_add_optimal = _static("BRepBndLib", "brepbndlib", "AddOptimal")
_breptools_write = _static("BRepTools", "breptools", "Write")


def _uv_bounds(face):
    try:
        return _static("BRepTools", "breptools", "UVBounds")(face)
    except Exception:
        return _static("ShapeAnalysis", "shapeanalysis", "GetFaceUVBounds")(face)


_SURF_TYPES = {
    GeomAbs_Plane: "Plane", GeomAbs_Cylinder: "Cylinder", GeomAbs_Cone: "Cone",
    GeomAbs_Sphere: "Sphere", GeomAbs_Torus: "Torus",
    GeomAbs_BezierSurface: "BezierSurface", GeomAbs_BSplineSurface: "BSplineSurface",
    GeomAbs_SurfaceOfRevolution: "SurfaceOfRevolution",
    GeomAbs_SurfaceOfExtrusion: "SurfaceOfExtrusion",
    GeomAbs_OffsetSurface: "OffsetSurface", GeomAbs_OtherSurface: "OtherSurface",
}


# ---------------------------------------------------------------------------


@dataclass
class ImportedGeometry:
    path: str
    shape: object                       # TopoDS_Shape
    face_map: object                    # TopTools_IndexedMapOfShape (1-based)
    solid_map: object
    is_assembly: bool
    n_free_shapes: int
    face_names: dict = field(default_factory=dict)    # face_index -> XDE name
    solid_names: dict = field(default_factory=dict)   # solid_index -> XDE name
    import_seconds: float = 0.0

    @property
    def n_faces(self) -> int:
        return self.face_map.Size()

    @property
    def n_solids(self) -> int:
        return self.solid_map.Size()


def _label_name(label) -> str | None:
    try:
        name = label.GetLabelName()
        return name or None
    except Exception:
        pass
    try:
        from OCC.Core.TDataStd import TDataStd_Name
        attr = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID(), attr):
            return attr.Get().ToExtString() or None
    except Exception:
        pass
    return None


def read_step(path: str | Path) -> ImportedGeometry:
    """Read a STEP file through XDE, in millimetres.

    The returned ``face_map`` gives the persistent, deterministic face index
    (TopExp::MapShapes order, 1-based) for this geometry version.
    """
    t0 = time.perf_counter()
    path = str(path)
    Interface_Static.SetCVal("xstep.cascade.unit", "MM")

    # NB: pythonOCC 7.7.2 aborts (Standard_NullObject) if given a TCollection_ExtendedString
    doc = TDocStd_Document("face-bridge")
    try:  # OCCT >= 7.6: the target document carries its own length unit
        from OCC.Core.UnitsMethods import UnitsMethods_LengthUnit_Millimeter
        _static("XCAFDoc", "XCAFDoc_DocumentTool", "SetLengthUnit")(
            doc, 1.0, UnitsMethods_LengthUnit_Millimeter)
    except Exception:
        try:
            _static("XCAFDoc", "XCAFDoc_DocumentTool", "SetLengthUnit")(doc, 1.0)
        except Exception:
            pass

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"STEPCAFControl_Reader.ReadFile failed (status {status}): {path}")
    if not reader.Transfer(doc):
        raise RuntimeError(f"STEPCAFControl_Reader.Transfer failed: {path}")

    shape_tool = _static("XCAFDoc", "XCAFDoc_DocumentTool", "ShapeTool")(doc.Main())
    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    n_free = free.Length()
    if n_free == 0:
        raise RuntimeError(f"No shapes in STEP: {path}")

    get_shape = XCAFDoc_ShapeTool.GetShape
    is_asm = any(XCAFDoc_ShapeTool.IsAssembly(free.Value(i)) for i in range(1, n_free + 1))

    if n_free == 1:
        shape = get_shape(free.Value(1))
    else:
        comp = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(comp)
        for i in range(1, n_free + 1):
            builder.Add(comp, get_shape(free.Value(i)))
        shape = comp

    face_map = TopTools_IndexedMapOfShape()
    _map_shapes(shape, TopAbs_FACE, face_map)
    solid_map = TopTools_IndexedMapOfShape()
    _map_shapes(shape, TopAbs_SOLID, solid_map)

    geom = ImportedGeometry(path=path, shape=shape, face_map=face_map, solid_map=solid_map,
                            is_assembly=bool(is_asm), n_free_shapes=n_free)
    _collect_names(free, geom)
    geom.import_seconds = time.perf_counter() - t0
    return geom


def _collect_names(free: TDF_LabelSequence, geom: ImportedGeometry) -> None:
    """Best-effort XDE names for solids/faces, with assembly locations composed."""

    def visit(label, loc: TopLoc_Location, depth: int):
        if depth > 32:
            return
        if XCAFDoc_ShapeTool.IsReference(label):
            ref = TDF_Label()
            XCAFDoc_ShapeTool.GetReferredShape(label, ref)
            comp_loc = XCAFDoc_ShapeTool.GetLocation(label)
            visit(ref, loc.Multiplied(comp_loc), depth + 1)
            return
        name = _label_name(label)
        if name:
            s = XCAFDoc_ShapeTool.GetShape(label)
            if not s.IsNull():
                s = s.Moved(loc) if not loc.IsIdentity() else s
                if s.ShapeType() == TopAbs_SOLID:
                    idx = geom.solid_map.FindIndex(s)
                    if idx:
                        geom.solid_names[idx] = name
                elif s.ShapeType() == TopAbs_FACE:
                    idx = geom.face_map.FindIndex(s)
                    if idx:
                        geom.face_names[idx] = name
                # a named compound/part holding exactly one solid -> name that solid
                elif geom.solid_map.Size():
                    exp = TopExp_Explorer(s, TopAbs_SOLID)
                    solids = []
                    while exp.More():
                        solids.append(exp.Current())
                        exp.Next()
                    if len(solids) == 1:
                        idx = geom.solid_map.FindIndex(solids[0])
                        if idx and idx not in geom.solid_names:
                            geom.solid_names[idx] = name
        if XCAFDoc_ShapeTool.IsAssembly(label):
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents(label, comps, False)
            for i in range(1, comps.Length() + 1):
                visit(comps.Value(i), loc, depth + 1)
        subs = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes(label, subs)
        for i in range(1, subs.Length() + 1):
            visit(subs.Value(i), loc, depth + 1)

    for i in range(1, free.Length() + 1):
        try:
            visit(free.Value(i), TopLoc_Location(), 0)
        except Exception:  # names are optional; never fail the import on them
            pass


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------


def _bbox(shape) -> list[float]:
    box = Bnd_Box()
    _bnd_add_optimal(shape, box, False, False)
    return list(box.Get())


def face_signature(face) -> dict:
    face = topods.Face(face)
    adaptor = BRepAdaptor_Surface(face, True)
    stype = _SURF_TYPES.get(adaptor.GetType(), "OtherSurface")

    props = GProp_GProps()
    _surface_props(face, props)
    area = props.Mass()
    c = props.CentreOfMass()

    normal = None
    try:
        umin, umax, vmin, vmax = _uv_bounds(face)
        u, v = 0.5 * (umin + umax), 0.5 * (vmin + vmax)
        slp = BRepLProp_SLProps(adaptor, u, v, 1, 1e-9)
        if slp.IsNormalDefined():
            n = slp.Normal()
            if face.Orientation() == TopAbs_REVERSED:
                n.Reverse()
            normal = [n.X(), n.Y(), n.Z()]
    except Exception:
        normal = None

    radius = None
    try:
        if stype == "Cylinder":
            radius = adaptor.Cylinder().Radius()
        elif stype == "Sphere":
            radius = adaptor.Sphere().Radius()
        elif stype == "Cone":
            radius = adaptor.Cone().RefRadius()
        elif stype == "Torus":
            radius = adaptor.Torus().MajorRadius()
    except Exception:
        radius = None

    sig = {
        "occ_type": stype,
        "surface_type": normalise_type(stype),
        "area": area,
        "centroid": [c.X(), c.Y(), c.Z()],
        "bbox": _bbox(face),
        "normal": normal,
        "radius": radius,
    }
    sig["hash"] = signature_hash(sig)
    return sig


def solid_signature(solid) -> dict:
    props = GProp_GProps()
    _volume_props(solid, props)
    c = props.CentreOfMass()
    return {"surface_type": None, "area": props.Mass(),   # "area" = generic measure
            "centroid": [c.X(), c.Y(), c.Z()], "bbox": _bbox(solid)}


def face_to_solid_index(geom: ImportedGeometry) -> dict[int, int]:
    """face_index -> owning solid index (0 for faces outside any solid)."""
    owner: dict[int, int] = {}
    for si in range(1, geom.solid_map.Size() + 1):
        exp = TopExp_Explorer(geom.solid_map.FindKey(si), TopAbs_FACE)
        while exp.More():
            fi = geom.face_map.FindIndex(exp.Current())
            if fi and fi not in owner:
                owner[fi] = si
            exp.Next()
    return owner


def compute_signatures(geom: ImportedGeometry) -> dict:
    """All face and solid signatures, JSON-serialisable."""
    owner = face_to_solid_index(geom)
    faces = []
    for fi in range(1, geom.face_map.Size() + 1):
        sig = face_signature(geom.face_map.FindKey(fi))
        sig["index"] = fi
        sig["solid"] = owner.get(fi, 0)
        if fi in geom.face_names:
            sig["name"] = geom.face_names[fi]
        faces.append(sig)
    solids = []
    for si in range(1, geom.solid_map.Size() + 1):
        sig = solid_signature(geom.solid_map.FindKey(si))
        sig["index"] = si
        if si in geom.solid_names:
            sig["name"] = geom.solid_names[si]
        solids.append(sig)
    bbox = _bbox(geom.shape)
    return {"faces": faces, "solids": solids, "bbox": bbox, "scale": bbox_diagonal(bbox)}


def write_brep(geom: ImportedGeometry, out_path: str | Path) -> str:
    out_path = str(out_path)
    ok = _breptools_write(geom.shape, out_path)
    if ok is False:
        raise RuntimeError(f"BRepTools::Write failed: {out_path}")
    return out_path
