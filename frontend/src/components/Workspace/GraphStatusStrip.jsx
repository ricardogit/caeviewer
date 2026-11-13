/**
 * GraphStatusStrip — FASE 9 §9.4: non-intrusive status of the study in the graph editor.
 *   ⚠ completeness issues (first ones)   ✓ valid for physics   ✓/⚠ estimated tier vs declared
 *   ℹ confidence factor from validated similar cases   · latest run
 * Refreshed (debounced) whenever the graph's nodes/edges change.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Box, Typography, IconButton, Tooltip } from '@mui/material';
import { ExpandLess, ExpandMore } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';
import useWorkspaceStore from '../../stores/workspaceStore';

const fmtInt = (n) => (n == null ? '—' : Number(n).toLocaleString('es-MX'));

export function statusLines(p) {
  if (!p) return [];
  if (p.error) return [{ kind: 'warn', text: p.error }];
  const out = [];
  const errs = (p.issues || []).filter((i) => i.severity === 'error');
  const warns = (p.issues || []).filter((i) => i.severity !== 'error');
  errs.slice(0, 3).forEach((i) => out.push({ kind: 'error', text: i.message }));
  if (errs.length > 3) out.push({ kind: 'error', text: `… y ${errs.length - 3} problema(s) más` });
  warns.slice(0, 2).forEach((i) => out.push({ kind: 'warn', text: i.message }));
  if (p.ready) out.push({ kind: 'ok', text: `Grafo válido para física: ${p.physics_label}` });
  if (p.size) {
    const est = p.size.estimated ? '≈ ' : '';
    if (p.tier_needed == null) {
      out.push({ kind: 'error', text: `${est}${fmtInt(p.size.n_dof)} DOF: excede el Tier 3` });
    } else if (p.tier_ok) {
      out.push({ kind: 'ok', text: `Tier estimado: ${p.tier_needed} (${est}${fmtInt(p.size.n_dof)} DOF) · declarado ${p.tier_declared}` });
    } else {
      out.push({ kind: 'warn', text: `Necesita Tier ${p.tier_needed} (${est}${fmtInt(p.size.n_dof)} DOF) y el estudio declara Tier ${p.tier_declared}` });
    }
  }
  if (p.confidence) {
    out.push({
      kind: 'info',
      text: p.confidence.n_similar
        ? `Factor de confianza: ${p.confidence.factor.toFixed(2)} (${p.confidence.n_similar} simulación(es) similar(es) validada(s))`
        : 'Factor de confianza: sin casos similares validados con ensayos',
    });
  }
  if (p.latest_run) {
    const r = p.latest_run;
    out.push({ kind: r.status === 'failed' ? 'warn' : 'info',
      text: `Última simulación: ${r.status}${r.max_displacement_mm != null ? ` · u máx ${Number(r.max_displacement_mm).toPrecision(3)} mm` : ''}${r.max_von_mises_mpa != null ? ` · σvM máx ${Number(r.max_von_mises_mpa).toPrecision(3)} MPa` : ''}` });
  }
  return out;
}

const ICON = { error: ['⚠', '#ef9a9a'], warn: ['⚠', '#ffe082'], ok: ['✓', '#a5d6a7'], info: ['ℹ', '#90caf9'] };

export default function GraphStatusStrip() {
  const { activeGraphId, graphData } = useDesignStore();
  const { preflight, loadPreflight } = useWorkspaceStore();
  const [open, setOpen] = useState(true);

  // structural fingerprint of the graph: refresh when content changes, not on drags
  const key = useMemo(() => JSON.stringify([
    (graphData?.nodes || []).map((n) => [n.id, n.data?.node_type, n.data?.properties]),
    (graphData?.edges || []).map((e) => [e.source, e.target, e.data?.edge_type || e.label]),
  ]), [graphData]);

  useEffect(() => {
    if (!activeGraphId) return undefined;
    const t = setTimeout(() => loadPreflight(activeGraphId), 500);
    return () => clearTimeout(t);
  }, [activeGraphId, key, loadPreflight]);

  if (!activeGraphId || !preflight || (preflight.graph_id && preflight.graph_id !== activeGraphId)) return null;
  const lines = statusLines(preflight);
  const nErr = lines.filter((l) => l.kind === 'error').length;
  return (
    <Box data-testid="graph-status" sx={{
      position: 'absolute', left: 64, bottom: 16, zIndex: 20, maxWidth: 520, bgcolor: '#161616ee',
      border: `1px solid ${nErr ? '#b71c1c' : '#2e7d32'}`, borderRadius: 1.5, px: 1.25, py: 0.5,
      boxShadow: '0 4px 16px rgba(0,0,0,0.5)', pointerEvents: 'auto',
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center' }}>
        <Typography sx={{ color: '#bbb', fontSize: 11, flex: 1, fontWeight: 600 }}>
          Estado del estudio {nErr ? `· ${nErr} problema(s)` : ''}
        </Typography>
        <Tooltip title={open ? 'Contraer' : 'Expandir'}>
          <IconButton size="small" onClick={() => setOpen((o) => !o)} sx={{ color: '#888', p: 0.25 }}>
            {open ? <ExpandMore fontSize="small" /> : <ExpandLess fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>
      {open && lines.map((l, i) => (
        <Typography key={i} sx={{ color: ICON[l.kind][1], fontSize: 11, lineHeight: 1.6 }}>
          {ICON[l.kind][0]} {l.text}
        </Typography>
      ))}
    </Box>
  );
}
