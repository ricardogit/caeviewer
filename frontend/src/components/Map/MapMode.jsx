import React from 'react';
import { Box } from '@mui/material';
import MapView from './MapView';
import DomainPanel from './DomainPanel';

/** Mapa mode viewport (lazy chunk with Leaflet): map + domain / mesh panel. */
export default function MapMode() {
  return (
    <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
      <MapView />
      <DomainPanel />
    </Box>
  );
}
