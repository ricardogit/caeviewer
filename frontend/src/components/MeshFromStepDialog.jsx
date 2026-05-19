import React, { useState, useCallback } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Slider, Select, MenuItem, FormControl, InputLabel,
  Typography, Box, CircularProgress, Alert, Chip, Divider,
  ToggleButton, ToggleButtonGroup, Tooltip, Stack,
} from '@mui/material';
import {
  CheckCircle, Hub, InfoOutlined,
  ViewInAr, Grain, BlurOn, GridOn,
} from '@mui/icons-material';
import axios from 'axios';

// ─── Datos de configuración ───────────────────────────────────────────────────

/**
 * Tipos de malla soportados por Gmsh con sus propiedades reales.
 * Fuente: compatibilidad real Gmsh (ver tabla de referencia).
 *
 * strategy  → qué se envía al backend como mesh_type
 * algorithm → algoritmo 3D por defecto para ese tipo (se puede sobreescribir)
 */
const MESH_FAMILIES = [
  {
    id: 'tetra',
    label: 'TET4',
    sublabel: 'Tetraédrico',
    icon: <ViewInAr sx={{ fontSize: 18 }} />,
    strategy: 'tetra',
    defaultAlgo: 'hxt',
    quality: 2,        // 1–5
    autoGen: 5,
    description:
      'Malla no estructurada de tetraedros. Muy robusta para cualquier geometría STEP. ' +
      'Recomendada para análisis estructural FEA general, biomédica y geomecánica.',
    solvers: ['CalculiX', 'Code_Aster', 'OpenFOAM', 'Elmer', 'Abaqus', 'ANSYS'],
    warning: null,
  },
  {
    id: 'tetra10',
    label: 'TET10',
    sublabel: 'Cuadrático',
    icon: <ViewInAr sx={{ fontSize: 18 }} />,
    strategy: 'tetra',
    defaultAlgo: 'frontal',
    quality: 4,
    autoGen: 4,
    description:
      'Tetraedros de segundo orden (10 nodos). Mejor precisión en esfuerzos y ' +
      'desplazamientos curvos. Requiere más memoria. Ideal para FEA estructural de alta calidad.',
    solvers: ['CalculiX', 'Code_Aster', 'Abaqus', 'ANSYS Mechanical'],
    warning: 'Genera ~4× más nodos que TET4 con la misma fineza.',
    extraGmsh: { 'Mesh.ElementOrder': 2 },
  },
  {
    id: 'hybrid',
    label: 'HEX+TET',
    sublabel: 'Híbrido',
    icon: <BlurOn sx={{ fontSize: 18 }} />,
    strategy: 'hybrid',
    defaultAlgo: 'hxt',
    quality: 3,
    autoGen: 3,
    description:
      'Hexaedros donde la topología lo permite + tetraedros/cuñas en zonas complejas. ' +
      'Balance entre calidad numérica y generación automática. Útil para CFD e ingeniería industrial.',
    solvers: ['OpenFOAM', 'Fluent', 'CalculiX', 'STAR-CCM+', 'Code_Aster'],
    warning: null,
  },
  {
    id: 'hexa',
    label: 'HEX8',
    sublabel: 'Hexaédrico',
    icon: <GridOn sx={{ fontSize: 18 }} />,
    strategy: 'hexa',
    defaultAlgo: 'hxt',
    quality: 5,
    autoGen: 2,
    description:
      'Malla pura de hexaedros mediante recombinación Blossom + Frontal-Hex + subdivisión. ' +
      'Máxima calidad numérica. Recomendada para crash, turbomáquinas y problemas de contacto.',
    solvers: ['LS-DYNA', 'Abaqus', 'ANSYS Mechanical', 'CalculiX', 'Nastran'],
    warning:
      'Produce ~4× más elementos que TET con la misma fineza. Puede generar elementos ' +
      'distorsionados en geometrías muy complejas con curvaturas libres.',
  },
  {
    id: 'prism',
    label: 'PRISM',
    sublabel: 'Capas BL',
    icon: <Grain sx={{ fontSize: 18 }} />,
    strategy: 'hybrid',
    defaultAlgo: 'frontal',
    quality: 5,
    autoGen: 3,
    description:
      'Cuñas prismáticas (wedges) en la capa límite + TET en el núcleo. ' +
      'Estándar industrial para CFD con resolución de capa límite turbulenta.',
    solvers: ['OpenFOAM', 'Fluent', 'STAR-CCM+', 'SU2'],
    warning:
      'Gmsh genera prismas en extrusión normal a superficies. ' +
      'Para BL avanzada se recomienda postprocesar con cfMesh o snappyHexMesh.',
    extraGmsh: {
      'Mesh.BoundaryLayerFanPoints': 5,
    },
  },
];

const ALGORITHMS = [
  {
    value: 'hxt',
    label: 'HXT',
    desc: 'Paralelo Delaunay — el más rápido',
    compatWith: ['tetra', 'hybrid', 'hexa'],
  },
  {
    value: 'delaunay',
    label: 'Delaunay',
    desc: 'Robusto, buena calidad general',
    compatWith: ['tetra', 'hybrid', 'hexa'],
  },
  {
    value: 'frontal',
    label: 'Frontal',
    desc: 'Mayor calidad, más lento',
    compatWith: ['tetra', 'tetra10', 'hybrid', 'prism'],
  },
];

const REFINEMENT_LABELS = ['', 'Muy gruesa', 'Gruesa', 'Media', 'Fina', 'Muy fina'];
const REFINEMENT_HINT   = [
  '',
  '~1 k–5 k elem.',
  '~5 k–20 k elem.',
  '~20 k–100 k elem.',
  '~100 k–500 k elem.',
  '~500 k+ elem. (lento)',
];

// ─── Sub-componentes ──────────────────────────────────────────────────────────

function QualityBar({ value, color = 'primary' }) {
  return (
    <Box sx={{ display: 'flex', gap: 0.4, alignItems: 'center' }}>
      {[1, 2, 3, 4, 5].map(i => (
        <Box
          key={i}
          sx={{
            width: 10,
            height: 10,
            borderRadius: '2px',
            bgcolor: i <= value ? `${color}.main` : 'action.disabledBackground',
            transition: 'background-color 0.2s',
          }}
        />
      ))}
    </Box>
  );
}

function FamilyCard({ family, selected, onSelect }) {
  return (
    <Tooltip
      title={
        <Box sx={{ p: 0.5, maxWidth: 260 }}>
          <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>
            {family.description}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Solvers: {family.solvers.join(', ')}
          </Typography>
        </Box>
      }
      placement="right"
      arrow
    >
      <Box
        onClick={() => onSelect(family.id)}
        sx={{
          border: '1.5px solid',
          borderColor: selected ? 'primary.main' : 'divider',
          borderRadius: 1.5,
          px: 1.5,
          py: 1,
          cursor: 'pointer',
          bgcolor: selected ? 'primary.50' : 'background.paper',
          transition: 'all 0.15s',
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          '&:hover': {
            borderColor: 'primary.light',
            bgcolor: 'action.hover',
          },
        }}
      >
        {/* Icon + labels */}
        <Box sx={{ color: selected ? 'primary.main' : 'text.secondary' }}>
          {family.icon}
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" alignItems="baseline" spacing={0.75}>
            <Typography variant="body2" fontWeight={600} lineHeight={1.2}>
              {family.label}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {family.sublabel}
            </Typography>
          </Stack>
          <Stack direction="row" spacing={1.5} sx={{ mt: 0.5 }}>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: 10 }}>
                Calidad
              </Typography>
              <QualityBar value={family.quality} color="primary" />
            </Stack>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: 10 }}>
                Auto
              </Typography>
              <QualityBar value={family.autoGen} color="success" />
            </Stack>
          </Stack>
        </Box>
        {selected && (
          <CheckCircle sx={{ fontSize: 16, color: 'primary.main', flexShrink: 0 }} />
        )}
      </Box>
    </Tooltip>
  );
}

// ─── Diálogo principal ────────────────────────────────────────────────────────

export default function MeshFromStepDialog({ open, onClose, stepFile, onMeshCreated }) {
  const [familyId,   setFamilyId]   = useState('tetra');
  const [refinement, setRefinement] = useState(3);
  const [algorithm,  setAlgorithm]  = useState('hxt');
  const [optimize,   setOptimize]   = useState(true);
  const [loading,    setLoading]    = useState(false);
  const [result,     setResult]     = useState(null);
  const [error,      setError]      = useState(null);

  const family = MESH_FAMILIES.find(f => f.id === familyId) ?? MESH_FAMILIES[0];

  // Al cambiar familia, actualizar algoritmo por defecto si el actual no es compatible
  const handleFamilyChange = useCallback((id) => {
    const fam = MESH_FAMILIES.find(f => f.id === id);
    if (!fam) return;
    setFamilyId(id);
    const compat = ALGORITHMS.filter(a => a.compatWith.includes(id));
    if (!compat.find(a => a.value === algorithm)) {
      setAlgorithm(fam.defaultAlgo);
    }
    setResult(null);
    setError(null);
  }, [algorithm]);

  const compatAlgos = ALGORITHMS.filter(a => a.compatWith.includes(familyId));

  const reset = () => { setResult(null); setError(null); setLoading(false); };
  const handleClose = () => { reset(); onClose(); };

  const handleGenerate = async () => {
    if (!stepFile?.id) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = {
        part_id:    stepFile.id,
        refinement,
        algorithm,
        optimize,
        mesh_type:  family.strategy,
        // Pasar metadatos extra para que el backend pueda ajustar opciones Gmsh específicas
        mesh_family: familyId,
        ...(family.extraGmsh ? { gmsh_extra: family.extraGmsh } : {}),
      };
      const res = await axios.post('/api/cae/meshes/from-step', payload);
      setResult({ ...res.data, _familyId: familyId });
    } catch (e) {
      setError(e.response?.data?.error || 'Error al generar la malla');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenInCAE = () => {
    if (result) {
      onMeshCreated({
        id:                result.mesh_id,
        original_filename: result.original_filename,
        node_count:        result.node_count,
        element_count:     result.element_count,
      });
    }
    handleClose();
  };

  // Color del chip de tipo según familia
  const chipColor = {
    tetra:   'primary',
    tetra10: 'info',
    hybrid:  'secondary',
    hexa:    'warning',
    prism:   'success',
  }[result?._familyId] ?? 'default';

  return (
    <Dialog
      open={open}
      onClose={loading ? undefined : handleClose}
      maxWidth="sm"
      fullWidth
      PaperProps={{ sx: { borderRadius: 2 } }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
        <Hub fontSize="small" color="info" />
        Generar Malla FEA
      </DialogTitle>

      <DialogContent sx={{ pt: 0 }}>
        {stepFile && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
            Origen: <strong>{stepFile.original_filename || stepFile.name}</strong>
          </Typography>
        )}

        {/* ── 1. Tipo de elemento ── */}
        <Typography variant="body2" fontWeight={500} gutterBottom>
          Tipo de elemento
        </Typography>
        <Stack spacing={0.75} sx={{ mb: 2 }}>
          {MESH_FAMILIES.map(fam => (
            <FamilyCard
              key={fam.id}
              family={fam}
              selected={familyId === fam.id}
              onSelect={handleFamilyChange}
            />
          ))}
        </Stack>

        {/* Aviso específico del tipo seleccionado */}
        {family.warning && (
          <Alert
            severity="warning"
            icon={<InfoOutlined fontSize="small" />}
            sx={{ mb: 2, py: 0.5, fontSize: 12 }}
          >
            {family.warning}
          </Alert>
        )}

        <Divider sx={{ mb: 2 }} />

        {/* ── 2. Fineza ── */}
        <Typography variant="body2" fontWeight={500} gutterBottom>
          Fineza: <strong>{REFINEMENT_LABELS[refinement]}</strong>
        </Typography>
        <Slider
          value={refinement}
          onChange={(_, v) => setRefinement(v)}
          min={1} max={5} step={1}
          marks={[1, 2, 3, 4, 5].map(v => ({ value: v, label: String(v) }))}
          disabled={loading}
          sx={{ mb: 0.5 }}
        />
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
          {REFINEMENT_HINT[refinement]}
          {(familyId === 'hexa' || familyId === 'tetra10') &&
            ' · ×4 por subdivisión/orden'
          }
        </Typography>

        {/* ── 3. Algoritmo ── */}
        <FormControl fullWidth size="small" sx={{ mb: 2 }} disabled={loading}>
          <InputLabel>Algoritmo de generación</InputLabel>
          <Select
            value={algorithm}
            onChange={e => setAlgorithm(e.target.value)}
            label="Algoritmo de generación"
          >
            {compatAlgos.map(a => (
              <MenuItem key={a.value} value={a.value}>
                <Box>
                  <Typography variant="body2" lineHeight={1.3}>{a.label}</Typography>
                  <Typography variant="caption" color="text.secondary">{a.desc}</Typography>
                </Box>
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* ── 4. Optimización ── */}
        <Box sx={{ mb: 2 }}>
          <ToggleButtonGroup
            value={optimize ? 'on' : 'off'}
            exclusive
            onChange={(_, v) => { if (v) setOptimize(v === 'on'); }}
            size="small"
            disabled={loading}
          >
            <ToggleButton value="on" sx={{ px: 2, fontSize: 12 }}>
              Optimizar ✓
            </ToggleButton>
            <ToggleButton value="off" sx={{ px: 2, fontSize: 12 }}>
              Sin optimizar
            </ToggleButton>
          </ToggleButtonGroup>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {familyId === 'tetra' || familyId === 'tetra10'
              ? 'Netgen — mejora ángulos diedros en tetraedros'
              : 'Relocate3D + UntangleMeshGeometry — para hex/híbrido'}
          </Typography>
        </Box>

        <Divider sx={{ mb: 2 }} />

        {/* ── Estado ── */}
        {loading && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
            <CircularProgress size={20} />
            <Typography variant="body2" color="text.secondary">
              Generando malla {family.label}… puede tardar varios segundos.
            </Typography>
          </Box>
        )}

        {error && (
          <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 1 }}>
            {error}
          </Alert>
        )}

        {result && (
          <Alert severity="success" icon={<CheckCircle />} sx={{ mb: 1 }}>
            <Typography variant="body2" gutterBottom>
              <strong>Malla generada en {result.elapsed_s}s</strong>
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
              <Chip
                label={family.label}
                size="small"
                color={chipColor}
              />
              <Chip label={`${result.node_count.toLocaleString()} nodos`}   size="small" />
              <Chip label={`${result.element_count.toLocaleString()} elem.`} size="small" />
              {Object.entries(result.element_types ?? {}).map(([t, n]) => (
                <Chip key={t} label={`${t}: ${n}`} size="small" variant="outlined" />
              ))}
            </Box>
          </Alert>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 2, pb: 2, gap: 1 }}>
        <Button onClick={handleClose} disabled={loading}>
          {result ? 'Cerrar' : 'Cancelar'}
        </Button>

        {!result && (
          <Button
            onClick={handleGenerate}
            variant="contained"
            disabled={loading || !stepFile}
          >
            {loading ? 'Generando…' : 'Generar malla'}
          </Button>
        )}

        {result && (
          <Button onClick={handleOpenInCAE} variant="contained" color="success">
            Abrir en CAEViewer
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
