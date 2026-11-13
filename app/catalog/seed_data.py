"""Initial Hub catalog. Upserted by slug with ``flask catalog seed``.

Notes
-----
* Integration levels: ``integrated`` runs inside the Hub, ``connectable`` needs the
  user's own licence through an adapter, ``reference`` is an informational card.
* ``availability`` is honest about today: CalculiX/Elmer/Code_Aster cannot run yet.
  Per PLAN_CAE_NUEVA_GENERACION.md the own FEM kernel comes first; CalculiX is planned
  only as a verification benchmark, the others have no date.
* OpenFOAM and SU2 are finite-volume CFD codes, not FEM → method ``fvm``, analysis ``cfd``.
* Names only, own icons — no vendor logos (trademarks).
"""

VOCABULARY = {
    'analysis': ['static', 'modal', 'buckling', 'thermal', 'transient', 'nonlinear', 'contact',
                 'cfd', 'electromagnetics', 'multiphysics', 'optimization', 'meshing', 'postprocessing'],
    'method': ['fem', 'fvm', 'meshing', 'statistics'],
    'deployment': ['desktop', 'hpc', 'cloud', 'ai'],
}

CATALOG = [
    # ── Integrated (run inside the Hub) ────────────────────────────────────
    {
        'slug': 'cae-lab-fem', 'name': 'CAE Lab FEM (núcleo nativo)', 'category': 'open_source',
        'icon': 'functions', 'license': 'Propio', 'url': None,
        'description': 'Solver FEM propio en Python: tetraedros lineales (T4), estático lineal, '
                       'Newton-Raphson para no linealidad de material y refinamiento adaptativo '
                       'con estimador de Zienkiewicz-Zhu. Ideal para estudios rápidos (Tier 0-1).',
        'integration_level': 'integrated', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['static', 'nonlinear'], 'method': ['fem'], 'elements': ['T4'],
                         'deployment': ['desktop'], 'formats': {'out': ['hdf5']}},
        'launch': {'mode': 'design'}, 'sort_order': 10,
    },
    {
        'slug': 'gmsh', 'name': 'Gmsh', 'category': 'open_source', 'icon': 'grid',
        'license': 'GPL-2.0+', 'url': 'https://gmsh.info',
        'description': 'Mallador 3D con núcleo OpenCASCADE. Genera mallas tetraédricas, hexaédricas e '
                       'híbridas a partir de STEP y crea Physical Groups por cara para las condiciones '
                       'de frontera.',
        'integration_level': 'integrated', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['meshing'], 'method': ['meshing'], 'elements': ['tet4', 'tet10', 'hex8'],
                         'deployment': ['desktop', 'hpc'],
                         'formats': {'in': ['step', 'brep', 'iges'], 'out': ['msh', 'inp', 'vtk', 'unv']}},
        'launch': {'mode': 'cae', 'action': 'mesh_from_step'}, 'sort_order': 20,
    },
    {
        'slug': 'calculix', 'name': 'CalculiX', 'category': 'open_source', 'icon': 'calculate',
        'license': 'GPL-2.0', 'url': 'http://www.calculix.de',
        'description': 'Solver FEM estructural y térmico con entrada compatible con Abaqus (.inp). '
                       'Previsto como referencia para verificar el kernel FEM propio en los benchmarks '
                       '(Gmsh → .inp → ccx → .frd → VTU).',
        'integration_level': 'integrated', 'availability': 'planned', 'availability_note': 'Benchmark de verificación',
        'capabilities': {'analysis': ['static', 'modal', 'buckling', 'thermal', 'transient', 'nonlinear', 'contact'],
                         'method': ['fem'], 'elements': ['C3D4', 'C3D10', 'C3D8', 'C3D20', 'S8', 'B32'],
                         'deployment': ['desktop', 'hpc'], 'formats': {'in': ['inp'], 'out': ['frd', 'dat']}},
        'launch': {'mode': 'design'}, 'sort_order': 30,
    },
    {
        'slug': 'code-aster', 'name': 'Code_Aster', 'category': 'open_source', 'icon': 'architecture',
        'license': 'GPL-3.0', 'url': 'https://code-aster.org',
        'description': 'Solver FEM de EDF para mecánica estructural, térmica y termomecánica, con amplia '
                       'biblioteca de no linealidades y contacto.',
        'integration_level': 'integrated', 'availability': 'planned', 'availability_note': 'Sin fecha',
        'capabilities': {'analysis': ['static', 'modal', 'buckling', 'thermal', 'transient', 'nonlinear',
                                      'contact', 'multiphysics'],
                         'method': ['fem'], 'deployment': ['desktop', 'hpc'],
                         'formats': {'in': ['comm', 'med'], 'out': ['med', 'rmed']}},
        'launch': {'mode': 'design'}, 'sort_order': 40,
    },
    {
        'slug': 'elmer', 'name': 'Elmer FEM', 'category': 'open_source', 'icon': 'hub',
        'license': 'GPL-2.0 / LGPL-2.1', 'url': 'https://www.elmerfem.org',
        'description': 'Solver FEM multifísico (CSC, Finlandia): estructural, térmico, electromagnetismo '
                       'y flujo, con acoplamientos entre físicas.',
        'integration_level': 'integrated', 'availability': 'planned', 'availability_note': 'Sin fecha',
        'capabilities': {'analysis': ['static', 'modal', 'thermal', 'transient', 'cfd', 'electromagnetics',
                                      'multiphysics'],
                         'method': ['fem'], 'deployment': ['desktop', 'hpc'],
                         'formats': {'in': ['sif', 'mesh'], 'out': ['vtu']}},
        'launch': {'mode': 'design'}, 'sort_order': 50,
    },
    {
        'slug': 'cae-assistant', 'name': 'Asistente CAE', 'category': 'specialized', 'icon': 'psychology',
        'license': 'Propio', 'url': None,
        'description': 'Hoy: detección estadística de zonas críticas en campos de resultados (umbral sobre '
                       'el máximo, clasificación de riesgo). Previsto: validación asistida de la configuración '
                       'antes de lanzar e interpretación de resultados.',
        'integration_level': 'integrated', 'availability': 'partial', 'availability_note': 'En desarrollo',
        'capabilities': {'analysis': ['postprocessing'], 'method': ['statistics'], 'deployment': ['ai']},
        'launch': {'mode': 'cae'}, 'sort_order': 60,
    },

    # ── Connectable (user's licence via adapter) ───────────────────────────
    {
        'slug': 'ansys-mechanical', 'name': 'Ansys Mechanical / MAPDL', 'category': 'commercial',
        'icon': 'precision', 'license': 'Comercial', 'url': 'https://www.ansys.com',
        'description': 'Suite FEM comercial. Conexión prevista mediante PyAnsys (PyMAPDL) con la licencia '
                       'del usuario.',
        'integration_level': 'connectable', 'availability': 'planned', 'availability_note': 'Adaptador futuro',
        'capabilities': {'analysis': ['static', 'modal', 'buckling', 'thermal', 'transient', 'nonlinear',
                                      'contact', 'multiphysics'],
                         'method': ['fem'], 'deployment': ['desktop', 'hpc', 'cloud']},
        'connection': {'adapter': 'PyMAPDL', 'python_package': 'ansys-mapdl-core',
                       'docs': 'https://mapdl.docs.pyansys.com',
                       'requires': ['Instalación local de Ansys', 'Licencia válida (servidor de licencias)']},
        'sort_order': 100,
    },
    {
        'slug': 'comsol', 'name': 'COMSOL Multiphysics', 'category': 'commercial', 'icon': 'bubble',
        'license': 'Comercial', 'url': 'https://www.comsol.com',
        'description': 'Plataforma FEM multifísica. Conexión prevista mediante la librería Python «mph» '
                       'sobre un servidor COMSOL con la licencia del usuario.',
        'integration_level': 'connectable', 'availability': 'planned', 'availability_note': 'Adaptador futuro',
        'capabilities': {'analysis': ['static', 'modal', 'thermal', 'transient', 'cfd', 'electromagnetics',
                                      'multiphysics', 'optimization'],
                         'method': ['fem'], 'deployment': ['desktop', 'hpc']},
        'connection': {'adapter': 'mph', 'python_package': 'mph', 'docs': 'https://mph.readthedocs.io',
                       'requires': ['COMSOL instalado con LiveLink/servidor', 'Licencia válida']},
        'sort_order': 110,
    },
    {
        'slug': 'abaqus', 'name': 'Abaqus', 'category': 'commercial', 'icon': 'layers',
        'license': 'Comercial', 'url': 'https://www.3ds.com/products/simulia/abaqus',
        'description': 'Solver FEM (implícito y explícito) de SIMULIA. Conexión prevista generando .inp y '
                       'ejecutando scripts Python de Abaqus con la licencia del usuario.',
        'integration_level': 'connectable', 'availability': 'planned', 'availability_note': 'Adaptador futuro',
        'capabilities': {'analysis': ['static', 'modal', 'buckling', 'thermal', 'transient', 'nonlinear', 'contact'],
                         'method': ['fem'], 'deployment': ['desktop', 'hpc'],
                         'formats': {'in': ['inp'], 'out': ['odb']}},
        'connection': {'adapter': 'Abaqus Python scripting', 'python_package': None,
                       'requires': ['Abaqus instalado', 'Licencia válida', 'Ejecución por línea de comandos (abaqus job=...)']},
        'sort_order': 120,
    },

    # ── Reference (informational cards) ────────────────────────────────────
    {
        'slug': 'openfoam', 'name': 'OpenFOAM', 'category': 'open_source', 'icon': 'air',
        'license': 'GPL-3.0', 'url': 'https://openfoam.org',
        'description': 'Toolbox CFD de volúmenes finitos (no FEM): flujo incompresible/compresible, '
                       'turbulencia, transferencia de calor y multifase.',
        'integration_level': 'reference', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['cfd', 'thermal', 'transient', 'multiphysics'], 'method': ['fvm'],
                         'deployment': ['desktop', 'hpc', 'cloud']},
        'sort_order': 200,
    },
    {
        'slug': 'su2', 'name': 'SU2', 'category': 'open_source', 'icon': 'flight',
        'license': 'LGPL-2.1', 'url': 'https://su2code.github.io',
        'description': 'Suite CFD de volúmenes finitos con optimización de forma basada en el adjunto.',
        'integration_level': 'reference', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['cfd', 'optimization'], 'method': ['fvm'], 'deployment': ['desktop', 'hpc']},
        'sort_order': 210,
    },
    {
        'slug': 'ls-dyna', 'name': 'LS-DYNA', 'category': 'specialized', 'icon': 'bolt',
        'license': 'Comercial', 'url': 'https://www.ansys.com/products/structures/ansys-ls-dyna',
        'description': 'Solver explícito para impacto, choque y grandes deformaciones. El modo CAE del Hub '
                       'ya importa modelos .k/.key (incluidos ensambles con *INCLUDE).',
        'integration_level': 'reference', 'availability': 'available', 'availability_note': 'Importación de modelos',
        'capabilities': {'analysis': ['transient', 'nonlinear', 'contact'], 'method': ['fem'],
                         'deployment': ['desktop', 'hpc'], 'formats': {'in': ['k', 'key']}},
        'sort_order': 220,
    },
    {
        'slug': 'simscale', 'name': 'SimScale', 'category': 'cloud', 'icon': 'cloud',
        'license': 'SaaS', 'url': 'https://www.simscale.com',
        'description': 'Plataforma de simulación en el navegador: FEA, CFD y térmico en la nube.',
        'integration_level': 'reference', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['static', 'modal', 'thermal', 'cfd', 'nonlinear'],
                         'method': ['fem', 'fvm'], 'deployment': ['cloud']},
        'sort_order': 300,
    },
    {
        'slug': 'onshape-simulation', 'name': 'Onshape Simulation', 'category': 'cloud', 'icon': 'web',
        'license': 'SaaS', 'url': 'https://www.onshape.com',
        'description': 'CAD en la nube con simulación integrada (estática lineal y modal) dentro del diseño.',
        'integration_level': 'reference', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['static', 'modal'], 'method': ['fem'], 'deployment': ['cloud']},
        'sort_order': 310,
    },
    {
        'slug': 'autodesk-fusion', 'name': 'Autodesk Fusion (Simulation)', 'category': 'cloud', 'icon': 'design',
        'license': 'Comercial / SaaS', 'url': 'https://www.autodesk.com/products/fusion-360',
        'description': 'CAD/CAM/CAE con estudios de simulación resueltos en la nube y diseño generativo.',
        'integration_level': 'reference', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['static', 'modal', 'thermal', 'nonlinear', 'optimization'],
                         'method': ['fem'], 'deployment': ['desktop', 'cloud']},
        'sort_order': 320,
    },
    {
        'slug': 'altair-one', 'name': 'Altair One', 'category': 'cloud', 'icon': 'cloud_queue',
        'license': 'Comercial / SaaS', 'url': 'https://altair.com/altair-one',
        'description': 'Plataforma en la nube para las herramientas de simulación y optimización de Altair '
                       '(p. ej. OptiStruct) con cómputo HPC bajo demanda.',
        'integration_level': 'reference', 'availability': 'available', 'availability_note': None,
        'capabilities': {'analysis': ['static', 'modal', 'nonlinear', 'optimization', 'cfd', 'multiphysics'],
                         'method': ['fem', 'fvm'], 'deployment': ['cloud', 'hpc']},
        'sort_order': 330,
    },
]


def seed_catalog(db, prune: bool = False) -> dict:
    """Idempotent upsert by slug. ``prune`` disables rows whose slug is no longer in CATALOG."""
    from app.catalog.models import SolverCatalog

    existing = {r.slug: r for r in SolverCatalog.query.all()}
    created = updated = disabled = 0
    for entry in CATALOG:
        row = existing.get(entry['slug'])
        if row is None:
            row = SolverCatalog(slug=entry['slug'])
            db.session.add(row)
            created += 1
        else:
            updated += 1
        for k in ('name', 'category', 'description', 'icon', 'license', 'url', 'integration_level',
                  'availability', 'availability_note', 'capabilities', 'launch', 'connection', 'sort_order'):
            setattr(row, k, entry.get(k))
        row.enabled = True
    if prune:
        slugs = {e['slug'] for e in CATALOG}
        for slug, row in existing.items():
            if slug not in slugs and row.enabled:
                row.enabled = False
                disabled += 1
    db.session.commit()
    return {'created': created, 'updated': updated, 'disabled': disabled}
