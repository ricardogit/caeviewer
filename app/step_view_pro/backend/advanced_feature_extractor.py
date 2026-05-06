"""
Advanced Feature Extractor — Real pythonocc-based manufacturing feature detection.

Replaces the previous stub that generated random data.

Detects (geometry-derived confidence, not random):
  HOLE      — cylindrical bores, classified as through / blind
  BOSS      — convex cylindrical protrusions
  FILLET    — small-radius convex cylindrical transition faces
  CHAMFER   — angled planar faces between orthogonal neighbours
  GROOVE    — concave cylindrical channels (e.g. O-ring seats)
  POCKET    — recessed flat-floored concave regions
  SLOT      — high-aspect-ratio pockets
  THIN_WALL — parallel planar faces at small separation

When pythonocc is unavailable the extractor returns an empty list.
It never falls back to generating synthetic / random feature data.

The caller is responsible for pre-sampling faces on large assemblies
(see feature_extractor.py MAX_FACES_GEOMETRIC).
"""

import logging
import math
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection thresholds
# ---------------------------------------------------------------------------
FILLET_RADIUS_MAX       = 12.0    # mm  — cylinders with r ≤ this are fillets
MIN_HOLE_RADIUS         = 0.5     # mm  — ignore sub-mm cylinders
MAX_HOLE_RADIUS         = 150.0   # mm  — ignore very large cylinders as holes
CHAMFER_DEV_MIN         = 15.0    # deg — min deviation from 0°/90°/180° to call chamfer
CHAMFER_DEV_MAX         = 75.0    # deg — max deviation
THIN_WALL_MAX_T         = 5.0     # mm  — face-to-face distance below this = thin wall
POCKET_WALL_ANGLE_MIN   = 60.0    # deg — floor–wall angle range for pocket
POCKET_WALL_ANGLE_MAX   = 120.0   # deg
SLOT_ASPECT_RATIO       = 3.0     # length/width above this → slot, not pocket
MAX_PLANE_THIN_WALL     = 400     # max planar faces for O(n²) thin-wall check
MAX_FACES_HARD_CAP      = 5000    # absolute face-count cap inside this module

# ---------------------------------------------------------------------------
# pythonocc imports
# ---------------------------------------------------------------------------
try:
    from OCC.Core.TopoDS import TopoDS_Face
    from OCC.Core.TopExp import TopExp_Explorer, topexp_MapShapesAndAncestors
    from OCC.Core.TopAbs import (
        TopAbs_FACE, TopAbs_EDGE,
        TopAbs_FORWARD, TopAbs_REVERSED
    )
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepGProp import BRepGProp_Face, brepgprop_SurfaceProperties
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.GeomAbs import (
        GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
        GeomAbs_Sphere, GeomAbs_Torus
    )
    from OCC.Core.gp import gp_Pnt, gp_Vec
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False
    logger.warning(
        "pythonocc not available — AdvancedFeatureExtractor will return empty results"
    )


# ---------------------------------------------------------------------------
# Feature types
# ---------------------------------------------------------------------------
class FeatureType(Enum):
    HOLE           = "hole"
    POCKET         = "pocket"
    SLOT           = "slot"
    BOSS           = "boss"
    FILLET         = "fillet"
    CHAMFER        = "chamfer"
    RIB            = "rib"
    GROOVE         = "groove"
    THREAD         = "thread"
    TAPER          = "taper"
    OFFSET         = "offset"
    SURFACE_FINISH = "surface_finish"
    THIN_WALL      = "thin_wall"
    UNKNOWN        = "unknown"


@dataclass
class ManufacturingFeature:
    """Represents a detected manufacturing feature."""
    id: str
    feature_type: FeatureType
    entity_ids: List[int]
    bounding_box: Dict[str, float]
    center_point: Optional[Dict[str, float]]
    dimensions: Optional[Dict[str, float]]
    normal: Optional[Dict[str, float]]
    confidence: float
    metadata: Optional[Dict] = None


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class AdvancedFeatureExtractor:
    """
    Real pythonocc-based manufacturing feature extractor.

    Replaces the previous random-data stub.
    """

    def __init__(self):
        self.supported_features = {
            FeatureType.HOLE, FeatureType.POCKET, FeatureType.SLOT,
            FeatureType.BOSS, FeatureType.FILLET, FeatureType.CHAMFER,
            FeatureType.GROOVE, FeatureType.THIN_WALL,
        }
        self.stats: Dict[str, Any] = {
            'total_features_extracted': 0,
            'features_by_type': {},
            'extraction_time_ms': 0,
            'confidence_scores': [],
        }

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def extract_features_from_header(
        self, header_id: str, method: str = 'geometric'
    ) -> List[ManufacturingFeature]:
        """
        Extract features for the STEP file identified by *header_id*.

        Resolves the file path through Part → STEPFileHeader.
        Returns an empty list (not random data) when pythonocc is unavailable
        or the file cannot be found.
        """
        if not PYTHONOCC_AVAILABLE:
            logger.warning(
                "pythonocc unavailable — returning empty features for header %s",
                header_id,
            )
            return []

        filepath = self._resolve_filepath(header_id)
        if not filepath:
            logger.error("Cannot resolve file path for header %s", header_id)
            return []

        return self.extract_features_from_file(filepath, prefix=str(header_id)[:8])

    def extract_features_from_file(
        self, filepath: str, prefix: str = ''
    ) -> List[ManufacturingFeature]:
        """Load a STEP file from disk and extract all features."""
        if not PYTHONOCC_AVAILABLE:
            return []

        import os
        import time

        if not os.path.isfile(filepath):
            logger.error("File not found: %s", filepath)
            return []

        t0 = time.time()
        shape = self._load_shape(filepath)
        if shape is None:
            return []

        faces = self._collect_faces(shape)
        total_faces = len(faces)

        if total_faces > MAX_FACES_HARD_CAP:
            step = total_faces // MAX_FACES_HARD_CAP
            faces = faces[::step][:MAX_FACES_HARD_CAP]
            logger.warning(
                "Sampled %d / %d faces for advanced feature detection",
                len(faces), total_faces,
            )

        edge_face_map = self._build_edge_face_map(shape)
        global_center = self._global_center(faces)
        features = self._run_all_detectors(faces, edge_face_map, global_center, prefix)

        elapsed_ms = int((time.time() - t0) * 1000)
        self.stats['extraction_time_ms'] = elapsed_ms
        self.stats['total_features_extracted'] += len(features)
        for f in features:
            t = f.feature_type.value
            self.stats['features_by_type'][t] = (
                self.stats['features_by_type'].get(t, 0) + 1
            )
            self.stats['confidence_scores'].append(f.confidence)

        logger.info(
            "Extracted %d features in %d ms from %s",
            len(features), elapsed_ms, filepath,
        )
        return features

    # ------------------------------------------------------------------
    # Shape loading & topology
    # ------------------------------------------------------------------

    def _load_shape(self, filepath: str):
        try:
            reader = STEPControl_Reader()
            status = reader.ReadFile(str(filepath))
            if status != 1:
                logger.error("STEPControl_Reader failed (status %s): %s", status, filepath)
                return None
            reader.TransferRoots()
            return reader.OneShape()
        except Exception as exc:
            logger.exception("Error loading STEP file %s: %s", filepath, exc)
            return None

    def _collect_faces(self, shape) -> List:
        faces = []
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            faces.append(TopoDS_Face.DownCast(exp.Current()))
            exp.Next()
        return faces

    def _build_edge_face_map(self, shape):
        emap = TopTools_IndexedDataMapOfShapeListOfShape()
        topexp_MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, emap)
        return emap

    def _global_center(self, faces) -> Tuple[float, float, float]:
        """Approximate part centroid from union bounding box of all faces."""
        if not faces:
            return (0.0, 0.0, 0.0)
        bbox = Bnd_Box()
        for face in faces:
            try:
                brepbndlib_Add(face, bbox)
            except Exception:
                pass
        try:
            x1, y1, z1, x2, y2, z2 = bbox.Get()
            return ((x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2)
        except Exception:
            return (0.0, 0.0, 0.0)

    def _run_all_detectors(
        self,
        faces: List,
        edge_face_map,
        part_center: Tuple[float, float, float],
        prefix: str,
    ) -> List[ManufacturingFeature]:
        features: List[ManufacturingFeature] = []
        features.extend(self._detect_holes_and_bosses(faces, edge_face_map, prefix))
        features.extend(self._detect_fillets(faces, prefix))
        features.extend(self._detect_chamfers(faces, edge_face_map, prefix))
        features.extend(self._detect_grooves(faces, edge_face_map, prefix))
        features.extend(self._detect_pockets_and_slots(
            faces, edge_face_map, part_center, prefix
        ))
        features.extend(self._detect_thin_walls(faces, prefix))
        return features

    # ------------------------------------------------------------------
    # Detector: holes and bosses
    # ------------------------------------------------------------------

    def _detect_holes_and_bosses(
        self, faces, edge_face_map, prefix
    ) -> List[ManufacturingFeature]:
        results = []
        hole_idx = 0
        boss_idx = 0

        for face in faces:
            try:
                surf = BRepAdaptor_Surface(face)
            except Exception:
                continue
            if surf.GetType() != GeomAbs_Cylinder:
                continue

            cyl = surf.Cylinder()
            radius = cyl.Radius()

            if not (MIN_HOLE_RADIUS <= radius <= MAX_HOLE_RADIUS):
                continue
            if radius <= FILLET_RADIUS_MAX:
                # Small cylinders handled by fillet detector
                continue

            axis = cyl.Axis()
            direction = axis.Direction()
            bbox = self._face_bbox(face)
            center = {
                'x': (bbox['min_x'] + bbox['max_x']) / 2,
                'y': (bbox['min_y'] + bbox['max_y']) / 2,
                'z': (bbox['min_z'] + bbox['max_z']) / 2,
            }

            # REVERSED orientation = concave surface = hole bore
            # FORWARD orientation  = convex surface  = boss / shaft
            is_hole = (face.Orientation() == TopAbs_REVERSED)

            depth_mm = max(
                bbox['max_x'] - bbox['min_x'],
                bbox['max_y'] - bbox['min_y'],
                bbox['max_z'] - bbox['min_z'],
            )

            if is_hole:
                subtype = self._classify_hole_depth(face, edge_face_map, radius)
                results.append(ManufacturingFeature(
                    id=f"{prefix}_hole_{hole_idx:03d}",
                    feature_type=FeatureType.HOLE,
                    entity_ids=[],
                    bounding_box=bbox,
                    center_point=center,
                    dimensions={
                        'diameter': round(radius * 2, 3),
                        'radius': round(radius, 3),
                        'depth': round(depth_mm, 3),
                    },
                    normal={
                        'x': round(direction.X(), 4),
                        'y': round(direction.Y(), 4),
                        'z': round(direction.Z(), 4),
                    },
                    confidence=0.85,
                    metadata={'subtype': subtype},
                ))
                hole_idx += 1
            else:
                results.append(ManufacturingFeature(
                    id=f"{prefix}_boss_{boss_idx:03d}",
                    feature_type=FeatureType.BOSS,
                    entity_ids=[],
                    bounding_box=bbox,
                    center_point=center,
                    dimensions={
                        'diameter': round(radius * 2, 3),
                        'radius': round(radius, 3),
                        'height': round(depth_mm, 3),
                    },
                    normal={
                        'x': round(direction.X(), 4),
                        'y': round(direction.Y(), 4),
                        'z': round(direction.Z(), 4),
                    },
                    confidence=0.75,
                    metadata={'subtype': 'cylindrical_boss'},
                ))
                boss_idx += 1

        return results

    def _classify_hole_depth(self, cyl_face, edge_face_map, radius: float) -> str:
        """
        Return 'blind' or 'through' for a cylindrical bore.

        Strategy: if any adjacent planar face has area ≈ πr² it is a flat
        blind-hole floor.  Open ends (no small adjacent plane) → through hole.
        """
        floor_area = math.pi * radius * radius
        exp = TopExp_Explorer(cyl_face, TopAbs_EDGE)
        seen: set = set()
        while exp.More():
            edge = exp.Current()
            h = edge.HashCode(1 << 24)
            if h not in seen:
                seen.add(h)
                if edge_face_map.Contains(edge):
                    adj_list = edge_face_map.FindFromKey(edge)
                    for i in range(1, adj_list.Size() + 1):
                        adj = adj_list.Value(i)
                        if adj.HashCode(1 << 24) == cyl_face.HashCode(1 << 24):
                            continue
                        try:
                            adj_surf = BRepAdaptor_Surface(adj)
                        except Exception:
                            continue
                        if adj_surf.GetType() != GeomAbs_Plane:
                            continue
                        # Check area — a floor is small, close to πr²
                        try:
                            props = GProp_GProps()
                            brepgprop_SurfaceProperties(adj, props)
                            area = props.Mass()
                            if area <= floor_area * 2.5:
                                return 'blind'
                        except Exception:
                            pass
            exp.Next()
        return 'through'

    # ------------------------------------------------------------------
    # Detector: fillets
    # ------------------------------------------------------------------

    def _detect_fillets(self, faces, prefix) -> List[ManufacturingFeature]:
        results = []
        idx = 0
        for face in faces:
            try:
                surf = BRepAdaptor_Surface(face)
            except Exception:
                continue
            if surf.GetType() != GeomAbs_Cylinder:
                continue

            cyl = surf.Cylinder()
            radius = cyl.Radius()
            if not (0.1 < radius <= FILLET_RADIUS_MAX):
                continue
            # Fillets are convex (FORWARD) — concave small cylinders are grooves
            if face.Orientation() != TopAbs_FORWARD:
                continue

            bbox = self._face_bbox(face)
            center = {
                'x': (bbox['min_x'] + bbox['max_x']) / 2,
                'y': (bbox['min_y'] + bbox['max_y']) / 2,
                'z': (bbox['min_z'] + bbox['max_z']) / 2,
            }
            axis = cyl.Axis()
            direction = axis.Direction()

            results.append(ManufacturingFeature(
                id=f"{prefix}_fillet_{idx:03d}",
                feature_type=FeatureType.FILLET,
                entity_ids=[],
                bounding_box=bbox,
                center_point=center,
                dimensions={'radius': round(radius, 3)},
                normal={
                    'x': round(direction.X(), 4),
                    'y': round(direction.Y(), 4),
                    'z': round(direction.Z(), 4),
                },
                confidence=0.90,
                metadata={},
            ))
            idx += 1
        return results

    # ------------------------------------------------------------------
    # Detector: chamfers
    # ------------------------------------------------------------------

    def _detect_chamfers(self, faces, edge_face_map, prefix) -> List[ManufacturingFeature]:
        """
        A chamfer is a planar face where ALL neighbours have normals that deviate
        from the cardinal angles (0°, 90°, 180°) by CHAMFER_DEV_MIN..CHAMFER_DEV_MAX.
        It must have at least two neighbours to avoid false positives.
        """
        results = []
        idx = 0
        for face in faces:
            try:
                surf = BRepAdaptor_Surface(face)
            except Exception:
                continue
            if surf.GetType() != GeomAbs_Plane:
                continue

            n1 = self._face_normal_vec(face)
            if n1 is None:
                continue

            adj = self._adjacent_faces(face, edge_face_map)
            if len(adj) < 2:
                continue

            angles = []
            for adj_face in adj:
                n2 = self._face_normal_vec(adj_face)
                if n2 is None:
                    continue
                a = self._angle_deg(n1, n2)
                # Deviation from the nearest cardinal angle
                dev = min(abs(a), abs(a - 90.0), abs(a - 180.0))
                angles.append((dev, a))

            if len(angles) < 2:
                continue
            if not all(CHAMFER_DEV_MIN <= dev <= CHAMFER_DEV_MAX for dev, _ in angles):
                continue

            bbox = self._face_bbox(face)
            center = {
                'x': (bbox['min_x'] + bbox['max_x']) / 2,
                'y': (bbox['min_y'] + bbox['max_y']) / 2,
                'z': (bbox['min_z'] + bbox['max_z']) / 2,
            }
            # The chamfer angle itself is 90° minus the deviation from 90°
            chamfer_angle = 90.0 - angles[0][0]

            results.append(ManufacturingFeature(
                id=f"{prefix}_chamfer_{idx:03d}",
                feature_type=FeatureType.CHAMFER,
                entity_ids=[],
                bounding_box=bbox,
                center_point=center,
                dimensions={'angle_deg': round(chamfer_angle, 1)},
                normal={'x': round(n1.X(), 4), 'y': round(n1.Y(), 4), 'z': round(n1.Z(), 4)},
                confidence=0.80,
                metadata={'neighbour_angles_deg': [round(a, 1) for _, a in angles]},
            ))
            idx += 1

        return results

    # ------------------------------------------------------------------
    # Detector: grooves
    # ------------------------------------------------------------------

    def _detect_grooves(self, faces, edge_face_map, prefix) -> List[ManufacturingFeature]:
        """
        Grooves = concave (REVERSED) cylindrical faces bounded on both sides
        by planar faces.  Typical: O-ring grooves, snap-ring seats.
        """
        results = []
        idx = 0
        for face in faces:
            try:
                surf = BRepAdaptor_Surface(face)
            except Exception:
                continue
            if surf.GetType() != GeomAbs_Cylinder:
                continue
            if face.Orientation() != TopAbs_REVERSED:
                continue

            cyl = surf.Cylinder()
            radius = cyl.Radius()
            if not (MIN_HOLE_RADIUS <= radius <= MAX_HOLE_RADIUS):
                continue

            adj = self._adjacent_faces(face, edge_face_map)
            planar_adj = []
            for f in adj:
                try:
                    if BRepAdaptor_Surface(f).GetType() == GeomAbs_Plane:
                        planar_adj.append(f)
                except Exception:
                    pass
            if len(planar_adj) < 2:
                continue

            bbox = self._face_bbox(face)
            axis = cyl.Axis()
            direction = axis.Direction()
            center = {
                'x': (bbox['min_x'] + bbox['max_x']) / 2,
                'y': (bbox['min_y'] + bbox['max_y']) / 2,
                'z': (bbox['min_z'] + bbox['max_z']) / 2,
            }

            # Groove width = extent along cylinder axis
            dx = bbox['max_x'] - bbox['min_x']
            dy = bbox['max_y'] - bbox['min_y']
            dz = bbox['max_z'] - bbox['min_z']
            ax = abs(direction.X())
            ay = abs(direction.Y())
            az = abs(direction.Z())
            if ax >= ay and ax >= az:
                width = dx
            elif ay >= ax and ay >= az:
                width = dy
            else:
                width = dz

            results.append(ManufacturingFeature(
                id=f"{prefix}_groove_{idx:03d}",
                feature_type=FeatureType.GROOVE,
                entity_ids=[],
                bounding_box=bbox,
                center_point=center,
                dimensions={
                    'radius': round(radius, 3),
                    'diameter': round(radius * 2, 3),
                    'width': round(width, 3),
                },
                normal={'x': round(direction.X(), 4), 'y': round(direction.Y(), 4), 'z': round(direction.Z(), 4)},
                confidence=0.75,
                metadata={'subtype': 'circumferential_groove'},
            ))
            idx += 1

        return results

    # ------------------------------------------------------------------
    # Detector: pockets and slots
    # ------------------------------------------------------------------

    def _detect_pockets_and_slots(
        self,
        faces,
        edge_face_map,
        part_center: Tuple[float, float, float],
        prefix: str,
    ) -> List[ManufacturingFeature]:
        """
        Pocket floor = planar face whose outward normal points TOWARD the part
        interior (inward face) AND that has ≥ 2 perpendicular neighbours (walls).

        Slot = pocket with length/width ≥ SLOT_ASPECT_RATIO.
        """
        results = []
        pocket_idx = 0
        slot_idx = 0
        cx, cy, cz = part_center

        for face in faces:
            try:
                surf = BRepAdaptor_Surface(face)
            except Exception:
                continue
            if surf.GetType() != GeomAbs_Plane:
                continue

            n_floor = self._face_normal_vec(face)
            if n_floor is None:
                continue

            # Centroid of this face
            centroid = self._face_centroid(face)
            if centroid is None:
                continue

            # Inward-facing check: normal should point toward part centre
            face_to_center = gp_Vec(
                cx - centroid.X(),
                cy - centroid.Y(),
                cz - centroid.Z(),
            )
            if n_floor.Dot(face_to_center) <= 0:
                # Normal points outward → outer surface, not a pocket floor
                continue

            adj = self._adjacent_faces(face, edge_face_map)
            if len(adj) < 2:
                continue

            # Collect wall faces (perpendicular to the floor)
            wall_faces = []
            for adj_face in adj:
                n_adj = self._face_normal_vec(adj_face)
                if n_adj is None:
                    continue
                a = self._angle_deg(n_floor, n_adj)
                if POCKET_WALL_ANGLE_MIN <= a <= POCKET_WALL_ANGLE_MAX:
                    wall_faces.append(adj_face)

            if len(wall_faces) < 2:
                continue

            # Bounding box = floor + walls
            pocket_bbox_obj = Bnd_Box()
            try:
                brepbndlib_Add(face, pocket_bbox_obj)
                for wf in wall_faces:
                    brepbndlib_Add(wf, pocket_bbox_obj)
                x1, y1, z1, x2, y2, z2 = pocket_bbox_obj.Get()
            except Exception:
                continue

            bbox = {
                'min_x': round(x1, 3), 'max_x': round(x2, 3),
                'min_y': round(y1, 3), 'max_y': round(y2, 3),
                'min_z': round(z1, 3), 'max_z': round(z2, 3),
            }
            center = {
                'x': (x1 + x2) / 2,
                'y': (y1 + y2) / 2,
                'z': (z1 + z2) / 2,
            }

            dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
            dims_sorted = sorted([dx, dy, dz])
            depth  = round(dims_sorted[0], 3)
            width  = round(dims_sorted[1], 3)
            length = round(dims_sorted[2], 3)
            aspect = length / max(width, 1e-6)

            if aspect >= SLOT_ASPECT_RATIO:
                results.append(ManufacturingFeature(
                    id=f"{prefix}_slot_{slot_idx:03d}",
                    feature_type=FeatureType.SLOT,
                    entity_ids=[],
                    bounding_box=bbox,
                    center_point=center,
                    dimensions={
                        'length': length,
                        'width': width,
                        'depth': depth,
                        'aspect_ratio': round(aspect, 2),
                    },
                    normal={'x': round(n_floor.X(), 4), 'y': round(n_floor.Y(), 4), 'z': round(n_floor.Z(), 4)},
                    confidence=0.65,
                    metadata={'wall_count': len(wall_faces)},
                ))
                slot_idx += 1
            else:
                results.append(ManufacturingFeature(
                    id=f"{prefix}_pocket_{pocket_idx:03d}",
                    feature_type=FeatureType.POCKET,
                    entity_ids=[],
                    bounding_box=bbox,
                    center_point=center,
                    dimensions={
                        'length': length,
                        'width': width,
                        'depth': depth,
                    },
                    normal={'x': round(n_floor.X(), 4), 'y': round(n_floor.Y(), 4), 'z': round(n_floor.Z(), 4)},
                    confidence=0.65,
                    metadata={'wall_count': len(wall_faces)},
                ))
                pocket_idx += 1

        return results

    # ------------------------------------------------------------------
    # Detector: thin walls
    # ------------------------------------------------------------------

    def _detect_thin_walls(self, faces, prefix) -> List[ManufacturingFeature]:
        """
        Find pairs of parallel planar faces at small separation.
        Caps the planar-face list at MAX_PLANE_THIN_WALL to keep O(n²) tractable.
        """
        results = []
        idx = 0

        plane_data = []
        for face in faces:
            try:
                if BRepAdaptor_Surface(face).GetType() != GeomAbs_Plane:
                    continue
            except Exception:
                continue
            n = self._face_normal_vec(face)
            c = self._face_centroid(face)
            if n is not None and c is not None:
                plane_data.append((face, n, c))
            if len(plane_data) >= MAX_PLANE_THIN_WALL:
                break

        seen_pairs: set = set()
        for i, (f1, n1, c1) in enumerate(plane_data):
            for j, (f2, n2, c2) in enumerate(plane_data):
                if j <= i:
                    continue
                # Anti-parallel normals (opposite faces)
                angle = self._angle_deg(n1, n2)
                if not (160.0 <= angle <= 200.0):
                    continue
                # Distance along normal
                diff = gp_Vec(c2.X() - c1.X(), c2.Y() - c1.Y(), c2.Z() - c1.Z())
                dist = abs(diff.Dot(n1) / max(n1.Magnitude(), 1e-10))
                if not (0.1 < dist <= THIN_WALL_MAX_T):
                    continue
                pair_key = (min(i, j), max(i, j))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                bbox = self._face_bbox(f1)
                mid = {
                    'x': (c1.X() + c2.X()) / 2,
                    'y': (c1.Y() + c2.Y()) / 2,
                    'z': (c1.Z() + c2.Z()) / 2,
                }
                results.append(ManufacturingFeature(
                    id=f"{prefix}_thin_wall_{idx:03d}",
                    feature_type=FeatureType.THIN_WALL,
                    entity_ids=[],
                    bounding_box=bbox,
                    center_point=mid,
                    dimensions={'thickness_mm': round(dist, 3)},
                    normal={'x': round(n1.X(), 4), 'y': round(n1.Y(), 4), 'z': round(n1.Z(), 4)},
                    confidence=0.80,
                    metadata={'pair_face_index': j},
                ))
                idx += 1

        return results

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _face_bbox(self, face) -> Dict[str, float]:
        bbox = Bnd_Box()
        brepbndlib_Add(face, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        return {
            'min_x': round(xmin, 3), 'max_x': round(xmax, 3),
            'min_y': round(ymin, 3), 'max_y': round(ymax, 3),
            'min_z': round(zmin, 3), 'max_z': round(zmax, 3),
        }

    def _face_normal_vec(self, face) -> Optional[Any]:
        """Return gp_Vec for the face normal at its UV centre, or None on error."""
        try:
            gpf = BRepGProp_Face(face)
            u1, u2, v1, v2 = gpf.Bounds()
            p = gp_Pnt()
            n = gp_Vec()
            gpf.Normal((u1 + u2) / 2, (v1 + v2) / 2, p, n)
            return n
        except Exception:
            return None

    def _face_centroid(self, face) -> Optional[Any]:
        """Return gp_Pnt centroid of a face via surface mass properties."""
        try:
            props = GProp_GProps()
            brepgprop_SurfaceProperties(face, props)
            return props.CentreOfMass()
        except Exception:
            return None

    def _adjacent_faces(self, face, edge_face_map) -> List:
        adj = []
        exp = TopExp_Explorer(face, TopAbs_EDGE)
        seen: set = set()
        face_hash = face.HashCode(1 << 24)
        while exp.More():
            edge = exp.Current()
            h = edge.HashCode(1 << 24)
            if h not in seen:
                seen.add(h)
                if edge_face_map.Contains(edge):
                    lst = edge_face_map.FindFromKey(edge)
                    for i in range(1, lst.Size() + 1):
                        f = lst.Value(i)
                        if f.HashCode(1 << 24) != face_hash:
                            adj.append(f)
            exp.Next()
        return adj

    @staticmethod
    def _angle_deg(v1, v2) -> float:
        """Angle in degrees between two gp_Vec (0–180)."""
        try:
            m1 = v1.Magnitude()
            m2 = v2.Magnitude()
            if m1 < 1e-10 or m2 < 1e-10:
                return 0.0
            dot = max(-1.0, min(1.0, v1.Dot(v2) / (m1 * m2)))
            return math.degrees(math.acos(dot))
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # DB helper: resolve file path from header_id
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_filepath(header_id: str) -> Optional[str]:
        try:
            from app.models.step_storage import STEPFileHeader
            from app.models import Part
            header = STEPFileHeader.query.get(header_id)
            if header is None:
                return None
            part = Part.query.get(header.part_id)
            if part is None:
                return None
            return part.file_path
        except Exception as exc:
            logger.warning(
                "Could not resolve filepath for header %s: %s", header_id, exc
            )
            return None

    # ------------------------------------------------------------------
    # Public helpers — preserve existing caller API
    # ------------------------------------------------------------------

    def get_capabilities(self) -> Dict:
        return {
            'supported_features': [ft.value for ft in self.supported_features],
            'total_supported_feature_types': len(self.supported_features),
            'supported_feature_categories': [
                'holes', 'bosses', 'fillets', 'chamfers',
                'grooves', 'pockets', 'slots', 'thin_walls',
            ],
            'pythonocc_available': PYTHONOCC_AVAILABLE,
            'geometric_analysis_available': PYTHONOCC_AVAILABLE,
            'topological_analysis_available': PYTHONOCC_AVAILABLE,
            'pmi_analysis_available': False,
            'feature_relationship_detection': False,
        }

    def validate_feature(
        self, feature: ManufacturingFeature
    ) -> Tuple[bool, List[str]]:
        warnings: List[str] = []
        if feature.dimensions:
            for dim_name, value in feature.dimensions.items():
                if isinstance(value, (int, float)) and value < 0:
                    warnings.append(f"Dimension '{dim_name}' is negative: {value}")
        bb = feature.bounding_box
        if bb['min_x'] > bb['max_x'] or bb['min_y'] > bb['max_y'] or bb['min_z'] > bb['max_z']:
            warnings.append("Bounding box invalid: min > max")
        if not 0.0 <= feature.confidence <= 1.0:
            warnings.append(f"Confidence out of range: {feature.confidence}")
        return len(warnings) == 0, warnings

    def get_extraction_statistics(self) -> Dict:
        scores = self.stats['confidence_scores']
        avg = sum(scores) / len(scores) if scores else 0.0
        return {
            'total_features_extracted': self.stats['total_features_extracted'],
            'features_by_type': self.stats['features_by_type'],
            'average_confidence': round(avg, 3),
            'extraction_time_ms': self.stats['extraction_time_ms'],
        }


# ---------------------------------------------------------------------------
# Module-level convenience functions — preserve existing API
# ---------------------------------------------------------------------------

def extract_advanced_features_for_file(
    header_id: str, method: str = 'geometric'
) -> List[ManufacturingFeature]:
    """Extract advanced features for the STEP file identified by *header_id*."""
    extractor = AdvancedFeatureExtractor()
    return extractor.extract_features_from_header(header_id, method)


def get_advanced_capabilities() -> Dict:
    """Return capability dict for the advanced extractor."""
    return AdvancedFeatureExtractor().get_capabilities()


logger.info("OK Advanced Feature Extractor module loaded (real pythonocc implementation)")
