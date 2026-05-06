import React, { useState, useEffect } from 'react';
import {
  Box, Typography, Tabs, Tab, Drawer, IconButton, Chip,
  CircularProgress, Alert, Paper, Table, TableBody,
  TableCell, TableHead, TableRow, LinearProgress, Button,
  Accordion, AccordionSummary, AccordionDetails, Tooltip,
  List, ListItem, ListItemText, ListItemIcon, Collapse,
} from '@mui/material';
import {
  Close, Schedule, AttachMoney, Build, SmartToy,
  ExpandMore, PictureAsPdf, Cancel, HighQuality,
  Inventory2, AccountTree, CheckCircle, Warning, FiberManualRecord,
  Layers, Straighten, ContentCut,
} from '@mui/icons-material';
import axios from 'axios';

const PLAN_WIDTH = 500;

const STRATEGY_COLORS = { balanced: 'primary', cost: 'success', time: 'warning', quality: 'info' };
const STRATEGY_LABELS = { balanced: 'Equilibrado', cost: 'Mín. Costo', time: 'Mín. Tiempo', quality: 'Máx. Calidad' };

function MetricCard({ icon, label, value, unit, color = 'primary' }) {
  return (
    <Paper sx={{ p: 1, textAlign: 'center', flex: 1, minWidth: 0 }}>
      <Box sx={{ color: `${color}.main`, display: 'flex', justifyContent: 'center', mb: 0.3 }}>{icon}</Box>
      <Typography variant="subtitle2" color={`${color}.main`} noWrap>{value}</Typography>
      <Typography variant="caption" color="text.secondary" display="block" noWrap>{unit || ' '}</Typography>
      <Typography variant="caption" color="text.secondary" display="block" noWrap sx={{ fontSize: '0.65rem' }}>{label}</Typography>
    </Paper>
  );
}

function OperationsTab({ operations }) {
  if (!operations?.length) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No hay operaciones disponibles para este plan.
        </Typography>
      </Box>
    );
  }
  return (
    <Box sx={{ overflow: 'auto' }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: 36 }}>#</TableCell>
            <TableCell>Operación</TableCell>
            <TableCell align="right" sx={{ width: 72 }}>Tiempo</TableCell>
            <TableCell align="right" sx={{ width: 72 }}>Costo</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {operations.map((op, i) => {
            const seq = op.sequence_order ?? op.sequence ?? i + 1;
            const type = op.operation_type || op.type || 'Operación';
            const time = op.estimated_duration ?? op.estimated_time;
            const cost = op.estimated_cost;
            return (
              <TableRow key={op.operation_id || i} hover>
                <TableCell>{seq}</TableCell>
                <TableCell>
                  <Typography variant="body2" noWrap>{type}</Typography>
                  {op.machine_id && (
                    <Typography variant="caption" color="text.secondary" display="block" noWrap>
                      Máq: {op.machine_id}
                    </Typography>
                  )}
                  {op.tool_id && (
                    <Typography variant="caption" color="text.secondary" display="block" noWrap>
                      Herr: {op.tool_id}
                    </Typography>
                  )}
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {time != null ? `${Number(time).toFixed(1)} min` : '—'}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {cost != null ? `$${Number(cost).toFixed(2)}` : '—'}
                  </Typography>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Box>
  );
}

function ReasoningTab({ reasoning, recommendations }) {
  const steps = Array.isArray(reasoning)
    ? reasoning
    : (reasoning?.steps || reasoning?.decision_steps || []);

  const hasContent = steps.length > 0 || (recommendations?.length > 0);

  if (!hasContent) {
    return (
      <Box sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          El razonamiento detallado no está disponible. El modelo AI tomó sus decisiones
          basándose en las características geométricas de la pieza, el material seleccionado
          y la estrategia de optimización.
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ overflow: 'auto' }}>
      {recommendations?.length > 0 && (
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            <SmartToy sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'middle' }} />
            Recomendaciones del AI
          </Typography>
          {recommendations.map((rec, i) => (
            <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', mb: 0.75 }}>
              <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'primary.main', mt: '6px', mr: 1, flexShrink: 0 }} />
              <Typography variant="body2">{rec}</Typography>
            </Box>
          ))}
        </Box>
      )}

      {steps.map((step, i) => (
        <Accordion key={i} disableGutters elevation={0}
          sx={{ '&:before': { display: 'none' }, borderBottom: '1px solid', borderColor: 'divider' }}
        >
          <AccordionSummary expandIcon={<ExpandMore />} sx={{ px: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1, minWidth: 0 }}>
              <Chip label={i + 1} size="small" color="primary" sx={{ width: 26, height: 20, fontSize: '0.7rem' }} />
              <Typography variant="body2" fontWeight="medium" noWrap sx={{ flex: 1 }}>
                {step.decision_point || step.question || `Decisión ${i + 1}`}
              </Typography>
              {step.confidence_score != null && (
                <Chip
                  label={`${Math.round(step.confidence_score * 100)}%`}
                  size="small"
                  color={step.confidence_score > 0.7 ? 'success' : step.confidence_score > 0.4 ? 'warning' : 'error'}
                  sx={{ flexShrink: 0 }}
                />
              )}
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 2, pb: 2 }}>
            {step.question && step.question !== step.decision_point && (
              <Typography variant="body2" sx={{ mb: 0.5 }}>
                <Box component="span" color="text.secondary">Pregunta: </Box>{step.question}
              </Typography>
            )}
            {step.answer && (
              <Typography variant="body2" sx={{ mb: 1 }}>
                <Box component="span" color="text.secondary">Respuesta: </Box>{step.answer}
              </Typography>
            )}
            {step.factors_json && Object.keys(step.factors_json).length > 0 && (
              <Box sx={{ mb: 1 }}>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                  Factores:
                </Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {Object.entries(step.factors_json).map(([k, v]) => (
                    <Chip key={k} label={`${k}: ${v}`} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
                  ))}
                </Box>
              </Box>
            )}
            {step.alternatives_considered?.length > 0 && (
              <Box sx={{ mb: 1 }}>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                  Alternativas descartadas:
                </Typography>
                {step.alternatives_considered.map((alt, j) => (
                  <Box key={j} sx={{ display: 'flex', alignItems: 'flex-start', mb: 0.3 }}>
                    <Cancel sx={{ fontSize: 13, mr: 0.5, mt: 0.3, color: 'error.main', flexShrink: 0 }} />
                    <Typography variant="body2">
                      <strong>{alt.option || alt.name || alt}</strong>
                      {alt.rejected_reason && ` — ${alt.rejected_reason}`}
                    </Typography>
                  </Box>
                ))}
              </Box>
            )}
            {step.confidence_score != null && (
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Confianza: {Math.round(step.confidence_score * 100)}%
                </Typography>
                <LinearProgress
                  variant="determinate"
                  value={step.confidence_score * 100}
                  color={step.confidence_score > 0.7 ? 'success' : step.confidence_score > 0.4 ? 'warning' : 'error'}
                  sx={{ mt: 0.5, borderRadius: 1 }}
                />
              </Box>
            )}
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  );
}

function BOMNode({ item, depth = 0 }) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = item.children?.length > 0;
  return (
    <>
      <ListItem
        disablePadding
        sx={{ pl: depth * 2, cursor: hasChildren ? 'pointer' : 'default' }}
        onClick={() => hasChildren && setOpen(!open)}
      >
        <ListItemIcon sx={{ minWidth: 24 }}>
          {hasChildren
            ? <AccountTree sx={{ fontSize: 14, color: 'primary.main' }} />
            : <FiberManualRecord sx={{ fontSize: 8, color: 'text.disabled' }} />}
        </ListItemIcon>
        <ListItemText
          primary={
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
              <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>{item.name}</Typography>
              {item.quantity > 1 && <Chip label={`×${item.quantity}`} size="small" sx={{ height: 16, fontSize: '0.65rem' }} />}
              {item.fit_type && item.fit_type !== 'clearance' && (
                <Chip label={item.fit_type} size="small" color="warning" sx={{ height: 16, fontSize: '0.65rem' }} />
              )}
            </Box>
          }
          secondary={
            <Typography variant="caption" color="text.secondary">
              {[item.part_number, item.material].filter(Boolean).join(' • ')}
            </Typography>
          }
        />
        {hasChildren && (
          <Typography variant="caption" color="text.secondary" sx={{ mr: 1 }}>
            {open ? '▲' : '▼'}
          </Typography>
        )}
      </ListItem>
      {hasChildren && (
        <Collapse in={open} timeout="auto" unmountOnExit>
          <List disablePadding>
            {item.children.map((child, i) => (
              <BOMNode key={child.item_id || i} item={child} depth={depth + 1} />
            ))}
          </List>
        </Collapse>
      )}
    </>
  );
}

function AssemblyTab({ assemblyMeta, bom, toleranceChains }) {
  const [bomOpen, setBomOpen] = useState(true);
  const [seqOpen, setSeqOpen] = useState(true);
  const [tolOpen, setTolOpen] = useState(true);

  const hasBom = bom?.length > 0;
  const hasTol = toleranceChains?.length > 0;

  if (!assemblyMeta && !hasBom) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="info">
          Este plan no tiene datos de ensamble. Usa <strong>Generar plan → Ensamble</strong>
          {' '}para obtener BOM, secuencia y análisis de tolerancias.
        </Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ overflow: 'auto' }}>
      {/* Assembly summary */}
      {assemblyMeta && (
        <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider', display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Chip icon={<Inventory2 sx={{ fontSize: 14 }} />} label={`${assemblyMeta.total_components} componentes`} size="small" />
          <Chip icon={<Build sx={{ fontSize: 14 }} />} label={`${assemblyMeta.total_fasteners} sujetadores`} size="small" />
          <Chip icon={<AccountTree sx={{ fontSize: 14 }} />} label={`${assemblyMeta.bom_levels} niveles`} size="small" />
        </Box>
      )}

      {/* BOM tree */}
      {hasBom && (
        <Accordion expanded={bomOpen} onChange={() => setBomOpen(!bomOpen)} disableGutters elevation={0}
          sx={{ '&:before': { display: 'none' }, borderBottom: '1px solid', borderColor: 'divider' }}
        >
          <AccordionSummary expandIcon={<ExpandMore />} sx={{ px: 2, minHeight: 40 }}>
            <Typography variant="subtitle2">Lista de materiales (BOM)</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ p: 0 }}>
            <List dense disablePadding>
              {bom.map((item, i) => <BOMNode key={item.item_id || i} item={item} depth={0} />)}
            </List>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Tolerance chains */}
      {hasTol && (
        <Accordion expanded={tolOpen} onChange={() => setTolOpen(!tolOpen)} disableGutters elevation={0}
          sx={{ '&:before': { display: 'none' }, borderBottom: '1px solid', borderColor: 'divider' }}
        >
          <AccordionSummary expandIcon={<ExpandMore />} sx={{ px: 2, minHeight: 40 }}>
            <Typography variant="subtitle2">Cadenas de tolerancias</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 2, pb: 1 }}>
            {toleranceChains.map((tc, i) => (
              <Paper key={i} variant="outlined" sx={{ p: 1, mb: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  {tc.is_feasible
                    ? <CheckCircle sx={{ fontSize: 16, color: 'success.main' }} />
                    : <Warning sx={{ fontSize: 16, color: 'error.main' }} />}
                  <Typography variant="caption" fontWeight="bold">
                    Cadena {i + 1} — gap nominal {tc.nominal_gap_mm?.toFixed(3)} mm
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                  <Typography variant="caption" color={tc.worst_case_gap_mm < 0 ? 'error.main' : 'text.secondary'}>
                    Peor caso: {tc.worst_case_gap_mm?.toFixed(3)} mm
                  </Typography>
                  <Typography variant="caption" color={tc.rss_gap_mm < 0 ? 'warning.main' : 'text.secondary'}>
                    RSS: {tc.rss_gap_mm?.toFixed(3)} mm
                  </Typography>
                </Box>
                {tc.warnings?.map((w, j) => (
                  <Typography key={j} variant="caption" color="warning.main" display="block" sx={{ mt: 0.3 }}>
                    ⚠ {w}
                  </Typography>
                ))}
              </Paper>
            ))}
          </AccordionDetails>
        </Accordion>
      )}
    </Box>
  );
}

const CUTTING_LABEL = {
  laser_cutting: 'Corte láser', plasma_cutting: 'Corte plasma',
  waterjet_cutting: 'Corte agua', shearing: 'Cizalla', blanking: 'Troquelado',
};
const CONFIDENCE_COLOR = (c) => c >= 0.8 ? 'success' : c >= 0.5 ? 'warning' : 'error';

function SheetMetalTab({ sheetMeta, operations, material, warnings }) {
  const thickness = sheetMeta?.thickness_mm;
  const confidence = sheetMeta?.confidence ?? 0;
  const reason = sheetMeta?.reason;

  const opsByType = (operations || []).reduce((acc, op) => {
    const t = op.operation_type || op.type || 'other';
    if (!acc[t]) acc[t] = { count: 0, time: 0, cost: 0 };
    acc[t].count += 1;
    acc[t].time += op.estimated_duration ?? op.estimated_time ?? 0;
    acc[t].cost += op.estimated_cost ?? 0;
    return acc;
  }, {});

  const cuttingOp = Object.keys(opsByType).find(k => CUTTING_LABEL[k]);

  if (!sheetMeta && !operations?.length) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="info">
          Usa <strong>Generar plan → Chapa</strong> para obtener análisis de geometría, método de corte y secuencia de doblado.
        </Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ overflow: 'auto' }}>
      {/* Geometry detection */}
      {sheetMeta && (
        <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="subtitle2" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Layers fontSize="small" color="primary" /> Geometría detectada
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1 }}>
            {thickness != null && (
              <Chip icon={<Straighten sx={{ fontSize: 14 }} />}
                label={`Espesor: ${thickness.toFixed(2)} mm`} size="small" color="primary" variant="outlined" />
            )}
            <Chip label={`Confianza: ${Math.round(confidence * 100)}%`} size="small"
              color={CONFIDENCE_COLOR(confidence)} variant="outlined" />
            {cuttingOp && (
              <Chip icon={<ContentCut sx={{ fontSize: 14 }} />}
                label={CUTTING_LABEL[cuttingOp]} size="small" color="info" />
            )}
            {material && (
              <Chip icon={<Layers sx={{ fontSize: 14 }} />} label={material} size="small" variant="outlined" />
            )}
          </Box>
          {reason && (
            <Typography variant="caption" color="text.secondary">{reason}</Typography>
          )}
        </Box>
      )}

      {/* Operations breakdown */}
      {Object.keys(opsByType).length > 0 && (
        <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="subtitle2" gutterBottom>Secuencia de operaciones</Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Operación</TableCell>
                <TableCell align="right" sx={{ width: 56 }}>Tiempo</TableCell>
                <TableCell align="right" sx={{ width: 64 }}>Costo</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {Object.entries(opsByType).map(([type, data]) => (
                <TableRow key={type} hover>
                  <TableCell>
                    <Typography variant="caption">{type.replace(/_/g, ' ')}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="caption">{data.time > 0 ? `${data.time.toFixed(0)} min` : '—'}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="caption" color="success.main">
                      {data.cost > 0 ? `$${data.cost.toFixed(0)}` : '—'}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      {/* Warnings */}
      {warnings?.length > 0 && (
        <Box sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" gutterBottom>Advertencias</Typography>
          {warnings.map((w, i) => (
            <Alert key={i} severity="warning" sx={{ mb: 0.5, py: 0 }}>
              <Typography variant="caption">{w}</Typography>
            </Alert>
          ))}
        </Box>
      )}
    </Box>
  );
}

function HistoryTab({ plans, currentPlanId, onSelectPlan }) {
  return (
    <Box sx={{ p: 1, overflow: 'auto' }}>
      {plans.map((p) => (
        <Paper
          key={p.id}
          elevation={p.id === currentPlanId ? 3 : 1}
          onClick={() => onSelectPlan(p.id)}
          sx={{
            p: 1.5, mb: 1, cursor: 'pointer',
            border: '1px solid',
            borderColor: p.id === currentPlanId ? 'primary.main' : 'divider',
            '&:hover': { borderColor: 'primary.light' },
          }}
        >
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
            <Typography variant="caption" color="text.secondary">
              {p.created_at ? new Date(p.created_at).toLocaleString() : '—'}
            </Typography>
            <Chip label={p.status || 'draft'} size="small"
              color={p.status === 'completed' ? 'success' : 'default'} />
          </Box>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {p.total_time != null && (
              <Typography variant="caption"><Schedule sx={{ fontSize: 12, mr: 0.3 }} />{Number(p.total_time).toFixed(0)} min</Typography>
            )}
            {p.total_cost != null && (
              <Typography variant="caption"><AttachMoney sx={{ fontSize: 12, mr: 0.3 }} />${Number(p.total_cost).toFixed(0)}</Typography>
            )}
          </Box>
        </Paper>
      ))}
    </Box>
  );
}

export default function PlanViewer({ open, onClose, planData, selectedFile }) {
  const [tab, setTab] = useState(0);
  const [fullPlan, setFullPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [partPlans, setPartPlans] = useState([]);

  useEffect(() => {
    if (!open) return;
    const planId = planData?.database_id || planData?.plan?.id || planData?.plan_id;
    if (planId && planId !== 'N/A') {
      loadPlan(planId);
    } else {
      setFullPlan(null);
    }
  }, [planData, open]);

  useEffect(() => {
    if (!open || !selectedFile) return;
    const partId = selectedFile.part_id || selectedFile.id;
    if (!partId) return;
    axios.get(`/api/v2/plans?part_id=${partId}&limit=10`)
      .then(res => setPartPlans(res.data.plans || []))
      .catch(() => {});
  }, [open, selectedFile, planData]);

  async function loadPlan(planId) {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`/api/v2/plans/${planId}`);
      setFullPlan(res.data);
    } catch {
      setError('No se pudieron cargar los detalles completos del plan.');
    } finally {
      setLoading(false);
    }
  }

  async function handleExportPdf() {
    const planId = fullPlan?.id;
    if (!planId) return;
    try {
      const res = await axios.get(`/api/v2/plans/${planId}/export/pdf`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = `plan_${planId.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('Error al exportar PDF.');
    }
  }

  const summary = planData?.summary || {};
  const operations = fullPlan?.operations_sequence || planData?.operations || [];
  const recommendations = planData?.recommendations || summary?.recommendations || [];
  const reasoning = fullPlan?.reasoning_json || fullPlan?.reasoning_steps || null;
  const totalTime = fullPlan?.estimated_makespan ?? summary?.estimated_time_minutes;
  const totalCost = fullPlan?.estimated_cost ?? summary?.estimated_cost;
  const qualityScore = fullPlan?.estimated_quality_score;
  const opsCount = fullPlan?.operations_count ?? operations.length ?? summary?.total_operations;
  const strategy = fullPlan?.strategy || 'balanced';
  const planName = fullPlan?.name || planData?.part?.name || selectedFile?.original_filename || 'Plan';
  const showHistory = partPlans.length > 1;

  // Assembly metadata from plan output
  const assemblyMeta = (
    planData?.metadata?.assembly_plan ||
    fullPlan?.scheduling_metrics?.summary?.assembly_plan ||
    null
  );
  const assemblyBom = planData?.metadata?.bom || fullPlan?.metadata?.bom || null;
  const toleranceChains = planData?.metadata?.tolerance_chains || null;
  const isAssemblyPlan = (
    planData?.process_type === 'assembly' ||
    fullPlan?.process_type === 'assembly' ||
    !!assemblyMeta
  );

  // Sheet metal metadata from plan output
  const sheetMeta = planData?.metadata?.sheet_geometry || fullPlan?.metadata?.sheet_geometry || null;
  const sheetMaterial = planData?.metadata?.material || fullPlan?.metadata?.material || null;
  // warnings are at top-level in the API response (plan_output.warnings)
  const sheetWarnings = planData?.warnings || fullPlan?.warnings || [];
  const isSheetMetalPlan = (
    planData?.process_type === 'sheet_metal' ||
    fullPlan?.process_type === 'sheet_metal' ||
    !!sheetMeta
  );

  // Special tab label (assembly and sheet metal are mutually exclusive plan types)
  const specialTab = isAssemblyPlan ? 'Ensamble' : isSheetMetalPlan ? 'Chapa' : null;
  const historyTabIndex = specialTab ? (showHistory ? 3 : null) : (showHistory ? 2 : null);

  return (
    <Drawer
      variant="persistent"
      anchor="right"
      open={open}
      sx={{
        width: PLAN_WIDTH,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: PLAN_WIDTH,
          boxSizing: 'border-box',
          mt: '64px',
          height: 'calc(100% - 64px)',
          zIndex: 1150,
          display: 'flex',
          flexDirection: 'column',
        },
      }}
    >
      {/* Header */}
      <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider', flexShrink: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <Box sx={{ flex: 1, mr: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" fontWeight="bold" noWrap>{planName}</Typography>
            <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
              <Chip label={STRATEGY_LABELS[strategy] || strategy} size="small"
                color={STRATEGY_COLORS[strategy] || 'default'} />
              {fullPlan?.status && (
                <Chip label={fullPlan.status} size="small" variant="outlined"
                  color={fullPlan.status === 'completed' ? 'success' : 'default'} />
              )}
              {fullPlan?.confidence_score != null && (
                <Tooltip title="Confianza del modelo AI">
                  <Chip label={`IA ${Math.round(fullPlan.confidence_score * 100)}%`}
                    size="small" color="info" />
                </Tooltip>
              )}
            </Box>
          </Box>
          <IconButton onClick={onClose} size="small"><Close /></IconButton>
        </Box>
      </Box>

      {loading && <LinearProgress />}
      {error && <Alert severity="warning" sx={{ m: 1 }} onClose={() => setError(null)}>{error}</Alert>}
      {!loading && !fullPlan && !planData && (
        <Alert severity="info" sx={{ m: 1.5 }}>
          No hay plan generado. Abre la configuración del plan (⚙) y haz clic en <strong>Generar plan de fabricación</strong>.
        </Alert>
      )}

      {/* Metrics strip */}
      <Box sx={{ display: 'flex', gap: 0.75, p: 1, borderBottom: 1, borderColor: 'divider', flexShrink: 0 }}>
        <MetricCard icon={<Schedule fontSize="small" />} label="Tiempo" unit="min"
          value={totalTime != null ? Number(totalTime).toFixed(0) : '—'} color="warning" />
        <MetricCard icon={<AttachMoney fontSize="small" />} label="Costo" unit="USD"
          value={totalCost != null ? `$${Number(totalCost).toFixed(0)}` : '—'} color="success" />
        <MetricCard icon={<Build fontSize="small" />} label="Operaciones" unit="pasos"
          value={opsCount ?? '—'} color="primary" />
        {qualityScore != null && (
          <MetricCard icon={<HighQuality fontSize="small" />} label="Calidad" unit=""
            value={`${Math.round(qualityScore * 100)}%`} color="info" />
        )}
      </Box>

      {/* Tabs */}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto"
        sx={{ borderBottom: 1, borderColor: 'divider', flexShrink: 0, minHeight: 40 }}
        TabIndicatorProps={{ style: { height: 2 } }}
      >
        <Tab label="Operaciones" sx={{ minHeight: 40, fontSize: '0.8rem' }} />
        <Tab label="Razonamiento AI" sx={{ minHeight: 40, fontSize: '0.8rem' }} />
        {specialTab && <Tab label={specialTab} sx={{ minHeight: 40, fontSize: '0.8rem' }} />}
        {showHistory && <Tab label="Historial" sx={{ minHeight: 40, fontSize: '0.8rem' }} />}
      </Tabs>

      {/* Content */}
      <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
        {tab === 0 && <OperationsTab operations={operations} />}
        {tab === 1 && <ReasoningTab reasoning={reasoning} recommendations={recommendations} />}
        {tab === 2 && isAssemblyPlan && (
          <AssemblyTab
            assemblyMeta={assemblyMeta}
            bom={assemblyBom}
            toleranceChains={toleranceChains}
          />
        )}
        {tab === 2 && isSheetMetalPlan && (
          <SheetMetalTab
            sheetMeta={sheetMeta}
            operations={operations}
            material={sheetMaterial}
            warnings={sheetWarnings}
          />
        )}
        {tab === historyTabIndex && showHistory && (
          <HistoryTab
            plans={partPlans}
            currentPlanId={fullPlan?.id}
            onSelectPlan={loadPlan}
          />
        )}
      </Box>

      {/* Footer */}
      <Box sx={{ p: 1.5, borderTop: 1, borderColor: 'divider', flexShrink: 0 }}>
        <Button variant="outlined" size="small" fullWidth startIcon={<PictureAsPdf />}
          onClick={handleExportPdf} disabled={!fullPlan?.id}
        >
          Exportar PDF
        </Button>
      </Box>
    </Drawer>
  );
}
