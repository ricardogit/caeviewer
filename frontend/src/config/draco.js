/**
 * Draco Decoder Configuration
 * ============================
 *
 * Configuración centralizada para el decoder de geometría Draco.
 * Draco es una librería de compresión que reduce significativamente
 * el tamaño de los modelos 3D.
 *
 * @module config/draco
 */

/**
 * Ruta al decoder Draco
 *
 * Por defecto: '/draco/' (se sirve desde public/draco/)
 *
 * Alternativas:
 * - CDN: 'https://www.gstatic.com/draco/v1/decoders/'
 * - NPM: '/node_modules/three/examples/jsm/libs/draco/'
 * - Custom: Cualquier ruta donde estén los archivos del decoder
 *
 * @type {string}
 */
export const DRACO_DECODER_PATH = import.meta.env.VITE_DRACO_DECODER_PATH || '/draco/';

/**
 * Habilitar/deshabilitar compresión Draco
 *
 * @type {boolean}
 */
export const ENABLE_DRACO = import.meta.env.VITE_ENABLE_DRACO !== 'false';

/**
 * Configuración del decoder Draco
 */
export const dracoConfig = {
  /**
   * Ruta al decoder
   */
  decoderPath: DRACO_DECODER_PATH,

  /**
   * Habilitar decoder
   */
  enabled: ENABLE_DRACO,

  /**
   * Tipo de decoder
   * - 'wasm': Web Assembly (más rápido, requiere draco_decoder.wasm)
   * - 'js': JavaScript puro (más lento, pero funciona en todos los navegadores)
   */
  decoderType: 'wasm',

  /**
   * URL de fallback si la ruta principal falla
   */
  fallbackUrl: 'https://www.gstatic.com/draco/versioned/decoders/1.5.6/',

  /**
   * Worker config
   */
  useWorker: true,
};

/**
 * Validar que los archivos del decoder existen
 *
 * @returns {Promise<boolean>} True si los archivos están disponibles
 */
export async function validateDracoDecoder() {
  try {
    const response = await fetch(`${DRACO_DECODER_PATH}draco_decoder.js`, {
      method: 'HEAD',
    });
    return response.ok;
  } catch (error) {
    console.warn('Draco decoder not found at:', DRACO_DECODER_PATH);
    console.warn('GLB models with Draco compression will fail to load.');
    console.warn('See: public/draco/README.md for setup instructions');
    return false;
  }
}

/**
 * Configurar decoder Draco en un loader
 *
 * @param {DRACOLoader} dracoLoader - Instancia de DRACOLoader
 */
export function configureDracoLoader(dracoLoader) {
  if (!ENABLE_DRACO) {
    return null;
  }

  dracoLoader.setDecoderPath(DRACO_DECODER_PATH);
  dracoLoader.setDecoderConfig({ type: dracoConfig.decoderType });

  if (dracoConfig.useWorker) {
    dracoLoader.preload();
  }

  return dracoLoader;
}

export default dracoConfig;
