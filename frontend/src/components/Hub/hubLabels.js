import {
  Functions, GridOn, Calculate, Architecture, Hub, Psychology, PrecisionManufacturing, BubbleChart,
  Layers, Air, Flight, Bolt, Cloud, Web, DesignServices, CloudQueue, Extension,
} from '@mui/icons-material';

/** Own icons per catalog `icon` key — never vendor logos (trademarks). */
export const ICONS = {
  functions: Functions, grid: GridOn, calculate: Calculate, architecture: Architecture, hub: Hub,
  psychology: Psychology, precision: PrecisionManufacturing, bubble: BubbleChart, layers: Layers,
  air: Air, flight: Flight, bolt: Bolt, cloud: Cloud, web: Web, design: DesignServices,
  cloud_queue: CloudQueue,
};
export const FallbackIcon = Extension;

export const LEVELS = {
  integrated:  { label: 'Integrado',  dot: '#4caf50', help: 'Se ejecuta dentro del Hub' },
  connectable: { label: 'Conectable', dot: '#ffc107', help: 'Requiere tu licencia mediante un adaptador' },
  reference:   { label: 'Referencia', dot: '#9e9e9e', help: 'Ficha informativa con enlace externo' },
};

export const AVAILABILITY = {
  available: { label: 'Disponible', color: 'success' },
  partial:   { label: 'Parcial',    color: 'info' },
  planned:   { label: 'Próximamente', color: 'default' },
};

export const CATEGORY = {
  open_source: 'Open source', commercial: 'Comercial', cloud: 'Nube', specialized: 'Especializado',
};

export const ANALYSIS = {
  static: 'Estático', modal: 'Modal', buckling: 'Pandeo', thermal: 'Térmico', transient: 'Transitorio',
  nonlinear: 'No lineal', contact: 'Contacto', cfd: 'CFD', electromagnetics: 'Electromagnetismo',
  multiphysics: 'Multifísica', optimization: 'Optimización', meshing: 'Mallado', postprocessing: 'Post-proceso',
};

export const METHOD = { fem: 'FEM', fvm: 'Volúmenes finitos', meshing: 'Mallado', statistics: 'Estadístico' };

export const DEPLOYMENT = [
  { key: 'desktop', label: 'Desktop' },
  { key: 'hpc', label: 'HPC' },
  { key: 'cloud', label: 'Cloud' },
  { key: 'ai', label: 'AI' },
];
