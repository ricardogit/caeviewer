import { useEffect } from 'react';
import { useMap } from 'react-leaflet';
import { depthColor } from '../../utils/geoDomain';

/**
 * Triangle mesh drawn on a canvas over the map (thousands of triangles: one Leaflet polygon each would be too
 * slow). Filled by node depth (mean of the corners), thin edges; redrawn on every map move / zoom.
 */
export default function MeshCanvasLayer({ mesh, fill = true }) {
  const map = useMap();
  useEffect(() => {
    if (!mesh) return undefined;
    const container = map.getContainer();
    const canvas = document.createElement('canvas');
    Object.assign(canvas.style, { position: 'absolute', left: 0, top: 0, pointerEvents: 'none', zIndex: 450 });
    container.appendChild(canvas);
    const depth = mesh.depth || [];
    const zmax = depth.reduce((m, z) => (z > m ? z : m), 1);     // no spread: meshes can have 10⁵ nodes
    const draw = () => {
      const size = map.getSize();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = size.x * dpr;
      canvas.height = size.y * dpr;
      canvas.style.width = `${size.x}px`;
      canvas.style.height = `${size.y}px`;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const pts = mesh.nodes.map(([lon, lat]) => map.latLngToContainerPoint([lat, lon]));
      // edges only when triangles are big enough on screen (else the lines paint the mesh black)
      let sum = 0; let cnt = 0;
      for (let e = 0; e < mesh.tris.length; e += Math.max(1, Math.floor(mesh.tris.length / 500))) {
        const [a, b] = mesh.tris[e];
        sum += Math.hypot(pts[a].x - pts[b].x, pts[a].y - pts[b].y); cnt += 1;
      }
      const strokes = cnt && sum / cnt > 5;
      ctx.lineWidth = 0.5;
      ctx.strokeStyle = 'rgba(20,20,20,0.55)';
      for (let e = 0; e < mesh.tris.length; e += 1) {
        const [a, b, c] = mesh.tris[e];
        const pa = pts[a]; const pb = pts[b]; const pc = pts[c];
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.lineTo(pc.x, pc.y);
        ctx.closePath();
        if (fill) {
          const za = depth[a]; const zb = depth[b]; const zc = depth[c];
          ctx.fillStyle = depthColor(za == null || zb == null || zc == null ? null : (za + zb + zc) / 3, zmax);
          ctx.globalAlpha = 0.75;
          ctx.fill();
          ctx.globalAlpha = 1;
        }
        if (strokes) ctx.stroke();
      }
    };
    draw();
    map.on('move zoom resize viewreset', draw);
    return () => {
      map.off('move zoom resize viewreset', draw);
      canvas.remove();
    };
  }, [map, mesh, fill]);
  return null;
}
