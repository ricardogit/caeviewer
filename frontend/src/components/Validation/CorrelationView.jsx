/**
 * CorrelationView — FASE 8: measured vs simulated.
 *   structural        sensors: scatter measured vs simulated (identity line), per-sensor table
 *   material          tensile test vs the material's current model (curve overlay)
 *   recal_tensile     before/after curves + parameter δ (old → new)
 *   recal_structural  effective E + scatter before/after the stiffness correction
 * R² and the maximum relative error are shown prominently, with the confidence factor.
 */
import React from 'react';
import { Box, Typography, Chip, Table, TableBody, TableRow, TableCell, TableHead, Alert } from '@mui/material';
import {
  ScatterChart, Scatter, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';

const cell = { '& td, & th': { color: '#ccc', borderColor: '#333', fontSize: 11, py: 0.3, px: 0.5 } };
const pct = (v, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${(100 * v).toFixed(d)} %`);
const num = (v, d = 4) => (v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toPrecision(d));
const QTY_UNIT = { ux: 'mm', uy: 'mm', uz: 'mm', umag: 'mm', strain: 'µε' };

export function r2Color(r2) {
  if (r2 == null || !Number.isFinite(r2)) return '#888';
  if (r2 >= 0.95) return '#66bb6a';
  if (r2 >= 0.8) return '#ffb74d';
  return '#ef5350';
}

function Headline({ metrics, title }) {
  if (!metrics) return null;
  return (
    <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5, flexWrap: 'wrap' }}>
      <Typography sx={{ color: '#aaa', fontSize: 11 }}>{title}</Typography>
      <Typography data-testid="r2" sx={{ color: r2Color(metrics.r2), fontSize: 26, fontWeight: 700, lineHeight: 1 }}>
        R² {num(metrics.r2, 4)}
      </Typography>
      <Typography sx={{ color: '#ccc', fontSize: 12 }}>error máx. {pct(metrics.max_rel_error)}</Typography>
      {metrics.confidence_factor != null && (
        <Chip size="small" label={`confianza ${num(metrics.confidence_factor, 2)}`}
          sx={{ height: 18, fontSize: 10, bgcolor: '#263238', color: '#80cbc4' }} />
      )}
    </Box>
  );
}

/** Scatter of normalized measured vs simulated (each quantity divided by its max |measured|). */
function SensorScatter({ sensors, afterKey }) {
  if (!sensors?.length) return null;
  const scale = {};
  sensors.forEach((s) => { scale[s.quantity] = Math.max(scale[s.quantity] || 0, Math.abs(s.value)); });
  const pts = (key) => sensors.map((s) => ({
    m: s.value / (scale[s.quantity] || 1), s: s[key] / (scale[s.quantity] || 1), label: s.label,
  }));
  const all = sensors.flatMap((s) => [s.value, s.simulated, afterKey ? s[afterKey] : s.value]
    .map((v) => v / (scale[s.quantity] || 1)));
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const pad = 0.05 * (hi - lo || 1);
  const dom = [lo - pad, hi + pad];
  return (
    <ResponsiveContainer width="100%" height={200}>
      <ScatterChart margin={{ top: 6, right: 10, bottom: 18, left: 0 }}>
        <CartesianGrid stroke="#333" />
        <XAxis type="number" dataKey="m" domain={dom} tick={{ fill: '#999', fontSize: 10 }}
          tickFormatter={(v) => v.toFixed(1)}
          label={{ value: 'medido (normalizado)', position: 'insideBottom', offset: -8, fill: '#999', fontSize: 10 }} />
        <YAxis type="number" dataKey="s" domain={dom} tick={{ fill: '#999', fontSize: 10 }} width={34}
          tickFormatter={(v) => v.toFixed(1)} />
        <Tooltip contentStyle={{ background: '#222', border: '1px solid #444', fontSize: 11 }}
          formatter={(v) => Number(v).toFixed(3)} labelFormatter={() => ''} />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Scatter name="identidad" data={[{ m: dom[0], s: dom[0] }, { m: dom[1], s: dom[1] }]} line={{ stroke: '#777' }}
          shape={() => null} legendType="none" isAnimationActive={false} />
        <Scatter name="simulado" data={pts('simulated')} fill="#4fc3f7" isAnimationActive={false} />
        {afterKey && <Scatter name="tras recalibrar" data={pts(afterKey)} fill="#66bb6a" isAnimationActive={false} />}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function SensorTable({ sensors, afterKey }) {
  if (!sensors?.length) return null;
  return (
    <Table size="small" sx={cell}>
      <TableHead>
        <TableRow>
          <TableCell>Sensor</TableCell><TableCell>Magnitud</TableCell><TableCell align="right">Medido</TableCell>
          <TableCell align="right">Simulado</TableCell>{afterKey && <TableCell align="right">Recalibr.</TableCell>}
          <TableCell align="right">Error</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {sensors.map((s, i) => (
          <TableRow key={`${s.label}-${i}`}>
            <TableCell>{s.label}{s.outside ? ' ⚠' : ''}</TableCell>
            <TableCell>{s.quantity} [{QTY_UNIT[s.quantity]}]</TableCell>
            <TableCell align="right">{num(s.value)}</TableCell>
            <TableCell align="right">{num(s.simulated)}</TableCell>
            {afterKey && <TableCell align="right">{num(s[afterKey])}</TableCell>}
            <TableCell align="right" sx={{ color: s.rel_error > 0.15 ? '#ef5350 !important' : undefined }}>
              {pct(s.rel_error)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function CurveOverlay({ curve }) {
  if (!curve?.strain?.length) return null;
  const n = curve.strain.length;
  const step = Math.max(1, Math.floor(n / 400));
  const data = [];
  for (let i = 0; i < n; i += step) {
    data.push({
      e: 100 * curve.strain[i], m: curve.measured[i],
      b: curve.before?.[i] ?? curve.predicted?.[i], a: curve.after?.[i],
    });
  }
  return (
    <ResponsiveContainer width="100%" height={190}>
      <LineChart data={data} margin={{ top: 6, right: 10, bottom: 18, left: 0 }}>
        <CartesianGrid stroke="#333" />
        <XAxis dataKey="e" type="number" domain={[0, 'dataMax']} tick={{ fill: '#999', fontSize: 10 }}
          tickFormatter={(v) => v.toFixed(1)}
          label={{ value: 'ε [%]', position: 'insideBottom', offset: -8, fill: '#999', fontSize: 10 }} />
        <YAxis tick={{ fill: '#999', fontSize: 10 }} width={38} />
        <Tooltip contentStyle={{ background: '#222', border: '1px solid #444', fontSize: 11 }}
          formatter={(v) => `${Number(v).toFixed(1)} MPa`} labelFormatter={(v) => `ε ${Number(v).toFixed(3)} %`} />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Line dataKey="m" name="ensayo" stroke="#bbb" dot={false} strokeWidth={1} isAnimationActive={false} />
        <Line dataKey="b" name="modelo actual" stroke="#ef5350" dot={false} strokeDasharray="5 3"
          isAnimationActive={false} />
        {curve.after && (
          <Line dataKey="a" name="recalibrado" stroke="#66bb6a" dot={false} isAnimationActive={false} />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

const PARAM_LABEL = { E: ['E', 1e-9, 'GPa'], sigma_y: ['σy (σ0.2)', 1e-6, 'MPa'], uts: ['UTS', 1e-6, 'MPa'] };

export function DeltaTable({ delta }) {
  const rows = Object.entries(delta || {});
  if (!rows.length) return null;
  return (
    <Table size="small" sx={cell}>
      <TableHead>
        <TableRow>
          <TableCell>Parámetro</TableCell><TableCell align="right">Antes</TableCell>
          <TableCell align="right">Después</TableCell><TableCell align="right">δ</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map(([k, d]) => {
          const [lab, sc, unit] = PARAM_LABEL[k] || [k, 1, ''];
          const f = (v) => (v == null ? '—' : `${num(v * sc, 4)}${unit ? ` ${unit}` : ''}`);
          return (
            <TableRow key={k}>
              <TableCell>{lab}</TableCell>
              <TableCell align="right">{f(d.old)}</TableCell>
              <TableCell align="right">{f(d.new)}{d.new_std ? ` ± ${num(d.new_std * sc, 2)}` : ''}</TableCell>
              <TableCell align="right">{d.rel_change == null ? 'nuevo' : `${d.rel_change >= 0 ? '+' : ''}${pct(d.rel_change)}`}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export default function CorrelationView({ view }) {
  if (!view?.data) return null;
  const { type, data } = view;
  const det = data.details || {};

  if (type === 'structural') {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Headline metrics={det.overall || { r2: data.r2, max_rel_error: data.max_relative_error,
          confidence_factor: data.confidence_factor }} title="Sensores vs simulación" />
        {det.n_outside > 0 && (
          <Alert severity="warning" sx={{ fontSize: 11, py: 0 }}>
            {det.n_outside} sensor(es) fuera de la pieza (más de media arista de malla): revisa sus coordenadas
            (mm, sistema del CAD).
          </Alert>
        )}
        <SensorScatter sensors={det.sensors} />
        <SensorTable sensors={det.sensors} />
        {det.load_factor != null && det.load_factor !== 1 && (
          <Typography sx={{ color: '#888', fontSize: 10 }}>Simulación escalada por el factor de carga {det.load_factor}.</Typography>
        )}
      </Box>
    );
  }
  if (type === 'material') {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Headline metrics={det.overall} title="Ensayo vs modelo del material" />
        <Typography sx={{ color: '#888', fontSize: 10 }}>{det.curve?.model}</Typography>
        <CurveOverlay curve={{ ...det.curve, after: det.after ? det.curve?.after : undefined }} />
        {data.recalibration_delta && <DeltaTable delta={data.recalibration_delta} />}
      </Box>
    );
  }
  if (type === 'recal_tensile') {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {!data.applied && <Chip size="small" label="Vista previa (no aplicado)" sx={{ alignSelf: 'flex-start', height: 18, fontSize: 10 }} />}
        <Headline metrics={data.before} title="Antes (modelo actual)" />
        <Headline metrics={data.after} title="Después (recalibrado)" />
        <Typography sx={{ color: '#888', fontSize: 10 }}>
          {data.model_before} → {data.model_after} · modo {data.mode === 'bayes' ? 'bayesiano (combina con el anterior)' : 'reemplazo'}
          {data.synced_nodes?.length ? ` · ${data.synced_nodes.length} nodo(s) MATERIAL actualizados` : ''}
        </Typography>
        <CurveOverlay curve={data.curve} />
        <DeltaTable delta={data.delta} />
      </Box>
    );
  }
  if (type === 'recal_structural') {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {!data.applied && <Chip size="small" label="Vista previa (no aplicado)" sx={{ alignSelf: 'flex-start', height: 18, fontSize: 10 }} />}
        <Headline metrics={data.before} title="Antes" />
        <Headline metrics={data.after} title="Con E efectivo" />
        {data.warning && <Alert severity="warning" sx={{ fontSize: 11, py: 0 }}>{data.warning}</Alert>}
        <Typography sx={{ color: '#ccc', fontSize: 12 }}>
          E efectivo {num(data.E_new / 1e9, 4)}{data.E_std ? ` ± ${num(data.E_std / 1e9, 2)}` : ''} GPa
          (simulado con {num(data.E_run / 1e9, 4)} GPa, {data.delta?.E?.rel_change >= 0 ? '+' : ''}{pct(data.delta?.E?.rel_change)})
        </Typography>
        <Typography sx={{ color: '#888', fontSize: 10 }}>
          Un solo caso de carga solo identifica la escala de rigidez: el E efectivo absorbe también la flexibilidad del
          utillaje o errores de carga. Vuelve a simular para ver los resultados con el nuevo E.
        </Typography>
        <SensorScatter sensors={data.sensors} afterKey="simulated_after" />
        <SensorTable sensors={data.sensors} afterKey="simulated_after" />
      </Box>
    );
  }
  return null;
}
