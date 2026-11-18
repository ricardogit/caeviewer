/**
 * PiezoFields — piezoelectric MATERIAL node (model_type = piezoelectric), hexagonal 6mm class with the
 * poling direction = material axis 3. Stress-charge form: σ = cᴱε − eᵀE, D = eε + εˢE.
 * c [Pa] (constant field), e [C/m²], relative permittivities at constant strain. "PZT-5H" fills a datasheet set.
 * thermal (model_type = thermopiezoelectric): + pyroelectric p3 [C/(m²·K)] along the poling axis; α, k and T_ref
 * come from the node's "Propiedades térmicas" (α may also be α1..α3 along the material axes).
 */
import React from 'react';
import { Box, Button, TextField, Typography } from '@mui/material';

export const PIEZO_KEYS = ['c11', 'c12', 'c13', 'c33', 'c44', 'c66', 'e31', 'e33', 'e15', 'eps11', 'eps33'];
export const PZT5H = {
  c11: 127.205e9, c12: 80.212e9, c13: 84.670e9, c33: 117.436e9, c44: 22.988e9, c66: 23.474e9,
  e31: -6.623, e33: 23.240, e15: 17.034, eps11: 1704.4, eps33: 1433.6, rho: 7500,
};
const ROWS = [
  [['c11', 'c11ᴱ [Pa]'], ['c12', 'c12ᴱ [Pa]'], ['c13', 'c13ᴱ [Pa]']],
  [['c33', 'c33ᴱ [Pa]'], ['c44', 'c44ᴱ [Pa]'], ['c66', 'c66ᴱ [Pa]']],
  [['e31', 'e31 [C/m²]'], ['e33', 'e33 [C/m²]'], ['e15', 'e15 [C/m²]']],
  [['eps11', 'ε11ˢ/ε0'], ['eps33', 'ε33ˢ/ε0']],
];
const DEFAULT_AXES = { axis_1: [1, 0, 0], axis_2: [0, 1, 0] };

export default function PiezoFields({ props, setProp, thermal = false }) {
  const num = (k, lbl) => (
    <TextField key={k} label={lbl} size="small" type="number" sx={{ flex: 1 }}
      value={props[k] ?? ''}
      onChange={(e) => setProp(k, e.target.value === '' ? null : parseFloat(e.target.value))}
      inputProps={{ style: { color: '#fff' }, 'aria-label': lbl }}
      InputLabelProps={{ style: { color: '#888' } }} />
  );
  const axis = (key, title) => {
    const v = props[key] || DEFAULT_AXES[key];
    return (
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        <Typography variant="caption" sx={{ color: '#bbb', width: 44, flexShrink: 0 }}>{title}</Typography>
        {['x', 'y', 'z'].map((c, i) => (
          <TextField key={c} label={c} size="small" type="number" sx={{ flex: 1 }} value={v[i]}
            onChange={(e) => {
              const next = [...v];
              next[i] = e.target.value === '' ? 0 : parseFloat(e.target.value);
              setProp(key, next);
            }}
            inputProps={{ style: { color: '#fff' }, 'aria-label': `${title} ${c}` }}
            InputLabelProps={{ style: { color: '#888' } }} />
        ))}
      </Box>
    );
  };
  const missing = [...PIEZO_KEYS, ...(thermal ? ['p3', 'alpha', 'k'] : [])]
    .filter(k => props[k] == null || props[k] === '');
  return (
    <Box data-testid="piezo-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #4a3b1a', borderRadius: 1, p: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="caption" sx={{ color: '#ffe082', flex: 1 }}>
          Piezoeléctrico 6mm · polarización = eje 3 del material
        </Typography>
        <Button size="small" variant="outlined"
          onClick={() => Object.entries(PZT5H).forEach(([k, v]) => setProp(k, v))}>PZT-5H</Button>
      </Box>
      {missing.length > 0 && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>Faltan: {missing.join(', ')}</Typography>
      )}
      {ROWS.map((row, i) => (
        <Box key={i} sx={{ display: 'flex', gap: 0.5 }}>{row.map(([k, lbl]) => num(k, lbl))}</Box>
      ))}
      {thermal && (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {num('p3', 'p3 piroeléctrico [C/m²·K]')}
        </Box>
      )}
      <Typography variant="caption" sx={{ color: '#888' }}>
        Ejes del material en el sistema global/CAD (eje 3 = 1 × 2 = dirección de polarización)
      </Typography>
      {axis('axis_1', 'Eje 1')}
      {axis('axis_2', 'Eje 2')}
      <Typography variant="caption" sx={{ color: '#888' }}>
        Electrodos: CC «Potencial eléctrico» en caras (V). Carga libre: CARGA «Carga eléctrica superficial».
        {thermal
          ? ' Temperatura: CC «Temperatura impuesta» y cargas térmicas; α, k y T ref en «Propiedades térmicas» '
            + '(acoplamiento en un sentido: térmico → dilatación α ΔT + carga piroeléctrica p3 ΔT).'
          : ' Sin acoplamiento térmico (use «Termo-piezoeléctrico»).'}
      </Typography>
    </Box>
  );
}
