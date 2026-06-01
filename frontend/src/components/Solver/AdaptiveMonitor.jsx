/**
 * AdaptiveMonitor — visualize adaptive mesh refinement cycles.
 * FASE 3: shows error reduction and mesh growth across iterations.
 */
import React from 'react';
import { Box, Typography, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts';

export default function AdaptiveMonitor({ adaptiveLog = [] }) {
  if (!adaptiveLog || adaptiveLog.length === 0) return null;

  const data = adaptiveLog.map(entry => ({
    cycle: entry.cycle,
    global_error: entry.global_error * 100,
    n_nodes: entry.n_nodes,
    n_elements: entry.n_elements,
    displacement_mm: entry.max_displacement_mm,
  }));

  return (
    <Box sx={{ bgcolor: '#0a0a0a', border: '1px solid #222', borderRadius: 1, p: 1.5 }}>
      {/* Header */}
      <Typography variant="subtitle2" sx={{ color: '#90caf9', fontWeight: 700, mb: 1 }}>
        Refinamiento Adaptativo — {adaptiveLog.length} ciclos
      </Typography>

      {/* Error reduction chart */}
      <ResponsiveContainer width="100%" height={120}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <XAxis dataKey="cycle" tick={{ fontSize: 9, fill: '#666' }} />
          <YAxis tick={{ fontSize: 9, fill: '#666' }} label={{ value: 'Error %', angle: -90, position: 'insideLeft' }} />
          <Tooltip contentStyle={{ backgroundColor: '#1e1e1e', border: '1px solid #333', fontSize: 10 }} />
          <ReferenceLine y={5} stroke="#f44336" strokeDasharray="4 2" label={{ value: '5%', fill: '#f44336', fontSize: 8 }} />
          <Line type="monotone" dataKey="global_error" stroke="#ff9800" dot={{ r: 3 }} strokeWidth={2} name="Global error %" />
        </LineChart>
      </ResponsiveContainer>

      {/* Mesh growth chart */}
      <ResponsiveContainer width="100%" height={100}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <XAxis dataKey="cycle" tick={{ fontSize: 9, fill: '#666' }} />
          <YAxis tick={{ fontSize: 9, fill: '#666' }} yAxisId="left" label={{ value: 'Nodos', angle: -90, position: 'insideLeft' }} />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 9, fill: '#666' }} label={{ value: 'Elementos', angle: 90, position: 'insideRight' }} />
          <Tooltip contentStyle={{ backgroundColor: '#1e1e1e', border: '1px solid #333', fontSize: 10 }} />
          <Line yAxisId="left" type="monotone" dataKey="n_nodes" stroke="#2196f3" dot={{ r: 3 }} strokeWidth={2} name="Nodos" />
          <Line yAxisId="right" type="monotone" dataKey="n_elements" stroke="#4caf50" dot={{ r: 3 }} strokeWidth={2} name="Elementos" />
          <Legend />
        </LineChart>
      </ResponsiveContainer>

      {/* Detailed table */}
      <Typography variant="caption" sx={{ color: '#888', fontSize: 10, display: 'block', mt: 1, mb: 0.5 }}>
        Historial de ciclos
      </Typography>
      <TableContainer sx={{ bgcolor: '#0d0d0d', border: '1px solid #333', borderRadius: 0.5, maxHeight: 200 }}>
        <Table size="small">
          <TableHead sx={{ bgcolor: '#1a1a1a' }}>
            <TableRow>
              <TableCell sx={{ color: '#888', fontSize: 10, p: 0.5, fontWeight: 700 }}>Ciclo</TableCell>
              <TableCell sx={{ color: '#888', fontSize: 10, p: 0.5, fontWeight: 700 }}>Nodos</TableCell>
              <TableCell sx={{ color: '#888', fontSize: 10, p: 0.5, fontWeight: 700 }}>Elementos</TableCell>
              <TableCell sx={{ color: '#888', fontSize: 10, p: 0.5, fontWeight: 700 }}>Error global</TableCell>
              <TableCell sx={{ color: '#888', fontSize: 10, p: 0.5, fontWeight: 700 }}>Despl. max [mm]</TableCell>
              <TableCell sx={{ color: '#888', fontSize: 10, p: 0.5, fontWeight: 700 }}>σ_vm max [MPa]</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {adaptiveLog.map((entry, i) => (
              <TableRow key={i} sx={{ bgcolor: i % 2 === 0 ? '#0a0a0a' : '#121212', '&:hover': { bgcolor: '#1a1a1a' } }}>
                <TableCell sx={{ color: '#aaa', fontSize: 9, p: 0.5 }}>{entry.cycle}</TableCell>
                <TableCell sx={{ color: '#aaa', fontSize: 9, p: 0.5 }}>{entry.n_nodes?.toLocaleString()}</TableCell>
                <TableCell sx={{ color: '#aaa', fontSize: 9, p: 0.5 }}>{entry.n_elements?.toLocaleString()}</TableCell>
                <TableCell sx={{ color: entry.global_error < 0.05 ? '#81c784' : '#ffa726', fontSize: 9, p: 0.5, fontWeight: entry.global_error < 0.05 ? 700 : 400 }}>
                  {(entry.global_error * 100).toFixed(2)}%
                </TableCell>
                <TableCell sx={{ color: '#aaa', fontSize: 9, p: 0.5 }}>{entry.max_displacement_mm?.toFixed(4)}</TableCell>
                <TableCell sx={{ color: '#aaa', fontSize: 9, p: 0.5 }}>{entry.max_von_mises_mpa?.toFixed(2)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}
