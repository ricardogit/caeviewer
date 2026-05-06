"""
Feature Extractor - Detección automática de features de manufactura en geometrías STEP
Versión: 1.0.0
Autor: STEP-View Pro Team

Detecta automáticamente:
- Holes (agujeros cilíndricos pasantes y ciegos)
- Pockets (cavidades rectangulares o de forma libre)
- Slots (ranuras)
- Bosses (salientes cilíndricos)
- Fillets (redondeos)
- Chamfers (chaflanes)
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import math

# Limits for large-assembly safety
# Above MAX_FACES_GEOMETRIC, geometric analysis is sampled rather than exhaustive.
MAX_FACES_GEOMETRIC = 5000
# Above MAX_ENTITIES_EXTRACT, entity-based extraction is capped at this count.
MAX_ENTITIES_EXTRACT = 30000
# Entity count above which geometric method is automatically downgraded to entity method.
LARGE_ASSEMBLY_ENTITY_THRESHOLD = 10000

# PythonOCC imports
try:
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face, TopoDS_Edge
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
    from OCC.Core.GeomAbs import (
        GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Sphere,
        GeomAbs_Cone, GeomAbs_Torus, GeomAbs_Circle, GeomAbs_Line
    )
    from OCC.Core.gp import gp_Pnt, gp_Vec, gp_Dir, gp_Ax1
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties, brepgprop_SurfaceProperties
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.Bnd import Bnd_Box
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False
    logging.warning("PythonOCC not available. Feature extraction will be limited.")

from app.step_view_pro.models import STEPEntity
from app.extensions import db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers for positional STEP entity_attributes lists
# entity_attributes is stored as a raw list of STEP parameter strings/values,
# NOT a dict.  E.g. CYLINDRICAL_SURFACE('', #124, 5.0) → ["''", '#124', '5.0']
# ---------------------------------------------------------------------------

def _param_float(attrs, idx: int) -> Optional[float]:
    """Safely extract a float from a positional entity_attributes list."""
    if not isinstance(attrs, (list, tuple)) or idx >= len(attrs):
        return None
    try:
        v = attrs[idx]
        if isinstance(v, str):
            v = v.strip().strip("'\"")
        return float(v)
    except (TypeError, ValueError):
        return None


def _param_ref(attrs, idx: int) -> Optional[str]:
    """Safely extract a reference token (e.g. '#124') from entity_attributes."""
    if not isinstance(attrs, (list, tuple)) or idx >= len(attrs):
        return None
    v = attrs[idx]
    return str(v).strip() if v is not None else None


@dataclass
class ManufacturingFeature:
    """Representación de un feature de manufactura detectado"""
    feature_id: str  # UUID único
    feature_type: str  # HOLE, POCKET, SLOT, BOSS, FILLET, CHAMFER
    feature_subtype: Optional[str] = None  # THROUGH_HOLE, BLIND_HOLE, etc.

    # Propiedades geométricas
    position: Optional[Tuple[float, float, float]] = None
    direction: Optional[Tuple[float, float, float]] = None
    dimensions: Optional[Dict[str, float]] = None

    # Entidades STEP relacionadas
    entity_ids: List[int] = None
    primary_entity_id: Optional[int] = None

    # Metadata
    confidence: float = 1.0  # 0.0 - 1.0
    extraction_method: str = "geometric_analysis"
    notes: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class FeatureExtractor:
    """
    Extrae automáticamente manufacturing features de geometrías STEP
    """

    def __init__(self, header_id: str):
        """
        Args:
            header_id: UUID del STEP file header
        """
        self.header_id = header_id
        self.features: List[ManufacturingFeature] = []

        if not PYTHONOCC_AVAILABLE:
            logger.warning("PythonOCC no disponible, FeatureExtractor funcionará en modo limitado")
            self.available = False
        else:
            self.available = True

    def extract_from_file(self, filepath: str) -> List[ManufacturingFeature]:
        """
        Extrae features de un archivo STEP usando PythonOCC.

        Para ensamblajes grandes (> MAX_FACES_GEOMETRIC caras) se analiza una
        muestra representativa en lugar de todas las caras, evitando OOM/timeout.

        Returns:
            Lista de ManufacturingFeature detectados
        """
        if not self.available:
            logger.warning("PythonOCC no disponible, retornando lista vacía de features")
            return []

        logger.info(f"Extracting features from: {filepath}")

        shape = self._load_step_file(filepath)
        if not shape:
            logger.error("Failed to load STEP file")
            return []

        faces = self._get_all_faces(shape)
        total_faces = len(faces)
        sampled = False

        if total_faces > MAX_FACES_GEOMETRIC:
            # Sample evenly so all regions of the assembly are represented
            step = max(1, total_faces // MAX_FACES_GEOMETRIC)
            faces = faces[::step][:MAX_FACES_GEOMETRIC]
            sampled = True
            logger.warning(
                f"Large assembly: {total_faces} faces — sampling {len(faces)} "
                f"(1 in {step}) for feature detection"
            )
        else:
            logger.info(f"Analyzing {total_faces} faces")

        self._detect_holes(faces, shape)
        self._detect_pockets(faces, shape)
        self._detect_slots(faces, shape)
        self._detect_bosses(faces, shape)
        self._detect_fillets_and_chamfers(shape)

        logger.info(
            f"Detected {len(self.features)} features "
            f"({'sampled' if sampled else 'full'} analysis, "
            f"{total_faces} total faces)"
        )
        # Store sampling metadata so callers can surface it
        self._total_faces = total_faces
        self._sampled = sampled
        return self.features

    def extract_from_entities(self) -> List[ManufacturingFeature]:
        """
        Extrae features basándose en entidades STEP ya parseadas en BD.

        Pagina la consulta en lotes de 5 000 filas para evitar cargar cientos
        de miles de registros de golpe. Está limitado a MAX_ENTITIES_EXTRACT
        entidades en total para mantener tiempos de respuesta razonables.

        Returns:
            Lista de ManufacturingFeature detectados
        """
        logger.info(f"Extracting features from entities for header {self.header_id}")

        total_in_db = STEPEntity.query.filter_by(header_id=self.header_id).count()
        cap = min(total_in_db, MAX_ENTITIES_EXTRACT)

        if total_in_db > MAX_ENTITIES_EXTRACT:
            logger.warning(
                f"Large assembly: {total_in_db} entities — capping analysis "
                f"at {MAX_ENTITIES_EXTRACT}"
            )

        # Paginar en lotes para no cargar todo en RAM
        _BATCH = 5000
        entities_by_type: Dict[str, list] = {}
        offset = 0

        while offset < cap:
            batch = (
                STEPEntity.query
                .filter_by(header_id=self.header_id)
                .limit(_BATCH)
                .offset(offset)
                .all()
            )
            if not batch:
                break
            for entity in batch:
                entities_by_type.setdefault(entity.entity_type, []).append(entity)
            offset += _BATCH

        logger.info(
            f"Loaded {offset} / {total_in_db} entities across "
            f"{len(entities_by_type)} types"
        )

        self._detect_holes_from_entities(entities_by_type)
        self._detect_pockets_from_entities(entities_by_type)
        self._detect_chamfers_from_entities(entities_by_type)
        self._detect_fillets_from_entities(entities_by_type)

        logger.info(f"Detected {len(self.features)} features from entities")
        return self.features

    def _load_step_file(self, filepath: str):
        """Carga archivo STEP y retorna la geometría"""
        if not PYTHONOCC_AVAILABLE:
            logger.warning("PythonOCC no disponible, retornando None")
            return None

        try:
            step_reader = STEPControl_Reader()
            status = step_reader.ReadFile(filepath)

            if status != 1:  # IFSelect_RetDone
                logger.error(f"Error reading STEP file: {filepath}")
                return None

            step_reader.TransferRoots()
            shape = step_reader.OneShape()
            return shape

        except Exception as e:
            logger.exception(f"Error loading STEP file: {e}")
            return None

    def _get_all_faces(self, shape):
        """Obtiene todas las caras de una geometría"""
        if not PYTHONOCC_AVAILABLE:
            logger.warning("PythonOCC no disponible, retornando lista vacía")
            return []

        faces = []
        explorer = TopExp_Explorer(shape, TopAbs_FACE)

        while explorer.More():
            face = explorer.Current()
            faces.append(TopoDS_Face.DownCast(face))
            explorer.Next()

        return faces

    def _detect_holes(self, faces, shape):
        """
        Detecta agujeros cilíndricos (through holes y blind holes)

        Criterios:
        - Superficie cilíndrica
        - Eje vertical o con orientación definida
        - Diámetro consistente
        """
        cylindrical_faces = []

        for face in faces:
            surface = BRepAdaptor_Surface(face)

            if surface.GetType() == GeomAbs_Cylinder:
                cylindrical_faces.append((face, surface))

        logger.debug(f"Found {len(cylindrical_faces)} cylindrical faces")

        # Analizar cada superficie cilíndrica
        for i, (face, surface) in enumerate(cylindrical_faces):
            try:
                # Obtener parámetros del cilindro
                cylinder = surface.Cylinder()
                axis = cylinder.Axis()
                radius = cylinder.Radius()

                # Posición del eje
                location = axis.Location()
                position = (location.X(), location.Y(), location.Z())

                # Dirección del eje
                direction_gp = axis.Direction()
                direction = (direction_gp.X(), direction_gp.Y(), direction_gp.Z())

                # Calcular profundidad (aproximación usando bounding box de la cara)
                bbox = Bnd_Box()
                brepbndlib_Add(face, bbox)
                xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
                depth = max(xmax - xmin, ymax - ymin, zmax - zmin)

                # Determinar si es pasante o ciego
                # (Simplificación: si atraviesa toda la pieza es pasante)
                is_through = depth > radius * 4  # Heurística simple

                feature = ManufacturingFeature(
                    feature_id=f"HOLE_{i:03d}",
                    feature_type="HOLE",
                    feature_subtype="THROUGH_HOLE" if is_through else "BLIND_HOLE",
                    position=position,
                    direction=direction,
                    dimensions={
                        "diameter": radius * 2,
                        "radius": radius,
                        "depth": depth
                    },
                    entity_ids=[],  # Se llenará si se correlaciona con entidades
                    confidence=0.8,
                    extraction_method="geometric_cylinder_analysis"
                )

                self.features.append(feature)
                logger.debug(f"Detected hole: Ø{radius*2:.2f}mm, depth={depth:.2f}mm")

            except Exception as e:
                logger.debug(f"Error analyzing cylindrical face: {e}")

    def _detect_pockets(self, faces, shape):
        """
        Detecta cavidades (pockets)

        Criterios:
        - Conjunto de caras que forman una depresión
        - Base plana o curva
        - Paredes laterales
        """
        planar_faces = []

        for face in faces:
            surface = BRepAdaptor_Surface(face)
            if surface.GetType() == GeomAbs_Plane:
                planar_faces.append((face, surface))

        # Heurística simple: caras planas horizontales rodeadas de paredes
        # En producción, esto requeriría análisis topológico más complejo

        logger.debug(f"Found {len(planar_faces)} planar faces (potential pocket bases)")

    def _detect_slots(self, faces, shape):
        """
        Detecta ranuras (slots)

        Criterios:
        - Forma alargada
        - Fondo plano o cilíndrico
        - Extremos semicirculares o rectos
        """
        # Implementación simplificada
        pass

    def _detect_bosses(self, faces, shape):
        """
        Detecta salientes cilíndricos (bosses)

        Similar a holes pero orientación inversa (protuberancia vs cavidad)
        """
        # Implementación simplificada
        pass

    def _detect_fillets_and_chamfers(self, shape):
        """
        Detecta redondeos (fillets) y chaflanes (chamfers)

        Criterios:
        - Fillets: superficies cilíndricas o esféricas de radio pequeño
        - Chamfers: caras planas en ángulo conectando dos superficies
        """
        explorer = TopExp_Explorer(shape, TopAbs_EDGE)
        fillet_count = 0

        while explorer.More():
            edge = explorer.Current()
            curve = BRepAdaptor_Curve(TopoDS_Edge.DownCast(edge))

            # Detectar arcos circulares (potenciales fillets)
            if curve.GetType() == GeomAbs_Circle:
                circle = curve.Circle()
                radius = circle.Radius()

                # Fillets típicamente tienen radios pequeños (< 10mm)
                if radius < 10.0:
                    fillet_count += 1

            explorer.Next()

        if fillet_count > 0:
            logger.debug(f"Detected {fillet_count} potential fillets")

    def _detect_holes_from_entities(self, entities_by_type: Dict):
        """
        Detecta holes desde CYLINDRICAL_SURFACE entities.
        entity_attributes positional layout: [name, placement_ref, radius]
        """
        _MIN_R = 0.5    # mm – ignore noise
        _MAX_R = 150.0  # mm – beyond this it's more likely a boss/barrel

        cylindrical_surfaces = entities_by_type.get('CYLINDRICAL_SURFACE', [])
        logger.debug(
            f"Entity hole detection: {len(cylindrical_surfaces)} CYLINDRICAL_SURFACE entities"
        )

        detected = 0
        for entity in cylindrical_surfaces:
            try:
                attrs = entity.entity_attributes  # positional list, NOT a dict
                radius = _param_float(attrs, 2)   # index 2 = radius
                if radius is None or not (_MIN_R <= radius <= _MAX_R):
                    continue

                feature = ManufacturingFeature(
                    feature_id=f"HOLE_{entity.entity_id}",
                    feature_type="HOLE",
                    feature_subtype="CYLINDRICAL_FEATURE",
                    dimensions={
                        "diameter": radius * 2,
                        "radius": radius,
                    },
                    entity_ids=[entity.entity_id],
                    primary_entity_id=entity.entity_id,
                    confidence=0.75,
                    extraction_method="entity_pattern_matching",
                    notes=f"CYLINDRICAL_SURFACE #{entity.entity_id} r={radius:.2f}mm"
                )
                self.features.append(feature)
                detected += 1
            except Exception as e:
                logger.debug(f"Error analyzing CYLINDRICAL_SURFACE #{entity.entity_id}: {e}")

        logger.info(f"Entity holes detected: {detected}")

    def _detect_pockets_from_entities(self, entities_by_type: Dict):
        """
        Estimates pocket count from PLANE entity surplus.
        A basic box has 6 exterior PLANE faces; every 4 additional planes ~ 1 pocket
        (floor + 3 walls minimum). Emits a single aggregated feature to avoid inflating
        counts since we cannot determine individual pocket boundaries without topology.
        """
        plane_count = len(entities_by_type.get('PLANE', []))
        estimated_pockets = max(0, (plane_count - 6)) // 4

        if estimated_pockets <= 0:
            logger.debug(f"Entity pockets: {plane_count} PLANEs → no pockets estimated")
            return

        feature = ManufacturingFeature(
            feature_id="POCKET_entity_aggregate",
            feature_type="POCKET",
            feature_subtype="ESTIMATED",
            dimensions={"estimated_count": estimated_pockets, "plane_count": plane_count},
            entity_ids=[],
            confidence=0.4,
            extraction_method="entity_pattern_matching",
            notes=f"Estimated from {plane_count} PLANE entities (heuristic: (planes-6)//4)"
        )
        self.features.append(feature)
        logger.info(
            f"Entity pockets: {plane_count} PLANEs → {estimated_pockets} estimated pockets"
        )

    def _detect_chamfers_from_entities(self, entities_by_type: Dict):
        """
        Detecta chamfers desde CONICAL_SURFACE entities.
        entity_attributes: [name, placement_ref, radius, semi_angle_radians]
        A semi-angle between 20° and 70° indicates a chamfer face.
        """
        _CHAMFER_MIN_DEG = 20.0
        _CHAMFER_MAX_DEG = 70.0

        conical_surfaces = entities_by_type.get('CONICAL_SURFACE', [])
        logger.debug(
            f"Entity chamfer detection: {len(conical_surfaces)} CONICAL_SURFACE entities"
        )

        detected = 0
        for entity in conical_surfaces:
            try:
                attrs = entity.entity_attributes
                semi_angle_rad = _param_float(attrs, 3)  # index 3 = semi_angle
                if semi_angle_rad is None:
                    continue
                semi_angle_deg = math.degrees(semi_angle_rad)
                if not (_CHAMFER_MIN_DEG <= semi_angle_deg <= _CHAMFER_MAX_DEG):
                    continue

                radius = _param_float(attrs, 2) or 0.0
                feature = ManufacturingFeature(
                    feature_id=f"CHAMFER_{entity.entity_id}",
                    feature_type="CHAMFER",
                    feature_subtype="CONICAL",
                    dimensions={
                        "semi_angle_deg": round(semi_angle_deg, 2),
                        "base_radius": radius,
                    },
                    entity_ids=[entity.entity_id],
                    primary_entity_id=entity.entity_id,
                    confidence=0.8,
                    extraction_method="entity_pattern_matching",
                    notes=f"CONICAL_SURFACE #{entity.entity_id} angle={semi_angle_deg:.1f}°"
                )
                self.features.append(feature)
                detected += 1
            except Exception as e:
                logger.debug(f"Error analyzing CONICAL_SURFACE #{entity.entity_id}: {e}")

        logger.info(f"Entity chamfers detected: {detected}")

    def _detect_fillets_from_entities(self, entities_by_type: Dict):
        """
        Detecta fillets desde TOROIDAL_SURFACE entities.
        entity_attributes: [name, placement_ref, major_radius, minor_radius]
        minor_radius is the fillet blend radius; capped at 12mm (same as advanced extractor).
        """
        _MAX_FILLET_R = 12.0

        toroidal_surfaces = entities_by_type.get('TOROIDAL_SURFACE', [])
        logger.debug(
            f"Entity fillet detection: {len(toroidal_surfaces)} TOROIDAL_SURFACE entities"
        )

        detected = 0
        for entity in toroidal_surfaces:
            try:
                attrs = entity.entity_attributes
                minor_radius = _param_float(attrs, 3)  # index 3 = minor_radius (fillet r)
                if minor_radius is None or minor_radius > _MAX_FILLET_R:
                    continue

                major_radius = _param_float(attrs, 2) or 0.0
                feature = ManufacturingFeature(
                    feature_id=f"FILLET_{entity.entity_id}",
                    feature_type="FILLET",
                    feature_subtype="TOROIDAL",
                    dimensions={
                        "radius": minor_radius,
                        "major_radius": major_radius,
                    },
                    entity_ids=[entity.entity_id],
                    primary_entity_id=entity.entity_id,
                    confidence=0.85,
                    extraction_method="entity_pattern_matching",
                    notes=f"TOROIDAL_SURFACE #{entity.entity_id} r={minor_radius:.2f}mm"
                )
                self.features.append(feature)
                detected += 1
            except Exception as e:
                logger.debug(f"Error analyzing TOROIDAL_SURFACE #{entity.entity_id}: {e}")

        logger.info(f"Entity fillets detected: {detected}")

    def save_to_database(self):
        """
        Guarda los features detectados en las entidades correspondientes

        Actualiza el campo manufacturing_feature de STEPEntity
        """
        if not self.features:
            logger.warning("No features to save")
            return 0

        updated_count = 0

        for feature in self.features:
            if not feature.entity_ids:
                continue

            # Actualizar entidad primaria
            if feature.primary_entity_id:
                entity = STEPEntity.query.filter_by(
                    header_id=self.header_id,
                    entity_id=feature.primary_entity_id
                ).first()

                if entity:
                    entity.manufacturing_feature = feature.feature_id
                    entity.feature_metadata = feature.to_dict()
                    updated_count += 1

        try:
            db.session.commit()
            logger.info(f"Saved {updated_count} features to database")
            return updated_count
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error saving features: {e}")
            return 0


def extract_features_for_file(header_id: str, filepath: str, method: str = "geometric") -> Dict:
    """
    Extraer features de manufactura con selección automática de método.

    Para ensamblajes grandes (> LARGE_ASSEMBLY_ENTITY_THRESHOLD entidades en DB)
    el método geométrico se degrada automáticamente a 'entity' para evitar
    timeouts/OOM con PythonOCC procesando toda la geometría.

    Args:
        header_id: UUID del header
        filepath: Ruta al archivo STEP
        method: "geometric" o "entity". "geometric" puede ser degradado.

    Returns:
        Dict con resultados + metadata de análisis (method_used, sampled, warnings).
    """
    entity_count = STEPEntity.query.filter_by(header_id=header_id).count()

    effective_method = method
    warnings: List[str] = []

    if method == "geometric" and entity_count > LARGE_ASSEMBLY_ENTITY_THRESHOLD:
        effective_method = "entity"
        warnings.append(
            f"Large assembly ({entity_count} entities): geometric method would be too slow. "
            f"Switched to entity-based extraction automatically."
        )
        logger.warning(warnings[-1])

    if effective_method == "geometric" and not PYTHONOCC_AVAILABLE:
        effective_method = "entity"
        warnings.append("PythonOCC not available — using entity method.")

    extractor = FeatureExtractor(header_id)

    if effective_method == "geometric":
        features = extractor.extract_from_file(filepath)
        sampled = getattr(extractor, '_sampled', False)
        total_faces = getattr(extractor, '_total_faces', None)
        if sampled:
            warnings.append(
                f"Geometry sampled: {total_faces} total faces, "
                f"only {MAX_FACES_GEOMETRIC} analyzed."
            )
    else:
        features = extractor.extract_from_entities()
        sampled = entity_count > MAX_ENTITIES_EXTRACT
        if sampled:
            warnings.append(
                f"Entity analysis capped at {MAX_ENTITIES_EXTRACT} "
                f"of {entity_count} total entities."
            )

    saved_count = extractor.save_to_database()

    features_by_type: Dict[str, list] = {}
    for feature in features:
        features_by_type.setdefault(feature.feature_type, []).append(feature.to_dict())

    return {
        "total_features": len(features),
        "features_by_type": features_by_type,
        "saved_to_db": saved_count,
        "extraction_method": effective_method,
        "requested_method": method,
        "entity_count": entity_count,
        "sampled": sampled,
        "warnings": warnings,
        "features": [f.to_dict() for f in features],
    }


logger.info("OK Feature Extractor module loaded")
