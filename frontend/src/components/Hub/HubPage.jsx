/**
 * HubPage — Engineering Hub catalog (H1d). Cards come from GET /api/catalog;
 * adding a tool is a DB row (app/catalog/seed_data.py), not UI code.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Box, Typography, Chip, Card, CardContent, CardActions, Button, Stack, Tooltip, Alert, CircularProgress,
  Dialog, DialogTitle, DialogContent, DialogActions, List, ListItem, ListItemText, Link,
} from '@mui/material';
import { ArrowForward, OpenInNew, Cable, PlayArrow, Schedule } from '@mui/icons-material';
import useHubStore, { matches, activeFilterCount } from '../../stores/hubStore';
import { ICONS, FallbackIcon, LEVELS, AVAILABILITY, CATEGORY, ANALYSIS, METHOD, DEPLOYMENT } from './hubLabels';

const SECTIONS = [
  { level: 'integrated', title: 'Integradas en el Hub', subtitle: 'Se ejecutan aquí: abre el espacio de trabajo.' },
  { level: 'connectable', title: 'Conectables', subtitle: 'Con tu propia licencia, mediante un adaptador.' },
  { level: 'reference', title: 'Referencia', subtitle: 'Fichas informativas con enlace externo.' },
];

function ConnectDialog({ tool, onClose }) {
  const c = tool?.connection || {};
  return (
    <Dialog open={Boolean(tool)} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Conectar {tool?.name}</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>
          El adaptador para {tool?.name} todavía no está implementado ({tool?.availability_note || 'fase futura'}).
          Estos son los requisitos previstos.
        </Alert>
        {c.adapter && <Typography variant="body2"><b>Adaptador:</b> {c.adapter}</Typography>}
        {c.python_package && <Typography variant="body2"><b>Paquete Python:</b> <code>{c.python_package}</code></Typography>}
        {c.requires?.length > 0 && (
          <List dense>
            {c.requires.map((r) => <ListItem key={r} disableGutters><ListItemText primary={`• ${r}`} /></ListItem>)}
          </List>
        )}
        {c.docs && <Link href={c.docs} target="_blank" rel="noopener noreferrer">Documentación del adaptador</Link>}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cerrar</Button></DialogActions>
    </Dialog>
  );
}

function ToolCard({ tool, match, highlight, onLaunch, onConnect }) {
  const Icon = ICONS[tool.icon] || FallbackIcon;
  const lvl = LEVELS[tool.integration_level];
  const av = AVAILABILITY[tool.availability];
  const caps = tool.capabilities || {};
  const filters = useHubStore((s) => s.filters);
  const runnable = tool.integration_level === 'integrated' && tool.availability !== 'planned' && tool.launch?.mode;

  let action;
  if (tool.integration_level === 'integrated') {
    action = runnable
      ? <Button size="small" variant="contained" startIcon={<PlayArrow />} onClick={() => onLaunch(tool)}>Abrir</Button>
      : <Button size="small" disabled startIcon={<Schedule />}>Próximamente</Button>;
  } else if (tool.integration_level === 'connectable') {
    action = <Button size="small" variant="outlined" startIcon={<Cable />} onClick={() => onConnect(tool)}>Configurar conexión</Button>;
  } else {
    action = tool.url
      ? <Button size="small" endIcon={<OpenInNew />} href={tool.url} target="_blank" rel="noopener noreferrer">Sitio web</Button>
      : null;
  }

  return (
    <Card
      variant="outlined"
      sx={{
        display: 'flex', flexDirection: 'column', height: '100%', transition: 'opacity .2s, border-color .2s',
        opacity: match ? 1 : 0.3,
        borderColor: highlight && match ? 'primary.main' : 'divider',
        boxShadow: highlight && match ? (t) => `0 0 0 1px ${t.palette.primary.main}` : 'none',
      }}
    >
      <CardContent sx={{ flex: 1, pb: 1 }}>
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          <Box sx={{ p: 1, borderRadius: 1, bgcolor: 'action.hover', display: 'grid', placeItems: 'center' }}>
            <Icon />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ lineHeight: 1.2 }}>{tool.name}</Typography>
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.5, flexWrap: 'wrap', rowGap: 0.5 }}>
              <Tooltip title={lvl.help}>
                <Chip size="small" variant="outlined" label={lvl.label}
                  icon={<Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: lvl.dot, ml: '8px !important' }} />} />
              </Tooltip>
              <Chip size="small" color={av.color} variant={tool.availability === 'available' ? 'filled' : 'outlined'}
                label={tool.availability_note && tool.availability !== 'available' ? `${av.label} · ${tool.availability_note}` : av.label} />
            </Stack>
          </Box>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>{tool.description}</Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 1.5 }}>
          {(caps.analysis || []).map((a) => (
            <Chip key={a} size="small" label={ANALYSIS[a] || a}
              color={filters.analysis.includes(a) ? 'primary' : 'default'}
              variant={filters.analysis.includes(a) ? 'filled' : 'outlined'} sx={{ height: 20, fontSize: 11 }} />
          ))}
          {(caps.method || []).filter((m) => m !== 'meshing').map((m) => (
            <Chip key={m} size="small" label={METHOD[m] || m} sx={{ height: 20, fontSize: 11 }} />
          ))}
        </Box>
      </CardContent>
      <CardActions sx={{ px: 2, pb: 1.5, pt: 0, '& .MuiButton-root': { whiteSpace: 'nowrap', flexShrink: 0 } }}>
        {action}
        <Box sx={{ flex: 1 }} />
        <Typography variant="caption" color="text.secondary" noWrap sx={{ minWidth: 0 }}>{CATEGORY[tool.category]} · {tool.license}</Typography>
        {tool.url && tool.integration_level !== 'reference' && (
          <Tooltip title="Sitio web">
            <Button size="small" sx={{ minWidth: 0 }} href={tool.url} target="_blank" rel="noopener noreferrer"><OpenInNew fontSize="small" /></Button>
          </Tooltip>
        )}
      </CardActions>
    </Card>
  );
}

export default function HubPage({ onLaunch }) {
  const { tools, facets, loading, error, filters, toggle, hideNonMatching, load } = useHubStore();
  const [connectTool, setConnectTool] = useState(null);
  useEffect(() => { load(); }, [load]);

  const anyFilter = activeFilterCount(filters) > 0;
  const enriched = useMemo(() => tools.map((t) => ({ tool: t, match: matches(t, filters) })), [tools, filters]);
  const nMatch = enriched.filter((e) => e.match).length;
  const analysisKeys = Object.keys(ANALYSIS).filter((k) => (facets?.analysis?.[k] ?? 0) > 0);

  return (
    <Box sx={{ height: '100%', overflow: 'auto', p: 3 }}>
      <Typography variant="h5">Engineering Hub</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Herramientas de simulación: las integradas corren aquí; las demás se conectan con tu licencia o son referencia.
      </Typography>

      {/* Desktop → HPC → Cloud → AI (deployment filter) */}
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
        {DEPLOYMENT.map((d, i) => (
          <React.Fragment key={d.key}>
            <Chip
              label={`${d.label}${facets ? ` (${facets.deployment?.[d.key] ?? 0})` : ''}`}
              color={filters.deployment.includes(d.key) ? 'primary' : 'default'}
              variant={filters.deployment.includes(d.key) ? 'filled' : 'outlined'}
              onClick={() => toggle('deployment', d.key)}
            />
            {i < DEPLOYMENT.length - 1 && <ArrowForward fontSize="small" sx={{ color: 'text.disabled' }} />}
          </React.Fragment>
        ))}
      </Stack>

      {/* Key features (analysis capabilities) */}
      <Typography variant="overline" color="text.secondary">Capacidades clave</Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mb: 2 }}>
        {analysisKeys.map((k) => (
          <Chip key={k} size="small" label={`${ANALYSIS[k]} (${facets.analysis[k]})`}
            color={filters.analysis.includes(k) ? 'primary' : 'default'}
            variant={filters.analysis.includes(k) ? 'filled' : 'outlined'}
            onClick={() => toggle('analysis', k)} />
        ))}
      </Box>

      {anyFilter && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {nMatch} de {tools.length} herramientas coinciden con los filtros.
        </Typography>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading && <CircularProgress size={24} />}
      {!loading && !error && tools.length === 0 && (
        <Alert severity="warning">El catálogo está vacío. Ejecuta <code>flask catalog seed</code> en el servidor.</Alert>
      )}

      {SECTIONS.map((sec) => {
        const items = enriched.filter((e) => e.tool.integration_level === sec.level && (!hideNonMatching || e.match));
        if (!items.length) return null;
        return (
          <Box key={sec.level} sx={{ mb: 3 }}>
            <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 1 }}>
              <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: LEVELS[sec.level].dot, alignSelf: 'center' }} />
              <Typography variant="h6">{sec.title}</Typography>
              <Typography variant="body2" color="text.secondary">{sec.subtitle}</Typography>
            </Stack>
            <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
              {items.map(({ tool, match }) => (
                <ToolCard key={tool.slug} tool={tool} match={match} highlight={anyFilter}
                  onLaunch={(t) => onLaunch?.(t.launch)} onConnect={setConnectTool} />
              ))}
            </Box>
          </Box>
        );
      })}
      <ConnectDialog tool={connectTool} onClose={() => setConnectTool(null)} />
    </Box>
  );
}
