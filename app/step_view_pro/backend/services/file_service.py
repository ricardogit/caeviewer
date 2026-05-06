"""
File Service - Gestión de archivos del sistema
==============================================

Servicio para manejo de archivos: guardado, hashing, limpieza, etc.
"""

import os
import hashlib
import shutil
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FileService:
    """
    Servicio para gestión de archivos
    """

    def __init__(self, upload_dir='data/uploads', temp_dir='data/temp'):
        """
        Inicializar servicio de archivos

        Args:
            upload_dir: Directorio para archivos subidos
            temp_dir: Directorio para archivos temporales
        """
        self.upload_dir = upload_dir
        self.temp_dir = temp_dir

        # Crear directorios si no existen
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)

        logger.info(f"FileService initialized: upload_dir={upload_dir}, temp_dir={temp_dir}")

    def calculate_file_hash(self, filepath: str, algorithm='sha256') -> str:
        """
        Calcular hash de un archivo

        Args:
            filepath: Ruta al archivo
            algorithm: Algoritmo de hash (sha256, md5, etc.)

        Returns:
            Hash del archivo como string hexadecimal

        Raises:
            FileNotFoundError: Si el archivo no existe
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        if algorithm == 'sha256':
            hash_obj = hashlib.sha256()
        elif algorithm == 'md5':
            hash_obj = hashlib.md5()
        elif algorithm == 'sha1':
            hash_obj = hashlib.sha1()
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")

        # Leer archivo en chunks para archivos grandes
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_obj.update(chunk)

        file_hash = hash_obj.hexdigest()
        logger.debug(f"Calculated {algorithm} hash for {filepath}: {file_hash}")

        return file_hash

    def save_temp_file(self, file_obj, prefix='upload') -> Tuple[str, str]:
        """
        Guardar archivo temporal

        Args:
            file_obj: Objeto de archivo (FileStorage de Flask)
            prefix: Prefijo para el nombre del archivo

        Returns:
            Tupla (filepath, filename)
        """
        import uuid

        # Generar nombre único
        ext = os.path.splitext(file_obj.filename)[1]
        temp_filename = f"{prefix}_{uuid.uuid4().hex}{ext}"
        temp_path = os.path.join(self.temp_dir, temp_filename)

        # Guardar archivo
        file_obj.save(temp_path)

        logger.info(f"Saved temp file: {temp_path}")

        return temp_path, temp_filename

    def move_to_uploads(self, temp_path: str, model_id: str, extension: str) -> str:
        """
        Mover archivo temporal a directorio de uploads definitivo

        Args:
            temp_path: Ruta del archivo temporal
            model_id: ID del modelo
            extension: Extensión del archivo

        Returns:
            Ruta final del archivo

        Raises:
            FileNotFoundError: Si el archivo temporal no existe
        """
        if not os.path.exists(temp_path):
            raise FileNotFoundError(f"Temp file not found: {temp_path}")

        # Generar nombre final
        final_filename = f"{model_id}{extension}"
        final_path = os.path.join(self.upload_dir, final_filename)

        # Mover archivo
        shutil.move(temp_path, final_path)

        logger.info(f"Moved file from {temp_path} to {final_path}")

        return final_path

    def get_file_size(self, filepath: str) -> Tuple[int, float]:
        """
        Obtener tamaño de archivo

        Args:
            filepath: Ruta al archivo

        Returns:
            Tupla (bytes, megabytes)
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        size_bytes = os.path.getsize(filepath)
        size_mb = size_bytes / (1024 * 1024)

        return size_bytes, size_mb

    def validate_step_file(self, filepath: str) -> bool:
        """
        Validar que el archivo es un STEP válido

        Args:
            filepath: Ruta al archivo

        Returns:
            True si el archivo es válido

        Raises:
            ValueError: Si el archivo no es válido
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                # Verificar header (primera línea debe ser ISO-10303-21)
                first_line = f.readline().strip()
                if not first_line.startswith('ISO-10303-21'):
                    raise ValueError('Invalid STEP header: must start with ISO-10303-21')

                # Leer hasta el final para verificar footer
                f.seek(-100, 2)  # Últimos 100 bytes
                content = f.read()
                if 'END-ISO-10303-21' not in content:
                    raise ValueError('Invalid STEP footer: missing END-ISO-10303-21')

            logger.debug(f"STEP file validated: {filepath}")
            return True

        except UnicodeDecodeError as e:
            raise ValueError(f'File encoding error: {str(e)}')

    def delete_file(self, filepath: str) -> bool:
        """
        Eliminar archivo de forma segura

        Args:
            filepath: Ruta al archivo

        Returns:
            True si se eliminó exitosamente
        """
        if not os.path.exists(filepath):
            logger.warning(f"File does not exist: {filepath}")
            return False

        try:
            os.remove(filepath)
            logger.info(f"Deleted file: {filepath}")
            return True

        except Exception as e:
            logger.error(f"Error deleting file {filepath}: {str(e)}")
            return False

    def cleanup_temp_files(self, max_age_hours: int = 24) -> int:
        """
        Limpiar archivos temporales antiguos

        Args:
            max_age_hours: Edad máxima de archivos en horas

        Returns:
            Número de archivos eliminados
        """
        if not os.path.exists(self.temp_dir):
            return 0

        deleted_count = 0
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        try:
            for filename in os.listdir(self.temp_dir):
                filepath = os.path.join(self.temp_dir, filename)

                if os.path.isfile(filepath):
                    # Verificar edad del archivo
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))

                    if file_time < cutoff_time:
                        os.remove(filepath)
                        deleted_count += 1
                        logger.debug(f"Deleted old temp file: {filename}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} temp files older than {max_age_hours}h")

            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning temp files: {str(e)}")
            return deleted_count

    def get_disk_usage(self, directory: Optional[str] = None) -> dict:
        """
        Obtener uso de disco de un directorio

        Args:
            directory: Directorio a analizar (default: upload_dir)

        Returns:
            Dict con estadísticas de uso de disco
        """
        if directory is None:
            directory = self.upload_dir

        if not os.path.exists(directory):
            return {
                'exists': False,
                'total_files': 0,
                'total_size_bytes': 0,
                'total_size_mb': 0.0
            }

        total_size = 0
        file_count = 0

        try:
            for root, dirs, files in os.walk(directory):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    if os.path.isfile(filepath):
                        total_size += os.path.getsize(filepath)
                        file_count += 1

            return {
                'exists': True,
                'directory': directory,
                'total_files': file_count,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'total_size_gb': round(total_size / (1024 * 1024 * 1024), 2)
            }

        except Exception as e:
            logger.error(f"Error calculating disk usage: {str(e)}")
            return {
                'exists': True,
                'error': str(e)
            }

    def ensure_directories(self, directories: list) -> None:
        """
        Asegurar que los directorios existan

        Args:
            directories: Lista de rutas de directorios
        """
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")

    def copy_file(self, src: str, dst: str) -> bool:
        """
        Copiar archivo de forma segura

        Args:
            src: Ruta origen
            dst: Ruta destino

        Returns:
            True si se copió exitosamente
        """
        if not os.path.exists(src):
            logger.error(f"Source file not found: {src}")
            return False

        try:
            shutil.copy2(src, dst)
            logger.info(f"Copied file from {src} to {dst}")
            return True

        except Exception as e:
            logger.error(f"Error copying file: {str(e)}")
            return False


# Instancia global del servicio
file_service = FileService()
