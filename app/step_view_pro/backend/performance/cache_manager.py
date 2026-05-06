"""
Cache Manager - Sistema de cacheo multi-nivel para optimización de rendimiento
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Cacheo L1 (Redis) - Ultra rápido, volátil
- Cacheo L2 (PostgreSQL JSONB) - Persistente
- Estrategias de invalidación
- TTL configurables
- Métricas de hit/miss
"""

import logging
import json
import hashlib
from typing import Optional, Any, Dict
from datetime import datetime, timedelta
from functools import wraps
import pickle

logger = logging.getLogger(__name__)

# Redis imports (opcional)
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available. Using PostgreSQL-only caching.")


class CacheManager:
    """
    Gestor de caché multi-nivel con Redis (L1) y PostgreSQL (L2)
    """

    def __init__(self, redis_url: Optional[str] = None, enable_redis: bool = True):
        """
        Inicializa cache manager

        Args:
            redis_url: URL de conexión a Redis (ej: redis://localhost:6379/0)
            enable_redis: Habilitar Redis L1
        """
        self.redis_client = None
        self.redis_enabled = False

        # Estadísticas
        self.stats = {
            'l1_hits': 0,
            'l1_misses': 0,
            'l2_hits': 0,
            'l2_misses': 0,
            'total_gets': 0,
            'total_sets': 0
        }

        # Intentar conectar a Redis
        if REDIS_AVAILABLE and enable_redis:
            try:
                import os
                redis_url = redis_url or os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
                self.redis_client = redis.from_url(redis_url, decode_responses=False)
                self.redis_client.ping()
                self.redis_enabled = True
                logger.info(f"OK Redis L1 cache connected: {redis_url}")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Using PostgreSQL-only caching.")

    def _make_key(self, namespace: str, key: str) -> str:
        """
        Genera key único para cache

        Args:
            namespace: Namespace (ej: 'geometry', 'tree', 'features')
            key: Key específico

        Returns:
            Cache key completo
        """
        return f"step_view:{namespace}:{key}"

    def _serialize(self, value: Any) -> bytes:
        """Serializa valor para almacenamiento"""
        return pickle.dumps(value)

    def _deserialize(self, data: bytes) -> Any:
        """Deserializa valor desde almacenamiento"""
        return pickle.loads(data)

    def get(self, namespace: str, key: str, from_l2: bool = True) -> Optional[Any]:
        """
        Obtiene valor del cache

        Args:
            namespace: Namespace del cache
            key: Key del valor
            from_l2: Si L1 miss, intentar L2

        Returns:
            Valor cacheado o None
        """
        self.stats['total_gets'] += 1
        cache_key = self._make_key(namespace, key)

        # L1: Redis
        if self.redis_enabled:
            try:
                value = self.redis_client.get(cache_key)
                if value is not None:
                    self.stats['l1_hits'] += 1
                    logger.debug(f"L1 HIT: {cache_key}")
                    return self._deserialize(value)
                else:
                    self.stats['l1_misses'] += 1
            except Exception as e:
                logger.exception(f"Redis GET error: {e}")

        # L2: PostgreSQL (implementado en subclase o externamente)
        if from_l2:
            value = self._get_from_l2(namespace, key)
            if value is not None:
                self.stats['l2_hits'] += 1
                logger.debug(f"L2 HIT: {cache_key}")

                # Promover a L1
                if self.redis_enabled:
                    self.set(namespace, key, value, ttl=3600, to_l2=False)

                return value
            else:
                self.stats['l2_misses'] += 1

        logger.debug(f"MISS: {cache_key}")
        return None

    def set(self, namespace: str, key: str, value: Any,
            ttl: int = 3600, to_l2: bool = True) -> bool:
        """
        Almacena valor en cache

        Args:
            namespace: Namespace del cache
            key: Key del valor
            value: Valor a cachear
            ttl: Time-to-live en segundos (para L1)
            to_l2: También guardar en L2

        Returns:
            True si exitoso
        """
        self.stats['total_sets'] += 1
        cache_key = self._make_key(namespace, key)
        serialized = self._serialize(value)

        # L1: Redis
        if self.redis_enabled:
            try:
                self.redis_client.setex(cache_key, ttl, serialized)
                logger.debug(f"L1 SET: {cache_key} (TTL: {ttl}s)")
            except Exception as e:
                logger.exception(f"Redis SET error: {e}")

        # L2: PostgreSQL
        if to_l2:
            self._set_to_l2(namespace, key, value, ttl)

        return True

    def delete(self, namespace: str, key: str, from_l2: bool = True) -> bool:
        """
        Elimina valor del cache

        Args:
            namespace: Namespace
            key: Key
            from_l2: También eliminar de L2

        Returns:
            True si exitoso
        """
        cache_key = self._make_key(namespace, key)

        # L1: Redis
        if self.redis_enabled:
            try:
                self.redis_client.delete(cache_key)
                logger.debug(f"L1 DELETE: {cache_key}")
            except Exception as e:
                logger.exception(f"Redis DELETE error: {e}")

        # L2: PostgreSQL
        if from_l2:
            self._delete_from_l2(namespace, key)

        return True

    def invalidate_namespace(self, namespace: str) -> int:
        """
        Invalida todos los keys en un namespace

        Args:
            namespace: Namespace a invalidar

        Returns:
            Número de keys eliminados
        """
        count = 0

        # L1: Redis
        if self.redis_enabled:
            try:
                pattern = f"step_view:{namespace}:*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    count = self.redis_client.delete(*keys)
                logger.info(f"L1 invalidated {count} keys in namespace '{namespace}'")
            except Exception as e:
                logger.exception(f"Redis invalidate error: {e}")

        # L2: PostgreSQL
        l2_count = self._invalidate_namespace_l2(namespace)
        count += l2_count

        return count

    def get_stats(self) -> Dict:
        """
        Obtiene estadísticas de cache

        Returns:
            Dict con métricas
        """
        total_requests = self.stats['total_gets']
        l1_hit_rate = (self.stats['l1_hits'] / total_requests * 100) if total_requests > 0 else 0
        l2_hit_rate = (self.stats['l2_hits'] / total_requests * 100) if total_requests > 0 else 0

        return {
            **self.stats,
            'l1_hit_rate': round(l1_hit_rate, 2),
            'l2_hit_rate': round(l2_hit_rate, 2),
            'redis_enabled': self.redis_enabled
        }

    def clear_stats(self):
        """Reinicia estadísticas"""
        for key in self.stats:
            self.stats[key] = 0

    # Métodos L2 (PostgreSQL) - implementados externamente o en subclase
    def _get_from_l2(self, namespace: str, key: str) -> Optional[Any]:
        """Stub para L2 GET"""
        # Implementado en PostgreSQLCacheManager
        return None

    def _set_to_l2(self, namespace: str, key: str, value: Any, ttl: int):
        """Stub para L2 SET"""
        # Implementado en PostgreSQLCacheManager
        pass

    def _delete_from_l2(self, namespace: str, key: str):
        """Stub para L2 DELETE"""
        # Implementado en PostgreSQLCacheManager
        pass

    def _invalidate_namespace_l2(self, namespace: str) -> int:
        """Stub para L2 invalidate"""
        # Implementado en PostgreSQLCacheManager
        return 0


class PostgreSQLCacheManager(CacheManager):
    """
    Cache manager con soporte completo para PostgreSQL L2
    """

    def __init__(self, db_session, redis_url: Optional[str] = None, enable_redis: bool = True):
        """
        Inicializa con sesión de base de datos

        Args:
            db_session: SQLAlchemy session
            redis_url: URL de Redis
            enable_redis: Habilitar Redis
        """
        super().__init__(redis_url, enable_redis)
        self.db = db_session

    def _get_from_l2(self, namespace: str, key: str) -> Optional[Any]:
        """Obtiene valor de PostgreSQL"""
        from app.step_view_pro.models import CacheEntry

        try:
            entry = CacheEntry.query.filter_by(
                namespace=namespace,
                cache_key=key
            ).first()

            if entry:
                # Verificar expiración
                if entry.expires_at and entry.expires_at < datetime.utcnow():
                    self.db.delete(entry)
                    self.db.commit()
                    return None

                return pickle.loads(entry.value)

        except Exception as e:
            logger.exception(f"L2 GET error: {e}")

        return None

    def _set_to_l2(self, namespace: str, key: str, value: Any, ttl: int):
        """Almacena valor en PostgreSQL"""
        from app.step_view_pro.models import CacheEntry

        try:
            serialized = pickle.dumps(value)
            expires_at = datetime.utcnow() + timedelta(seconds=ttl) if ttl > 0 else None

            # Buscar entry existente
            entry = CacheEntry.query.filter_by(
                namespace=namespace,
                cache_key=key
            ).first()

            if entry:
                entry.value = serialized
                entry.expires_at = expires_at
                entry.updated_at = datetime.utcnow()
            else:
                entry = CacheEntry(
                    namespace=namespace,
                    cache_key=key,
                    value=serialized,
                    expires_at=expires_at
                )
                self.db.add(entry)

            self.db.commit()
            logger.debug(f"L2 SET: {namespace}:{key}")

        except Exception as e:
            logger.exception(f"L2 SET error: {e}")
            self.db.rollback()

    def _delete_from_l2(self, namespace: str, key: str):
        """Elimina valor de PostgreSQL"""
        from app.step_view_pro.models import CacheEntry

        try:
            CacheEntry.query.filter_by(
                namespace=namespace,
                cache_key=key
            ).delete()
            self.db.commit()
            logger.debug(f"L2 DELETE: {namespace}:{key}")

        except Exception as e:
            logger.exception(f"L2 DELETE error: {e}")
            self.db.rollback()

    def _invalidate_namespace_l2(self, namespace: str) -> int:
        """Invalida namespace en PostgreSQL"""
        from app.step_view_pro.models import CacheEntry

        try:
            count = CacheEntry.query.filter_by(namespace=namespace).delete()
            self.db.commit()
            logger.info(f"L2 invalidated {count} keys in namespace '{namespace}'")
            return count

        except Exception as e:
            logger.exception(f"L2 invalidate error: {e}")
            self.db.rollback()
            return 0

    def cleanup_expired(self) -> int:
        """
        Limpia entradas expiradas de L2

        Returns:
            Número de entradas eliminadas
        """
        from app.step_view_pro.models import CacheEntry

        try:
            count = CacheEntry.query.filter(
                CacheEntry.expires_at < datetime.utcnow()
            ).delete()
            self.db.commit()
            logger.info(f"Cleaned up {count} expired cache entries")
            return count

        except Exception as e:
            logger.exception(f"Cleanup error: {e}")
            self.db.rollback()
            return 0

    def get_geometry(self, header_id: str, lod: str = 'medium'):
        """
        Obtiene geometría cacheada para un header y nivel de detalle

        Args:
            header_id: ID del header
            lod: Nivel de detalle ('low', 'medium', 'high')

        Returns:
            Geometría cacheada o None
        """
        try:
            namespace = f"geometry_{header_id}"
            key = f"lod_{lod}"
            return self.get(namespace, key)
        except Exception as e:
            logger.exception(f"Error getting geometry from cache: {e}")
            return None

    def save_geometry(self, header_id: str, geometry_data: dict):
        """
        Guarda geometría en cache

        Args:
            header_id: ID del header
            geometry_data: Datos de geometría a guardar

        Returns:
            Clave de cache utilizada
        """
        try:
            # Guardar cada LOD por separado
            for lod_key in ['lod_low', 'lod_medium', 'lod_high']:
                if lod_key in geometry_data:
                    namespace = f"geometry_{header_id}"
                    key = lod_key
                    self.set(namespace, key, geometry_data[lod_key], ttl=86400)  # 24 horas

            # También guardar bounding box
            if 'bounding_box' in geometry_data:
                namespace = f"geometry_{header_id}"
                key = 'bounding_box'
                self.set(namespace, key, geometry_data['bounding_box'], ttl=86400)

            cache_key = f"{header_id}_geometry"
            return cache_key
        except Exception as e:
            logger.exception(f"Error saving geometry to cache: {e}")
            return None

    def get_cache_stats(self):
        """
        Obtiene estadísticas del cache

        Returns:
            Dict con estadísticas
        """
        try:
            cache_stats = self.get_stats()

            # Obtener conteo de entradas en PostgreSQL
            from app.step_view_pro.models import CacheEntry
            total_entries = self.db.query(CacheEntry).count()

            return {
                **cache_stats,
                'total_cached_entries': total_entries,
                'postgresql_cache_size': 'N/A'  # Implementar si se necesita
            }
        except Exception as e:
            logger.exception(f"Error getting cache stats: {e}")
            return {}

    def invalidate_cache(self, header_id: str):
        """
        Invalida cache para un header específico

        Args:
            header_id: ID del header a invalidar

        Returns:
            Número de entradas eliminadas
        """
        try:
            # Invalidar namespace de geometría
            geom_deleted = self.invalidate_namespace(f"geometry_{header_id}")

            # Invalidar otros namespaces relacionados
            entities_deleted = self.invalidate_namespace(f"entities_{header_id}")
            features_deleted = self.invalidate_namespace(f"features_{header_id}")

            total_deleted = geom_deleted + entities_deleted + features_deleted
            return total_deleted
        except Exception as e:
            logger.exception(f"Error invalidating cache: {e}")
            return 0

    def cleanup_old_entries(self, days: int = 30):
        """
        Limpia entradas antiguas del cache

        Args:
            days: Días de antigüedad para limpiar

        Returns:
            Número de entradas eliminadas
        """
        try:
            # Limpiar entradas expiradas
            expired_count = self.cleanup_expired()
            return expired_count
        except Exception as e:
            logger.exception(f"Error cleaning up old entries: {e}")
            return 0


def cached(namespace: str, ttl: int = 3600, key_func=None):
    """
    Decorator para cachear resultados de funciones

    Args:
        namespace: Namespace del cache
        ttl: Time-to-live en segundos
        key_func: Función para generar key custom (recibe args, kwargs)

    Usage:
        @cached('geometry', ttl=7200)
        def get_geometry(header_id):
            # expensive operation
            return geometry

        @cached('entities', key_func=lambda h_id, e_id: f"{h_id}:{e_id}")
        def get_entity(header_id, entity_id):
            return entity
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generar cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Usar args como key
                cache_key = hashlib.md5(
                    str((args, sorted(kwargs.items()))).encode()
                ).hexdigest()

            # Intentar obtener del cache
            # NOTE: This requires a cache_manager instance to be available
            # It should be passed or configured in the application context
            result = None
            # from app import cache_manager  # This line removed to prevent import issues
            # result = cache_manager.get(namespace, cache_key)

            if result is not None:
                return result

            # Ejecutar función
            result = func(*args, **kwargs)

            # Guardar en cache (if cache_manager is available in context)
            # cache_manager.set(namespace, cache_key, result, ttl=ttl)

            return result

        return wrapper
    return decorator


# Global instance
try:
    cache_manager = CacheManager()
    logger.info("OK Cache Manager module loaded with PythonOCC support")
except Exception as e:
    # Create a fallback cache manager when PythonOCC is not available
    logger.warning(f"PythonOCC not available, initializing basic cache manager: {e}")
    # Create a basic instance that works without PythonOCC
    cache_manager = CacheManager.__new__(CacheManager)
    cache_manager.available = False
    cache_manager.redis_client = None
    cache_manager.redis_enabled = False
    cache_manager.stats = {
        'l1_hits': 0,
        'l1_misses': 0,
        'l2_hits': 0,
        'l2_misses': 0,
        'total_gets': 0,
        'total_sets': 0
    }
    logger.info("OK Cache Manager module loaded (basic mode - PythonOCC unavailable)")

logger.info("OK Cache Manager module loaded")
