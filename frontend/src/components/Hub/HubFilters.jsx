import React, { useEffect } from 'react';
import {
  Box, Typography, FormGroup, FormControlLabel, Checkbox, Divider, Button, Stack, Switch, Tooltip,
} from '@mui/material';
import useHubStore, { activeFilterCount } from '../../stores/hubStore';
import { LEVELS, AVAILABILITY, CATEGORY, METHOD } from './hubLabels';

function Group({ title, group, labels, counts }) {
  const selected = useHubStore((s) => s.filters[group]);
  const toggle = useHubStore((s) => s.toggle);
  const entries = Object.entries(labels).filter(([k]) => (counts?.[k] ?? 0) > 0);
  if (!entries.length) return null;
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="overline" color="text.secondary">{title}</Typography>
      <FormGroup>
        {entries.map(([key, label]) => (
          <FormControlLabel
            key={key}
            sx={{ my: -0.5 }}
            control={<Checkbox size="small" checked={selected.includes(key)} onChange={() => toggle(group, key)} />}
            label={<Typography variant="body2">{typeof label === 'string' ? label : label.label}
              <Typography component="span" variant="caption" color="text.secondary"> ({counts[key]})</Typography></Typography>}
          />
        ))}
      </FormGroup>
    </Box>
  );
}

export default function HubFilters() {
  const { facets, filters, load, clearFilters, hideNonMatching, setHideNonMatching } = useHubStore();
  useEffect(() => { load(); }, [load]);
  const n = activeFilterCount(filters);

  return (
    <Box sx={{ p: 2 }}>
      <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>Filtros</Typography>
        <Button size="small" disabled={!n} onClick={clearFilters}>Limpiar{n ? ` (${n})` : ''}</Button>
      </Stack>
      <FormControlLabel
        control={<Switch size="small" checked={hideNonMatching} onChange={(e) => setHideNonMatching(e.target.checked)} />}
        label={<Typography variant="body2">Ocultar las que no coinciden</Typography>}
        sx={{ mb: 1 }}
      />
      <Divider sx={{ mb: 1 }} />
      {facets && (
        <>
          <Group title="Integración" group="level" labels={LEVELS} counts={facets.level} />
          <Group title="Categoría" group="category" labels={CATEGORY} counts={facets.category} />
          <Group title="Disponibilidad" group="availability" labels={AVAILABILITY} counts={facets.availability} />
          <Group title="Método" group="method" labels={METHOD} counts={facets.method} />
        </>
      )}
      <Divider sx={{ my: 1 }} />
      <Typography variant="overline" color="text.secondary">Niveles de integración</Typography>
      {Object.entries(LEVELS).map(([k, l]) => (
        <Tooltip key={k} title={l.help} placement="right">
          <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 0.25 }}>
            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: l.dot }} />
            <Typography variant="body2">{l.label}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap>· {l.help}</Typography>
          </Stack>
        </Tooltip>
      ))}
    </Box>
  );
}
