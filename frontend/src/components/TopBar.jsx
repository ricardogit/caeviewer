import React, { useEffect, useState } from 'react';
import {
  AppBar, Toolbar, IconButton, Typography, Box,
  Badge, Popover, Chip, Tooltip,
} from '@mui/material';
import { Menu as MenuIcon, PlayArrow, GridOn, ViewInAr, AccountTree, Category } from '@mui/icons-material';
import JobMonitor from './JobMonitor';
import useJobStore, { selectActiveCount } from '../stores/jobStore';

/**
 * TopBar — application header with three-mode selector.
 *
 * appMode: 'design' | 'step' | 'cae'
 * Shows active file/mesh and mode status indicators
 */
export default function TopBar({ onMenuClick, selectedFile, selectedMesh, appMode, onSetMode }) {
  const [jobsAnchor, setJobsAnchor] = useState(null);
  const jobsOpen = Boolean(jobsAnchor);
  const activeJobs = useJobStore(selectActiveCount);
  const initJobs = useJobStore((st) => st.init);
  useEffect(() => { initJobs(); }, [initJobs]);

  const modes = [
    { key: 'design', label: 'Design',  Icon: AccountTree, color: '#7986cb' },
    { key: 'geometry', label: 'Geometría', Icon: Category, color: '#ffb74d' },
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

        {/* Three-mode selector with status indicators */}
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          {modes.map(({ key, label, Icon, color }) => {
            const hasData =
              (key === 'step' && selectedFile) ||
              (key === 'cae' && selectedMesh) ||
              key === 'design';
            return (
              <Tooltip key={key} title={`Modo ${label}${hasData ? ' (activo)' : ''}`}>
                <Box sx={{ position: 'relative' }}>
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
                  {hasData && (
                    <Box
                      sx={{
                        position: 'absolute',
                        top: -4,
                        right: -4,
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        bgcolor: color,
                        border: '2px solid #121212',
                      }}
                    />
                  )}
                </Box>
              </Tooltip>
            );
          })}
        </Box>

        {/* Context info — show active file or mesh */}
        <Box sx={{ ml: 2, display: 'flex', flexDirection: 'column', gap: 0.25 }}>
          {selectedFile && (appMode === 'step' || appMode === 'cae') && (
            <Typography variant="body2" color="inherit" noWrap sx={{ maxWidth: 300, color: '#aaa', fontSize: 12 }}>
              {selectedFile.original_filename}
            </Typography>
          )}
          {selectedMesh && appMode === 'cae' && (
            <Typography variant="body2" color="inherit" noWrap sx={{ maxWidth: 300, color: '#90caf9', fontSize: 12 }}>
              Mesh: {selectedMesh.name || selectedMesh.id?.substring(0, 8)}
            </Typography>
          )}
        </Box>

        <Box sx={{ flex: 1 }} />

        {/* Job Monitor */}
        <IconButton color="inherit" onClick={e => setJobsAnchor(e.currentTarget)}>
          <Badge badgeContent={activeJobs} color="secondary">
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
