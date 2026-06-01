/**
 * DesignEdgeComponent — custom ReactFlow edge renderer.
 * Visual style (color, dash pattern) depends on edge_type.
 */
import React, { memo } from 'react';
import { BaseEdge, EdgeLabelRenderer, getBezierPath, getStraightPath } from 'reactflow';

const EDGE_STYLES = {
  FUNCTIONAL:      { color: '#2196f3', dash: 'none',     label: 'FUNCIONAL' },
  PHYSICAL:        { color: '#9e9e9e', dash: 'none',     label: 'FÍSICO' },
  DEPENDS_ON:      { color: '#607d8b', dash: '6,4',      label: 'DEPENDE DE' },
  MANUFACTURED_BY: { color: '#4caf50', dash: '8,4,2,4',  label: 'MANUFACTURA' },
  CONSTRAINS:      { color: '#f44336', dash: 'none',     label: 'RESTRINGE' },
  PRODUCES:        { color: '#00bcd4', dash: 'none',     label: 'PRODUCE' },
};

function DesignEdgeComponent({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  data, selected,
}) {
  const edgeType = data?.edge_type || 'PHYSICAL';
  const cfg = EDGE_STYLES[edgeType] || EDGE_STYLES.PHYSICAL;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: cfg.color,
          strokeWidth: selected ? 2.5 : 1.5,
          strokeDasharray: cfg.dash === 'none' ? undefined : cfg.dash,
          opacity: selected ? 1.0 : 0.75,
        }}
        markerEnd={`url(#arrow-${edgeType.toLowerCase()})`}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            fontSize: 9,
            background: '#1e1e1e',
            color: cfg.color,
            border: `1px solid ${cfg.color}55`,
            borderRadius: 3,
            padding: '1px 4px',
            pointerEvents: 'none',
            fontFamily: 'monospace',
            fontWeight: 600,
          }}
        >
          {cfg.label}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

export default memo(DesignEdgeComponent);
