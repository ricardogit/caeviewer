"""
Measurement Tools - Herramientas de medición 3D para geometrías STEP
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Distance (punto a punto, punto a plano, plano a plano)
- Angle (entre vectores, entre planos)
- Area (superficie)
- Volume (sólidos)
- Bounding Box
"""

import logging
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import numpy as np

# PythonOCC imports
try:
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties, brepgprop_SurfaceProperties
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.gp import gp_Pnt, gp_Vec
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.GeomAbs import GeomAbs_Plane
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False
    logging.warning("PythonOCC not available. Measurement tools will be limited.")

logger = logging.getLogger(__name__)


@dataclass
class Measurement:
    """Representación de una medición"""
    measurement_id: str
    measurement_type: str  # DISTANCE, ANGLE, AREA, VOLUME, BBOX

    # Valor y unidades
    value: float
    unit: str = 'mm'

    # Puntos de la medición
    points: List[Tuple[float, float, float]] = None

    # Metadata
    label: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class MeasurementTools:
    """
    Herramientas de medición 3D
    """

    @staticmethod
    def distance_point_to_point(p1: Tuple[float, float, float],
                                  p2: Tuple[float, float, float]) -> float:
        """
        Calcula distancia entre dos puntos

        Args:
            p1: Punto 1 (x, y, z)
            p2: Punto 2 (x, y, z)

        Returns:
            Distancia en unidades del modelo
        """
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        dz = p2[2] - p1[2]

        distance = math.sqrt(dx*dx + dy*dy + dz*dz)

        logger.debug(f"Distance P1→P2: {distance:.4f}")
        return distance

    @staticmethod
    def distance_point_to_plane(point: Tuple[float, float, float],
                                 plane_point: Tuple[float, float, float],
                                 plane_normal: Tuple[float, float, float]) -> float:
        """
        Calcula distancia de punto a plano

        Args:
            point: Punto (x, y, z)
            plane_point: Punto en el plano
            plane_normal: Normal del plano (nx, ny, nz)

        Returns:
            Distancia perpendicular
        """
        # Vector del plano al punto
        dx = point[0] - plane_point[0]
        dy = point[1] - plane_point[1]
        dz = point[2] - plane_point[2]

        # Normalizar la normal
        nx, ny, nz = plane_normal
        norm_length = math.sqrt(nx*nx + ny*ny + nz*nz)
        nx /= norm_length
        ny /= norm_length
        nz /= norm_length

        # Proyección sobre la normal = distancia
        distance = abs(dx*nx + dy*ny + dz*nz)

        logger.debug(f"Distance point→plane: {distance:.4f}")
        return distance

    @staticmethod
    def angle_between_vectors(v1: Tuple[float, float, float],
                               v2: Tuple[float, float, float],
                               degrees: bool = True) -> float:
        """
        Calcula ángulo entre dos vectores

        Args:
            v1: Vector 1
            v2: Vector 2
            degrees: Retornar en grados (True) o radianes (False)

        Returns:
            Ángulo
        """
        # Convertir a arrays numpy
        v1_arr = np.array(v1)
        v2_arr = np.array(v2)

        # Normalizar
        v1_norm = v1_arr / np.linalg.norm(v1_arr)
        v2_norm = v2_arr / np.linalg.norm(v2_arr)

        # Producto punto
        dot_product = np.dot(v1_norm, v2_norm)

        # Clamp para evitar errores numéricos
        dot_product = np.clip(dot_product, -1.0, 1.0)

        # Ángulo en radianes
        angle_rad = math.acos(dot_product)

        if degrees:
            angle = math.degrees(angle_rad)
        else:
            angle = angle_rad

        logger.debug(f"Angle between vectors: {angle:.2f}°")
        return angle

    @staticmethod
    def angle_between_planes(normal1: Tuple[float, float, float],
                              normal2: Tuple[float, float, float],
                              degrees: bool = True) -> float:
        """
        Calcula ángulo entre dos planos

        Args:
            normal1: Normal del plano 1
            normal2: Normal del plano 2
            degrees: Retornar en grados

        Returns:
            Ángulo
        """
        # El ángulo entre planos es el ángulo entre sus normales
        return MeasurementTools.angle_between_vectors(normal1, normal2, degrees)

    @staticmethod
    def compute_area_from_shape(shape: 'TopoDS_Shape') -> float:
        """
        Calcula área de una superficie usando PythonOCC

        Args:
            shape: Forma TopoDS (face o shape)

        Returns:
            Área en unidades²
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for area calculation")

        props = GProp_GProps()
        brepgprop_SurfaceProperties(shape, props)
        area = props.Mass()

        logger.debug(f"Surface area: {area:.4f}")
        return area

    @staticmethod
    def compute_volume_from_shape(shape: 'TopoDS_Shape') -> float:
        """
        Calcula volumen de un sólido usando PythonOCC

        Args:
            shape: Forma TopoDS (solid)

        Returns:
            Volumen en unidades³
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for volume calculation")

        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
        volume = props.Mass()

        logger.debug(f"Volume: {volume:.4f}")
        return volume

    @staticmethod
    def compute_bounding_box(shape: 'TopoDS_Shape') -> Dict:
        """
        Calcula bounding box de una geometría

        Args:
            shape: Forma TopoDS

        Returns:
            Dict con min, max, dimensions
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for bounding box")

        bbox = Bnd_Box()
        brepbndlib_Add(shape, bbox)

        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        dimensions = {
            'min': [xmin, ymin, zmin],
            'max': [xmax, ymax, zmax],
            'dimensions': [xmax - xmin, ymax - ymin, zmax - zmin],
            'center': [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2],
            'diagonal': math.sqrt(
                (xmax - xmin)**2 + (ymax - ymin)**2 + (zmax - zmin)**2
            )
        }

        logger.debug(f"Bounding box: {dimensions['dimensions']}")
        return dimensions

    @staticmethod
    def compute_center_of_mass(shape: 'TopoDS_Shape') -> Tuple[float, float, float]:
        """
        Calcula centro de masa de un sólido

        Args:
            shape: Forma TopoDS

        Returns:
            (x, y, z) del centro de masa
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for center of mass")

        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)

        com = props.CentreOfMass()
        center = (com.X(), com.Y(), com.Z())

        logger.debug(f"Center of mass: {center}")
        return center

    @staticmethod
    def compute_moments_of_inertia(shape: 'TopoDS_Shape') -> Dict:
        """
        Calcula momentos de inercia

        Args:
            shape: Forma TopoDS

        Returns:
            Dict con Ixx, Iyy, Izz, Ixy, Ixz, Iyz
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for moments of inertia")

        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)

        matrix = props.MatrixOfInertia()

        moments = {
            'Ixx': matrix.Value(1, 1),
            'Iyy': matrix.Value(2, 2),
            'Izz': matrix.Value(3, 3),
            'Ixy': matrix.Value(1, 2),
            'Ixz': matrix.Value(1, 3),
            'Iyz': matrix.Value(2, 3)
        }

        logger.debug(f"Moments of inertia: {moments}")
        return moments

    @staticmethod
    def create_measurement(meas_type: str,
                          value: float,
                          points: List[Tuple] = None,
                          unit: str = 'mm',
                          label: str = None) -> Measurement:
        """
        Crea objeto Measurement

        Args:
            meas_type: Tipo de medición
            value: Valor medido
            points: Puntos involucrados
            unit: Unidad
            label: Etiqueta descriptiva

        Returns:
            Measurement object
        """
        import uuid

        measurement = Measurement(
            measurement_id=str(uuid.uuid4()),
            measurement_type=meas_type,
            value=value,
            unit=unit,
            points=points,
            label=label
        )

        return measurement


def measure_distance(p1: List[float], p2: List[float]) -> Dict:
    """
    API wrapper para medir distancia

    Args:
        p1: [x, y, z]
        p2: [x, y, z]

    Returns:
        Dict con resultado
    """
    distance = MeasurementTools.distance_point_to_point(
        tuple(p1), tuple(p2)
    )

    measurement = MeasurementTools.create_measurement(
        'DISTANCE',
        distance,
        points=[tuple(p1), tuple(p2)],
        label=f"Distance: {distance:.2f} mm"
    )

    return {
        'type': 'distance',
        'value': distance,
        'unit': 'mm',
        'points': [p1, p2],
        'measurement': measurement.to_dict()
    }


def measure_angle(v1: List[float], v2: List[float]) -> Dict:
    """
    API wrapper para medir ángulo

    Args:
        v1: [x, y, z]
        v2: [x, y, z]

    Returns:
        Dict con resultado
    """
    angle = MeasurementTools.angle_between_vectors(
        tuple(v1), tuple(v2), degrees=True
    )

    measurement = MeasurementTools.create_measurement(
        'ANGLE',
        angle,
        points=[tuple(v1), tuple(v2)],
        unit='degrees',
        label=f"Angle: {angle:.2f}°"
    )

    return {
        'type': 'angle',
        'value': angle,
        'unit': 'degrees',
        'vectors': [v1, v2],
        'measurement': measurement.to_dict()
    }


logger.info("OK Measurement Tools module loaded")
