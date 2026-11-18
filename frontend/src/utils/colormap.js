/** Shared field colormap (blue → cyan → green → yellow → red), t in [0, 1] → [r, g, b]. */
const STOPS = [[0.13, 0.35, 0.85], [0.1, 0.75, 0.9], [0.3, 0.8, 0.3], [0.95, 0.85, 0.2], [0.9, 0.2, 0.15]];

export function colormap(t) {
  const x = Math.min(0.9999, Math.max(0, Number.isFinite(t) ? t : 0)) * 4;
  const i = Math.floor(x);
  const f = x - i;
  return STOPS[i].map((c, k) => c + f * (STOPS[i + 1][k] - c));
}

export const COLORBAR_CSS = 'linear-gradient(90deg, #2159d9, #1abfe6, #4dcc4d, #f2d933, #e63326)';
