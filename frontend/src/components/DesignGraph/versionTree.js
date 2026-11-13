/**
 * Group the flat graph list into projects (version trees, FASE 9): each project = the root and
 * every graph that descends from it through parent_id. Versions sorted by number; projects by
 * their most recent activity. A parent missing from the list (deleted) makes the child a root.
 */
export function groupVersions(graphs) {
  const byId = new Map((graphs || []).map((g) => [g.id, g]));
  const rootOf = (g) => {
    let r = g;
    const seen = new Set();
    while (r.parent_id && byId.has(r.parent_id) && !seen.has(r.id)) {
      seen.add(r.id);
      r = byId.get(r.parent_id);
    }
    return r;
  };
  const groups = new Map();
  (graphs || []).forEach((g) => {
    const root = rootOf(g);
    if (!groups.has(root.id)) groups.set(root.id, { root, versions: [] });
    groups.get(root.id).versions.push(g);
  });
  const stamp = (g) => g.updated_at || g.created_at || '';
  return [...groups.values()]
    .map((grp) => {
      const versions = grp.versions.sort((a, b) => a.version - b.version || stamp(a).localeCompare(stamp(b)));
      return { ...grp, versions, latest: versions[versions.length - 1],
        activity: versions.map(stamp).sort().pop() || '' };
    })
    .sort((a, b) => b.activity.localeCompare(a.activity));
}
