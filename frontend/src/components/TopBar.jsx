import React, { useState } from 'react';
import {
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  Box,
  Badge,
  Popover,
} from '@mui/material';
import { Menu as MenuIcon, PlayArrow, GridOn, ViewInAr } from '@mui/icons-material';
import { Tooltip, Chip } from '@mui/material';
import JobMonitor from './JobMonitor';

export default function TopBar({ onMenuClick, selectedFile, caeMode, onToggleCAE }) {
  const [jobsAnchor, setJobsAnchor] = useState(null);

  const handleJobsClick = (event) => {
    setJobsAnchor(event.currentTarget);
  };

  const handleJobsClose = () => {
    setJobsAnchor(null);
  };

  const jobsOpen = Boolean(jobsAnchor);

  return (
    <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar>
        <IconButton
          color="inherit"
          edge="start"
          onClick={onMenuClick}
          sx={{ mr: 2 }}
        >
          <MenuIcon />
        </IconButton>

        <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
          CAE Viewer
        </Typography>

        {selectedFile && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Typography variant="body2" color="inherit">
              {selectedFile.original_filename}
            </Typography>
          </Box>
        )}

        {/* Mode toggle STEP ↔ CAE */}
        <Tooltip title={caeMode ? 'Cambiar a modo STEP' : 'Cambiar a modo CAE/FEA'}>
          <Chip
            icon={caeMode ? <ViewInAr /> : <GridOn />}
            label={caeMode ? 'CAE' : 'STEP'}
            onClick={onToggleCAE}
            color={caeMode ? 'info' : 'default'}
            variant="outlined"
            size="small"
            sx={{ mx: 1, cursor: 'pointer', color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
          />
        </Tooltip>

        {/* Job Monitor Toggle */}
        <IconButton color="inherit" onClick={handleJobsClick} sx={{ ml: 2 }}>
          <Badge badgeContent={0} color="secondary">
            <PlayArrow />
          </Badge>
        </IconButton>

        {/* Job Monitor Popover */}
        <Popover
          open={jobsOpen}
          anchorEl={jobsAnchor}
          onClose={handleJobsClose}
          anchorOrigin={{
            vertical: 'bottom',
            horizontal: 'right',
          }}
          transformOrigin={{
            vertical: 'top',
            horizontal: 'right',
          }}
        >
          <Box sx={{ width: 400, maxHeight: 500, overflow: 'auto', p: 2 }}>
            <JobMonitor />
          </Box>
        </Popover>
      </Toolbar>
    </AppBar>
  );
}
