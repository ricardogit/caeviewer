import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  TextField,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  ListItemIcon,
  Collapse,
  IconButton,
} from '@mui/material';
import {
  ExpandMore,
  ChevronRight,
  Search as SearchIcon,
  AccountTree,
} from '@mui/icons-material';
import axios from 'axios';

/**
 * EntityTree - Árbol jerárquico de entidades STEP con carga lazy
 *
 * Props:
 * - headerId: UUID del STEP file header
 * - onEntitySelect: Callback(entityId) cuando se selecciona una entidad
 * - selectedEntityId: ID de la entidad actualmente seleccionada
 */
export default function EntityTree({ headerId, onEntitySelect, selectedEntityId }) {
  const [roots, setRoots] = useState([]);
  const [metadata, setMetadata] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [expanded, setExpanded] = useState(new Set());
  const [childrenCache, setChildrenCache] = useState({});
  const [loadingNodes, setLoadingNodes] = useState(new Set());
  const [isLazy, setIsLazy] = useState(false);

  useEffect(() => {
    if (!headerId) return;
    setChildrenCache({});
    setExpanded(new Set());
    loadTree();
  }, [headerId]);

  async function loadTree() {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`/api/step-view/graph/${headerId}/tree`);
      const data = response.data;

      setMetadata(data.metadata || null);
      setIsLazy(!!data.metadata?.lazy);

      const rootNodes = data.roots || [];
      setRoots(rootNodes);

      // Pre-expand root ids
      setExpanded(new Set(rootNodes.map(r => r.entity_id)));
    } catch (err) {
      console.error('Error loading tree:', err);
      setError(err.response?.data?.error || err.message || 'Failed to load entity tree');
    } finally {
      setLoading(false);
    }
  }

  const fetchChildren = useCallback(async (entityId) => {
    if (childrenCache[entityId] !== undefined || loadingNodes.has(entityId)) return;

    setLoadingNodes(prev => new Set([...prev, entityId]));
    try {
      const response = await axios.get(
        `/api/step-view/graph/${headerId}/entity/${entityId}/children`
      );
      const children = response.data.children || [];
      setChildrenCache(prev => ({ ...prev, [entityId]: children }));
    } catch (err) {
      console.error(`Error loading children of ${entityId}:`, err);
      setChildrenCache(prev => ({ ...prev, [entityId]: [] }));
    } finally {
      setLoadingNodes(prev => {
        const next = new Set(prev);
        next.delete(entityId);
        return next;
      });
    }
  }, [headerId, childrenCache, loadingNodes]);

  function handleToggle(entityId) {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(entityId)) {
        next.delete(entityId);
      } else {
        next.add(entityId);
        if (isLazy) fetchChildren(entityId);
      }
      return next;
    });
  }

  function handleSelect(entityId) {
    if (onEntitySelect) onEntitySelect(entityId);
  }

  async function handleSearch() {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    try {
      const response = await axios.post(`/api/step-view/graph/${headerId}/search`, {
        query: searchQuery,
        limit: 50,
      });
      setSearchResults(response.data.results || []);
    } catch (err) {
      console.error('Error searching:', err);
    }
  }

  async function handleSearchResultClick(entityId) {
    if (onEntitySelect) onEntitySelect(entityId);
    if (!isLazy) {
      try {
        const response = await axios.get(
          `/api/step-view/graph/${headerId}/entity/${entityId}/path-to-root`
        );
        if (response.data?.path) {
          const pathIds = response.data.path.map(item => item.entity_id);
          setExpanded(prev => new Set([...prev, ...pathIds]));
        }
      } catch (err) {
        console.error('Error expanding path:', err);
      }
    }
  }

  function renderTreeNode(node, depth = 0) {
    if (!node) return null;
    const isSelected = node.entity_id === selectedEntityId;
    const isLoadingThis = loadingNodes.has(node.entity_id);
    const isExpanded = expanded.has(node.entity_id);

    let children;
    if (isLazy) {
      const cached = childrenCache[node.entity_id];
      children = cached !== undefined ? cached : null;
    } else {
      children = node.children || [];
    }

    const hasChildren = isLazy
      ? (node.has_children || (children && children.length > 0))
      : (children && children.length > 0);

    return (
      <React.Fragment key={node.entity_id}>
        <ListItem
          disablePadding
          sx={{ pl: depth * 2 }}
        >
          <ListItemButton
            dense
            selected={isSelected}
            onClick={() => handleSelect(node.entity_id)}
            sx={{
              borderRadius: 1,
              py: 0.25,
              '&.Mui-selected': {
                backgroundColor: 'primary.dark',
                '&:hover': { backgroundColor: 'primary.main' },
              },
            }}
          >
            <ListItemIcon sx={{ minWidth: 24 }}>
              {isLoadingThis ? (
                <CircularProgress size={12} />
              ) : hasChildren ? (
                <IconButton
                  size="small"
                  sx={{ p: 0 }}
                  onClick={(e) => { e.stopPropagation(); handleToggle(node.entity_id); }}
                >
                  {isExpanded
                    ? <ExpandMore sx={{ fontSize: 16 }} />
                    : <ChevronRight sx={{ fontSize: 16 }} />}
                </IconButton>
              ) : (
                <Box sx={{ width: 16 }} />
              )}
            </ListItemIcon>
            <ListItemText
              disableTypography
              primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
                  <Typography variant="body2" sx={{ fontWeight: isSelected ? 'bold' : 'normal', fontSize: '0.75rem' }}>
                    #{node.entity_id}
                  </Typography>
                  <Chip
                    label={node.entity_type}
                    size="small"
                    sx={{ fontSize: '0.65rem', height: 18 }}
                    color={isSelected ? 'primary' : 'default'}
                  />
                  {node.entity_label && (
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
                      {node.entity_label}
                    </Typography>
                  )}
                  {node.manufacturing_feature && (
                    <Chip
                      label={node.manufacturing_feature}
                      size="small"
                      color="secondary"
                      sx={{ fontSize: '0.62rem', height: 16 }}
                    />
                  )}
                </Box>
              }
            />
          </ListItemButton>
        </ListItem>

        {hasChildren && (
          <Collapse in={isExpanded} timeout="auto" unmountOnExit>
            {isLazy && children === null ? (
              <ListItem sx={{ pl: (depth + 1) * 2 + 3 }}>
                <CircularProgress size={12} sx={{ mr: 1 }} />
                <Typography variant="caption" color="text.secondary">Loading...</Typography>
              </ListItem>
            ) : (
              (children || []).map(child => renderTreeNode(child, depth + 1))
            )}
          </Collapse>
        )}
      </React.Fragment>
    );
  }

  if (loading) {
    return (
      <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={30} />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  if (!roots.length) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="info">No entity tree available</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <AccountTree fontSize="small" />
          <Typography variant="subtitle2">Entity Graph</Typography>
        </Box>
        {metadata && (
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Chip label={`${metadata.total_nodes} nodes`} size="small" variant="outlined" />
            {metadata.root_count != null && (
              <Chip label={`${metadata.root_count} roots`} size="small" variant="outlined" />
            )}
            {metadata.max_depth != null && (
              <Chip label={`depth ${metadata.max_depth}`} size="small" variant="outlined" />
            )}
            {metadata.lazy && (
              <Chip label="lazy" size="small" color="info" variant="outlined" />
            )}
          </Box>
        )}
        {metadata?.truncated && (
          <Alert severity="info" sx={{ mt: 1, py: 0.5, fontSize: '0.75rem' }}>
            {metadata.message}
          </Alert>
        )}
      </Box>

      {/* Search */}
      <Accordion defaultExpanded={false}>
        <AccordionSummary expandIcon={<ExpandMore />}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <SearchIcon fontSize="small" />
            <Typography variant="body2">Search</Typography>
          </Box>
        </AccordionSummary>
        <AccordionDetails>
          <TextField
            size="small"
            fullWidth
            placeholder="Search entities..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            InputProps={{
              endAdornment: (
                <IconButton size="small" onClick={handleSearch}>
                  <SearchIcon fontSize="small" />
                </IconButton>
              ),
            }}
          />
          {searchResults.length > 0 && (
            <List dense sx={{ mt: 1, maxHeight: 200, overflow: 'auto' }}>
              {searchResults.map((result) => (
                <ListItem key={result.entity_id} disablePadding>
                  <ListItemButton onClick={() => handleSearchResultClick(result.entity_id)}>
                    <ListItemText
                      primary={
                        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                          <Typography variant="caption">#{result.entity_id}</Typography>
                          <Chip label={result.entity_type} size="small" sx={{ fontSize: '0.65rem' }} />
                        </Box>
                      }
                      secondary={result.entity_label}
                    />
                  </ListItemButton>
                </ListItem>
              ))}
            </List>
          )}
        </AccordionDetails>
      </Accordion>

      {/* Tree */}
      <Box sx={{ flexGrow: 1, overflow: 'auto', p: 1 }}>
        <List dense disablePadding>
          {roots.map(node => renderTreeNode(node, 0))}
        </List>
      </Box>
    </Box>
  );
}
