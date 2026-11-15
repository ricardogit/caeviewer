/**
 * ResultsViewer — FASE 9 "Results" mode: the 3D field of a finished run of the active study.
 * Surface of the run (GET /api/design/solver/<run>/surface), coloured by von Mises, |u| or a
 * component, drawn on the deformed shape (scale slider, true scale 1×), with colour bar and the
 * run summary. Opened from the run list, the solver panel ("Ver resultados 3D") or the TopBar.
 */
import React, { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, GizmoHelper, GizmoViewport } from '@react-three/drei';
import {
  Box, Typography, ToggleButtonGroup, ToggleButton, Slider, CircularProgress, Alert, Button, Tooltip,
} from '@mui/material';
import { AccountTree } from '@mui/icons-material';
import useResultsStore from '../../stores/resultsStore';
import { colormap, COLORBAR_CSS } from '../../utils/colormap';
import { autoScale, fieldMeta, availableFields, fieldValues, fmt, normalizer, range } from './resultsField';
import useDesignStore from '../../stores/designStore';

function FitOnce({ box, keyId }) {
  const { camera, controls } = useThree();
  const done = useRef(null);
  useEffect(() => {
    if (!box || done.current === keyId) return;
    done.current = keyId;
    const c = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    const dist = (size / (2 * Math.tan((camera.fov * Math.PI) / 360))) * 1.1;
    camera.position.copy(c).add(new THREE.Vector3(0.6, 0.45, 1).normalize().multiplyScalar(dist));
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) { controls.target.copy(c); controls.update(); }
  }, [box, keyId, camera, controls]);
  return null;
}

export function SummaryRows({ header }) {
  const s = header?.summary || {};
  const hasU = (header?.fields || ['u']).includes('u');
  const rows = [
    ...(hasU ? [
      ['Despl. máx.', header?.max_u_mm != null ? `${fmt(header.max_u_mm)} mm` : '—'],
      ['σvM máx. (nodal)', header?.max_vm_mpa != null ? `${fmt(header.max_vm_mpa)} MPa` : '—'],
    ] : []),
    ...(s.plasticity ? [
      ['εp máx.', fmt(s.plasticity.max_equivalent_plastic_strain)],
      ['Zona plástica', `${fmt(100 * s.plasticity.plastic_volume_fraction)} % vol.`],
      ['Carga alcanzada', s.plasticity.limit_load_reached
        ? `${fmt(100 * s.plasticity.load_factor)} % (carga límite)` : 'completa'],
    ] : []),
    ...(s.hyperelastic ? [
      ['Modelo', 'Neo-Hookean (grandes def.)'],
      ['ε Green máx.', fmt(s.hyperelastic.max_green_strain)],
      ['J mín.', fmt(s.hyperelastic.min_J)],
      ['Carga alcanzada', s.hyperelastic.stopped_early
        ? `${fmt(100 * s.hyperelastic.load_factor)} % (sin convergencia)` : 'completa'],
    ] : []),
    ...(s.viscoelastic ? [
      ['Modelo', `Maxwell (${s.viscoelastic.prony?.length || 0} términos)`],
      ['Tiempo final', `${fmt(s.viscoelastic.t_end_s)} s`],
      ['E₀ / E∞', `${fmt(s.viscoelastic.E0 / 1e9)} / ${fmt(s.viscoelastic.E_inf / 1e9)} GPa`],
      ['Despl. final / inicial', s.viscoelastic.creep_ratio != null ? `×${fmt(s.viscoelastic.creep_ratio)}` : '—'],
    ] : []),
    ...(s.piezo ? [
      ['Modelo', 'Piezoeléctrico (u + φ)'],
      ['Potencial', `${fmt(s.piezo.min_potential_V)} … ${fmt(s.piezo.max_potential_V)} V`],
      ['|E| máx.', `${fmt(s.piezo.max_field_V_m / 1e6)} kV/mm`],
      ...(s.piezo.d_pC_N ? [['d31 / d33 / d15', `${fmt(s.piezo.d_pC_N.d31)} / ${fmt(s.piezo.d_pC_N.d33)} / `
        + `${fmt(s.piezo.d_pC_N.d15)} pC/N`]] : []),
      ...(s.piezo.electrodes || []).map((el, i) => [`Electrodo ${el.label || i + 1}`,
        `${fmt(el.voltage_V)} V · Q = ${fmt(el.charge_C * 1e9)} nC`]),
    ] : []),
    ...(s.fluid ? [
      ['Modelo', `${s.fluid.model === 'navier_stokes' ? 'Navier-Stokes laminar' : 'Stokes'} · μ = ${fmt(s.fluid.mu)} Pa·s`],
      ...(s.fluid.navier_stokes ? [
        ['Iteraciones', `${s.fluid.navier_stokes.picard_iterations} Picard + ${s.fluid.navier_stokes.newton_iterations} Newton`
          + (s.fluid.navier_stokes.continuation_steps > 1 ? ` · ${s.fluid.navier_stokes.continuation_steps} pasos de Re` : '')],
        ['Re de elemento máx.', `${fmt(s.fluid.navier_stokes.element_reynolds_max)}${s.fluid.navier_stokes.stabilization
          ? ' · SUPG' : (s.fluid.navier_stokes.element_reynolds_max > 100 ? ' ⚠ > 100' : '')}`],
      ] : []),
      ['|v| máx.', `${fmt(s.fluid.max_velocity_m_s * 1e3)} mm/s`],
      ['Presión', `${fmt(s.fluid.min_pressure_pa)} … ${fmt(s.fluid.max_pressure_pa)} Pa`],
      ...(s.fluid.flow_rates || []).filter(f => Math.abs(f.flow_m3_s) > 1e-6 * Math.max(
        ...(s.fluid.flow_rates || []).map(g => Math.abs(g.flow_m3_s)))).map(f => [
        `Caudal ${f.label || f.face_set}`, `${fmt(f.flow_m3_s * 6e7)} mL/min (${f.flow_m3_s > 0 ? 'sale' : 'entra'})`]),
      ['Balance de masa', `${fmt(100 * s.fluid.mass_balance_error)} %`],
      ['Reynolds', `${fmt(s.fluid.reynolds)}${s.fluid.model === 'navier_stokes'
        ? (s.fluid.reynolds > 2000 ? ' ⚠ > 2000' : '') : (s.fluid.reynolds > 1 ? ' ⚠ > 1' : '')}`],
    ] : []),
    ...(s.magnetic ? [
      ['Modelo', `Magnético · μr${s.magnetic.saturation ? ' inicial' : ''} = ${fmt(s.magnetic.mu_r)}${(s.magnetic.Br_T || []).some(b => b)
        ? ` · Br = [${s.magnetic.Br_T.map(fmt).join(', ')}] T` : ''}`],
      ...(s.magnetic.saturation ? [['Saturación', `${s.magnetic.saturation.model === 'tanh'
        ? `Js = ${fmt(s.magnetic.saturation.Js)} T` : `tabla B-H (${(s.magnetic.saturation.points || []).length} puntos)`}`
        + ` · μr mín. ${fmt(s.magnetic.saturation.min_mu_r)} · Newton ${s.magnetic.saturation.newton_iterations} it`]] : []),
      ['|B| máx.', `${fmt(s.magnetic.max_B_T)} T`],
      ['|H| máx.', `${fmt(s.magnetic.max_H_A_m / 1e3)} kA/m`],
      ['Potencial ψ', `${fmt(s.magnetic.min_potential_A)} … ${fmt(s.magnetic.max_potential_A)} A`],
      ...(s.magnetic.poles || []).map((p, i) => [`Polo ${p.label || i + 1}`,
        `ψ = ${fmt(p.potential_A)} A · Φ = ${fmt(p.flux_in_Wb * 1e6)} µWb (${p.flux_in_Wb >= 0 ? 'entra' : 'sale'})`]),
      ...(s.magnetic.permeance_H != null ? [['Permeancia (L para 1 vuelta)', `${fmt(s.magnetic.permeance_H * 1e6)} µH`]] : []),
      ['Energía del campo', `${fmt(s.magnetic.field_energy_J * 1e3)} mJ`
        + (s.magnetic.coenergy_J != null ? ` · coenergía ${fmt(s.magnetic.coenergy_J * 1e3)} mJ` : '')],
      ...(s.magnetic.coils || []).flatMap((c, i) => [
        [`Bobina ${c.label || i + 1}`, `${fmt(c.turns)} vueltas × ${fmt(c.current_A)} A · λ = ${fmt(c.flux_linkage_Wb * 1e3)} mWb`],
        ['Inductancia', `secante ${fmt(c.L_secant_H * 1e3)} mH · incremental ${fmt(c.L_incremental_H * 1e3)} mH`],
      ]),
    ] : []),
    ...(header?.max_T != null ? [
      ['Temperatura', `${fmt(header.min_T)} … ${fmt(header.max_T)} °C`],
      ['Flujo de calor máx.', `${fmt(header.max_q)} W/m²`],
      ['Balance de calor', s.thermal?.heat_balance_error != null ? `${fmt(100 * s.thermal.heat_balance_error)} %` : '—'],
    ] : []),
    ['Elemento', s.element_type || '—'],
    ['Nodos / elementos', s.n_nodes ? `${s.n_nodes.toLocaleString()} / ${(s.n_elements || 0).toLocaleString()}` : '—'],
    ...(hasU ? [
      header?.material?.E1
        ? ['E1 / E2 / E3', [header.material.E1, header.material.E2, header.material.E3].map(v => fmt(v / 1e9)).join(' / ') + ' GPa']
        : header?.material?.c33
          ? ['c11ᴱ / c33ᴱ', `${fmt(header.material.c11 / 1e9)} / ${fmt(header.material.c33 / 1e9)} GPa`]
          : ['E', header?.material?.E ? `${fmt(header.material.E / 1e9)} GPa` : '—'],
      ['Equilibrio', s.equilibrium_error != null ? `${fmt(100 * s.equilibrium_error)} %` : '—'],
    ] : (s.fluid || s.magnetic) ? [] : [['k', header?.material?.k
      ? `${Array.isArray(header.material.k) ? header.material.k.map(fmt).join(' / ') : fmt(header.material.k)} W/m·K`
      : '—']]),
  ];
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'auto auto', columnGap: 1.5, rowGap: 0.25 }}>
      {rows.map(([k, v]) => (
        <React.Fragment key={k}>
          <Typography sx={{ color: '#888', fontSize: 11 }}>{k}</Typography>
          <Typography sx={{ color: '#ddd', fontSize: 11, fontFamily: 'monospace', textAlign: 'right' }}>{v}</Typography>
        </React.Fragment>
      ))}
    </Box>
  );
}

export default function ResultsViewer() {
  const { pack, runId, loading, error, field: chosen, setField, scale, setScale } = useResultsStore();
  const fields = useMemo(() => availableFields(pack), [pack]);
  const field = fields.includes(chosen) ? chosen : (fields[0] || 'vm');
  const hasU = fields.includes('umag');
  const setAppMode = useDesignStore((s) => s.setAppMode);

  const geometry = useMemo(() => {
    if (!pack) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pack.xyz.data), 3));
    g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(pack.nNodes * 3), 3));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(pack.tris.data), 1));
    g.computeBoundingBox();
    return g;
  }, [pack]);
  const box = geometry?.boundingBox || null;
  const auto = useMemo(() => (pack ? autoScale(pack) : 1), [pack]);
  const k = scale ?? auto;
  const values = useMemo(() => (pack ? fieldValues(pack, field) : null), [pack, field]);
  const norm = useMemo(() => (values ? normalizer(field, range(values)) : null), [values, field]);

  useEffect(() => {
    if (!geometry || !values) return;
    const pos = geometry.attributes.position.array;
    const col = geometry.attributes.color.array;
    const xyz = pack.xyz.data;
    const u = pack.u.data;
    for (let i = 0; i < pack.nNodes; i += 1) {
      for (let c = 0; c < 3; c += 1) pos[3 * i + c] = xyz[3 * i + c] + k * u[3 * i + c];
      col.set(colormap(norm.t(values[i])), 3 * i);
    }
    geometry.attributes.position.needsUpdate = true;
    geometry.attributes.color.needsUpdate = true;
    geometry.computeVertexNormals();
  }, [geometry, values, norm, k, pack]);

  if (!runId) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#888',
        flexDirection: 'column', gap: 1 }}>
        <Typography>Selecciona una simulación terminada en el panel izquierdo.</Typography>
        <Button size="small" startIcon={<AccountTree />} onClick={() => setAppMode('design')}>Ir al grafo del estudio</Button>
      </Box>
    );
  }
  const f = fieldMeta(pack, field);
  return (
    <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
      <Canvas camera={{ fov: 40, position: [300, 200, 400] }} onCreated={({ gl }) => gl.setClearColor('#20242a')}>
        <ambientLight intensity={0.5} />
        <hemisphereLight args={['#e8eef7', '#30343a', 0.6]} />
        <directionalLight position={[1, 2, 1.5]} intensity={0.9} />
        <directionalLight position={[-1.5, -1, -1]} intensity={0.35} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
        {geometry && (
          <mesh geometry={geometry}>
            <meshStandardMaterial vertexColors side={THREE.DoubleSide} roughness={0.6} metalness={0.05} />
          </mesh>
        )}
        <FitOnce box={box} keyId={runId} />
        <GizmoHelper alignment="bottom-left" margin={[56, 56]}>
          <GizmoViewport axisColors={['#ff4060', '#80ff40', '#4080ff']} labelColor="white" />
        </GizmoHelper>
      </Canvas>

      {loading && (
        <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <CircularProgress />
        </Box>
      )}
      {error && (
        <Alert severity="error" sx={{ position: 'absolute', top: 60, left: 16, right: 16, fontSize: 12 }}>{error}</Alert>
      )}

      {pack && (
        <>
          <Box sx={{ position: 'absolute', top: 12, left: 12, right: 12, display: 'flex', alignItems: 'center',
            gap: 2, flexWrap: 'wrap' }}>
            <ToggleButtonGroup size="small" exclusive value={field} onChange={(_, v) => v && setField(v)}
              sx={{ bgcolor: '#1a1a1a' }}>
              {fields.map((key) => (
                <ToggleButton key={key} value={key} sx={{ fontSize: 11, py: 0.25, textTransform: 'none' }}>{fieldMeta(pack, key).label}</ToggleButton>
              ))}
            </ToggleButtonGroup>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, bgcolor: '#1a1a1acc', px: 1, borderRadius: 1 }}
              data-testid="colorbar">
              <Typography variant="caption" sx={{ color: '#ccc' }}>{fmt(norm.min)}</Typography>
              <Box sx={{ width: 160, height: 10, borderRadius: 1, background: COLORBAR_CSS }} />
              <Typography variant="caption" sx={{ color: '#ccc' }}>{fmt(norm.max)} {f.unit}</Typography>
            </Box>
            {hasU && <Tooltip title="Factor de deformación (auto = desplazamiento máximo dibujado como 8 % del modelo)">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: 260, bgcolor: '#1a1a1acc', px: 1,
                borderRadius: 1 }}>
                <Typography variant="caption" sx={{ color: '#ccc', whiteSpace: 'nowrap' }} data-testid="scale">
                  Deformada ×{fmt(k)}
                </Typography>
                <Slider size="small" min={0} max={2} step={0.05} value={auto > 0 ? k / auto : 0}
                  onChange={(_, v) => setScale(v * auto)} />
                <Button size="small" sx={{ fontSize: 10, minWidth: 0 }} onClick={() => setScale(1)}>1:1</Button>
              </Box>
            </Tooltip>}
          </Box>
          <Box sx={{ position: 'absolute', bottom: 12, right: 12, bgcolor: '#1a1a1add', p: 1, borderRadius: 1,
            border: '1px solid #333', minWidth: 220 }}>
            <Typography sx={{ color: '#90caf9', fontSize: 11, mb: 0.5 }}>
              Run {runId.slice(0, 8)} · {pack.header?.purpose} · {pack.header?.created_at?.slice(0, 16).replace('T', ' ')}
            </Typography>
            <SummaryRows header={pack.header} />
          </Box>
        </>
      )}
    </Box>
  );
}
