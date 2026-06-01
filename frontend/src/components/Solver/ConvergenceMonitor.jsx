/**
 * ConvergenceMonitor — real-time residual vs iteration chart.
 * FASE 2: uses Recharts (already installed).
 */
import React from 'react';
import { Box, Typography } from '@mui/material';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';

export default function ConvergenceMonitor({ log = [], tolerance = 1e-8 }) {
  if (log.length === 0) return null;

  // Convert residuals to log10 for better readability
  const data = log.map(p => ({
    iter: p.iter,
    log_res: p.residual > 0 ? Math.log10(p.residual) : -16,
    residual: p.residual,
    wall_time: p.wall_time?.toFixed(2),
  }));

  const logTol = Math.log10(tolerance);

  return (
    <Box sx={{ bgcolor: '#0a0a0a', border: '1px solid #222', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#888', fontSize: 10, display: 'block', mb: 0.5 }}>
        Convergencia — Residuo relativo (log₁₀)
      </Typography>
      <ResponsiveContainer width="100%" height={80}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <XAxis
            dataKey="iter" tick={{ fontSize: 9, fill: '#666' }}
            label={{ value: 'iter', position: 'insideBottomRight', fill: '#555', fontSize: 9 }}
          />
          <YAxis
            tick={{ fontSize: 9, fill: '#666' }}
            domain={[Math.min(logTol - 2, data.at(-1)?.log_res - 1 ?? -12), 1]}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#1e1e1e', border: '1px solid #333', fontSize: 10 }}
            formatter={(v, name) => [name === 'log_res' ? `10^${v.toFixed(1)}` : v, 'Residuo']}
            labelFormatter={l => `Iter ${l}`}
          />
          <ReferenceLine y={logTol} stroke="#f44336" strokeDasharray="4 2"
                         label={{ value: 'tol', fill: '#f44336', fontSize: 8 }} />
          <Line type="monotone" dataKey="log_res" stroke="#2196f3"
                dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <Typography variant="caption" sx={{ color: '#555', fontSize: 9 }}>
        Último residuo: {log.at(-1)?.residual?.toExponential(2) ?? '—'}
        {' · '}
        {log.at(-1)?.wall_time?.toFixed(2) ?? '—'} s
      </Typography>
    </Box>
  );
}
