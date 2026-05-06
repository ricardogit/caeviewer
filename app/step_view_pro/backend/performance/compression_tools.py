"""
Compression Tools - Compresión y chunking de datos para optimización
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Compresión gzip/bz2/lzma
- Chunking de grandes archivos
- Streaming de datos
- Deduplicación
"""

import logging
import gzip
import bz2
import lzma
import hashlib
import json
from typing import Any, Optional, Iterator, List
from pathlib import Path

logger = logging.getLogger(__name__)


class CompressionTools:
    """
    Herramientas de compresión de datos
    """

    ALGORITHMS = {
        'gzip': {
            'compress': gzip.compress,
            'decompress': gzip.decompress,
            'level_param': 'compresslevel'
        },
        'bz2': {
            'compress': bz2.compress,
            'decompress': bz2.decompress,
            'level_param': 'compresslevel'
        },
        'lzma': {
            'compress': lzma.compress,
            'decompress': lzma.decompress,
            'level_param': 'preset'
        }
    }

    @staticmethod
    def compress(data: bytes, algorithm: str = 'gzip', level: int = 6) -> bytes:
        """
        Comprime datos

        Args:
            data: Datos a comprimir
            algorithm: Algoritmo ('gzip', 'bz2', 'lzma')
            level: Nivel de compresión (1-9)

        Returns:
            Datos comprimidos
        """
        if algorithm not in CompressionTools.ALGORITHMS:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        algo = CompressionTools.ALGORITHMS[algorithm]
        compress_func = algo['compress']
        level_param = algo['level_param']

        compressed = compress_func(data, **{level_param: level})

        original_size = len(data)
        compressed_size = len(compressed)
        ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0

        logger.debug(
            f"Compressed {original_size} → {compressed_size} bytes "
            f"({ratio:.1f}% reduction) using {algorithm}"
        )

        return compressed

    @staticmethod
    def decompress(data: bytes, algorithm: str = 'gzip') -> bytes:
        """
        Descomprime datos

        Args:
            data: Datos comprimidos
            algorithm: Algoritmo usado

        Returns:
            Datos descomprimidos
        """
        if algorithm not in CompressionTools.ALGORITHMS:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        algo = CompressionTools.ALGORITHMS[algorithm]
        decompress_func = algo['decompress']

        decompressed = decompress_func(data)

        logger.debug(
            f"Decompressed {len(data)} → {len(decompressed)} bytes "
            f"using {algorithm}"
        )

        return decompressed

    @staticmethod
    def compress_json(data: Any, algorithm: str = 'gzip', level: int = 6) -> bytes:
        """
        Comprime objeto JSON

        Args:
            data: Objeto serializable a JSON
            algorithm: Algoritmo de compresión
            level: Nivel de compresión

        Returns:
            JSON comprimido
        """
        json_bytes = json.dumps(data).encode('utf-8')
        return CompressionTools.compress(json_bytes, algorithm, level)

    @staticmethod
    def decompress_json(data: bytes, algorithm: str = 'gzip') -> Any:
        """
        Descomprime JSON

        Args:
            data: JSON comprimido
            algorithm: Algoritmo usado

        Returns:
            Objeto deserializado
        """
        json_bytes = CompressionTools.decompress(data, algorithm)
        return json.loads(json_bytes.decode('utf-8'))

    @staticmethod
    def chunk_file(file_path: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """
        Lee archivo en chunks

        Args:
            file_path: Ruta al archivo
            chunk_size: Tamaño del chunk en bytes (default: 1MB)

        Yields:
            Chunks del archivo
        """
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    @staticmethod
    def compress_file(input_path: str, output_path: str,
                     algorithm: str = 'gzip', level: int = 6,
                     chunk_size: int = 1024 * 1024) -> dict:
        """
        Comprime archivo completo

        Args:
            input_path: Archivo de entrada
            output_path: Archivo de salida
            algorithm: Algoritmo
            level: Nivel de compresión
            chunk_size: Tamaño de chunks para lectura

        Returns:
            Dict con estadísticas
        """
        original_size = Path(input_path).stat().st_size

        if algorithm == 'gzip':
            open_func = lambda f: gzip.open(f, 'wb', compresslevel=level)
        elif algorithm == 'bz2':
            open_func = lambda f: bz2.open(f, 'wb', compresslevel=level)
        elif algorithm == 'lzma':
            open_func = lambda f: lzma.open(f, 'wb', preset=level)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        with open_func(output_path) as f_out:
            for chunk in CompressionTools.chunk_file(input_path, chunk_size):
                f_out.write(chunk)

        compressed_size = Path(output_path).stat().st_size
        ratio = (1 - compressed_size / original_size) * 100

        logger.info(
            f"File compressed: {input_path} → {output_path} "
            f"({original_size} → {compressed_size} bytes, {ratio:.1f}% reduction)"
        )

        return {
            'original_size': original_size,
            'compressed_size': compressed_size,
            'ratio_percent': round(ratio, 2),
            'algorithm': algorithm,
            'level': level
        }

    @staticmethod
    def calculate_hash(data: bytes) -> str:
        """
        Calcula hash SHA-256 de datos

        Args:
            data: Datos

        Returns:
            Hash hexadecimal
        """
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def deduplicate(items: List[Any], key_func=None) -> List[Any]:
        """
        Deduplica lista de items

        Args:
            items: Lista de items
            key_func: Función para extraer key (default: hash del item)

        Returns:
            Lista sin duplicados
        """
        seen = set()
        result = []

        for item in items:
            if key_func:
                key = key_func(item)
            else:
                # Usar hash del item
                key = hashlib.md5(str(item).encode()).hexdigest()

            if key not in seen:
                seen.add(key)
                result.append(item)

        removed = len(items) - len(result)
        if removed > 0:
            logger.debug(f"Deduplicated: removed {removed} duplicate items")

        return result


class StreamProcessor:
    """
    Procesador de streams de datos
    """

    @staticmethod
    def process_in_chunks(data_source: Iterator, processor_func, chunk_size: int = 100):
        """
        Procesa datos en chunks

        Args:
            data_source: Iterador de datos
            processor_func: Función de procesamiento
            chunk_size: Tamaño del chunk

        Yields:
            Resultados procesados
        """
        chunk = []

        for item in data_source:
            chunk.append(item)

            if len(chunk) >= chunk_size:
                yield processor_func(chunk)
                chunk = []

        # Procesar último chunk
        if chunk:
            yield processor_func(chunk)

    @staticmethod
    def batch_generator(items: List, batch_size: int):
        """
        Genera batches de items

        Args:
            items: Lista de items
            batch_size: Tamaño del batch

        Yields:
            Batches
        """
        for i in range(0, len(items), batch_size):
            yield items[i:i + batch_size]


logger.info("OK Compression Tools module loaded")
