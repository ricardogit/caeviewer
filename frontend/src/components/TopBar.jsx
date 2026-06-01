import React, { useState } from 'react';
import {
  AppBar, Toolbar, IconButton, Typography, Box,
  Badge, Popover, Chip, Tooltip,
} from '@mui/material';
import { Menu as MenuIcon, PlayArrow, GridOn, ViewInAr, AccountTree } from '@mui/icons-material';
import JobMonitor from './JobMonitor';

/**
 * TopBar — application header with three-mode selector.
 *
 * appMode: 'design' | 'step' | 'cae'
 */
export default function TopBar({ onMenuClick, selectedFile, appMode, onSetMode }) {
  const [jobsAnchor, setJobsAnchor] = useState(null);
  const jobsOpen = Boolean(jobsAnchor);

  const modes = [
    { key: 'design', label: 'Design',  Icon: AccountTree, color: '#7986cb' },
    { key: 'step',   label: 'STEP',    Icon: ViewInAr,    color: '#90caf9' },
    { key: 'cae',    label: 'CAE/FEA', Icon: GridOn,      color: '#80cbc4' },
  ];

  return (
    <AppBar position="fixed" sx={{ zIndex: theme => theme.zIndex.drawer + 1 }}>
      <Toolbar>
        <IconButton color="inherit" edge="start" onClick={onMenuClick} sx={{ mr: 2 }}>
          <MenuIcon />
        </IconButton>

        <Typography variant="h6" noWrap component="div" sx={{ mr: 3 }}>
          CAE Lab
        </Typography>

        {/* Three-mode selector */}
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {modes.map(({ key, label, Icon, color }) => (
            <Tooltip key={key} title={`Modo ${label}`}>
              <Chip
                icon={<Icon sx={{ fontSize: 14, color: appMode === key ? '#000' : color }} />}
                label={label}
                onClick={() => onSetMode(key)}
                size="small"
                sx={{
                  cursor: 'pointer',
                  bgcolor: appMode === key ? color : 'transparent',
                  color: appMode === key ? '#000' : color,
                  borderColor: color,
                  border: '1px solid',
                  fontWeight: appMode === key ? 700 : 400,
                  transition: 'all 0.15s',
                  '& .MuiChip-icon': { ml: 0.5 },
                }}
              />
            </Tooltip>
          ))}
        </Box>

        {/* Context info */}
        {selectedFile && appMode !== 'design' && (
          <Box sx={{ ml: 2 }}>
            <Typography variant="body2" color="inherit" noWrap sx={{ maxWidth: 260, color: '#aaa' }}>
              {selectedFile.original_filename}
            </Typography>
          </Box>
        )}

        <Box sx={{ flex: 1 }} />

        {/* Job Monitor */}
        <IconButton color="inherit" onClick={e => setJobsAnchor(e.currentTarget)}>
          <Badge badgeContent={0} color="secondary">
            <PlayArrow />
          </Badge>
        </IconButton>

        <Popover
          open={jobsOpen}
          anchorEl={jobsAnchor}
          onClose={() => setJobsAnchor(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        >
          <Box sx={{ width: 400, maxHeight: 500, overflow: 'auto', p: 2 }}>
            <JobMonitor />
          </Box>
        </Popover>
      </Toolbar>
    </AppBar>
  );
}
