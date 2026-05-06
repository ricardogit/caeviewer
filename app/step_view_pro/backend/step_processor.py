"""
STEP Processor - Funciones de bajo nivel para procesar geometría STEP
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# PythonOCC imports
try:
    from OCC.Extend.DataExchange import read_step_file
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False
    logger.warning("PythonOCC not available. STEP processing will be limited.")


def load_step_shape(file_path: str, shape_index: int = 0) -> Optional['TopoDS_Shape']:
    """
    Carga una forma desde un archivo STEP

    Args:
        file_path: Ruta al archivo STEP
        shape_index: Índice de la forma a cargar (0 = primera)

    Returns:
        TopoDS_Shape o None si falla
    """
    if not PYTHONOCC_AVAILABLE:
        raise RuntimeError("PythonOCC required for STEP processing")

    try:
        # Leer archivo STEP
        shape = read_step_file(file_path)

        if not shape:
            logger.error(f"Could not read STEP file: {file_path}")
            return None

        # Si shape_index > 0, intentar extraer una forma específica
        if shape_index > 0:
            shapes = []

            # Explorar sólidos
            explorer = TopExp_Explorer(shape, TopAbs_SOLID)
            while explorer.More():
                shapes.append(explorer.Current())
                explorer.Next()

            # Si no hay sólidos, explorar shells
            if not shapes:
                explorer = TopExp_Explorer(shape, TopAbs_SHELL)
                while explorer.More():
                    shapes.append(explorer.Current())
                    explorer.Next()

            # Si no hay shells, explorar faces
            if not shapes:
                explorer = TopExp_Explorer(shape, TopAbs_FACE)
                while explorer.More():
                    shapes.append(explorer.Current())
                    explorer.Next()

            if shape_index < len(shapes):
                return shapes[shape_index]
            else:
                logger.warning(f"shape_index {shape_index} out of range (found {len(shapes)} shapes)")
                return shape

        return shape

    except Exception as e:
        logger.exception(f"Error loading STEP shape: {e}")
        return None


def get_shape_count(file_path: str) -> dict:
    """
    Cuenta el número de formas en un archivo STEP

    Args:
        file_path: Ruta al archivo STEP

    Returns:
        Dict con conteos de solids, shells, faces
    """
    if not PYTHONOCC_AVAILABLE:
        raise RuntimeError("PythonOCC required for STEP processing")

    try:
        shape = read_step_file(file_path)

        if not shape:
            return {'solids': 0, 'shells': 0, 'faces': 0}

        counts = {
            'solids': 0,
            'shells': 0,
            'faces': 0
        }

        # Contar sólidos
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            counts['solids'] += 1
            explorer.Next()

        # Contar shells
        explorer = TopExp_Explorer(shape, TopAbs_SHELL)
        while explorer.More():
            counts['shells'] += 1
            explorer.Next()

        # Contar faces
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            counts['faces'] += 1
            explorer.Next()

        return counts

    except Exception as e:
        logger.exception(f"Error counting shapes: {e}")
        return {'solids': 0, 'shells': 0, 'faces': 0}


logger.info("OK STEP Processor module loaded")
