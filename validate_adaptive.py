"""FASE 3 Adaptive Meshing Validation — Zienkiewicz-Zhu refinement test."""
import sys, os
sys.path.insert(0, r'C:\cae-viewer')
os.environ['FLASK_ENV'] = 'development'

from app import create_app
app = create_app('development')

with app.app_context():
    from app.design.services.fem.kernel import FEMKernel
    
    kernel = FEMKernel()
    
    # Cantilever: 50x10x10 mm, E=210 GPa, ν=0.3, F_y = 1000 N
    L, W, H = 0.050, 0.010, 0.010
    E, nu = 210e9, 0.3
    Fy = 1000.0
    
    # Initial coarse mesh: n_div=5 (~46 nodes)
    spec = {
        'physics': ['structural'],
        'mesh_source': 'cantilever',
        'mesh_params': {'length': L, 'width': W, 'height': H, 'n_along_length': 5},
        'material': {'type': 'linear_elastic_isotropic', 'E': E, 'nu': nu, 'rho': 7800.0},
        'bcs':  [{'node_set': 'fixed', 'dofs': [0,1,2], 'values': [0,0,0]}],
        'loads': [{'node_set': 'tip',   'force': [0, -Fy, 0]}],
    }
    
    # Analytical reference (Euler-Bernoulli)
    analytical = FEMKernel.cantilever_analytical(E, nu, L, W, H, Fy)
    ana_deflection_mm = analytical['tip_deflection_mm']
    
    print("\n" + "="*80)
    print("FASE 3: ADAPTIVE MESH REFINEMENT TEST")
    print("="*80)
    print(f"\nCantilever beam: {L*1000:.1f} × {W*1000:.1f} × {H*1000:.1f} mm")
    print(f"Material: E={E/1e9:.0f} GPa, ν={nu}, ρ=7800 kg/m³")
    print(f"Load: F_y = {Fy} N (at tip)")
    print(f"Analytical tip deflection (EB): {ana_deflection_mm:.6f} mm")
    print(f"\n{'Cycle':>6} | {'Nodes':>7} | {'Elements':>9} | {'Error %':>8} | {'Displ [mm]':>11} | σ_vm [MPa]")
    print("-" * 80)
    
    # Run adaptive with max 5 cycles, target 5% error
    result = kernel.solve_adaptive_sync(
        solver_spec=spec,
        max_cycles=5,
        target_error=0.05,        # 5%
        refinement_fraction=0.2    # Refine top 20% by error
    )
    
    adaptive_log = result.get('adaptive_log', [])
    
    for entry in adaptive_log:
        cycle = entry['cycle']
        n_nodes = entry['n_nodes']
        n_elems = entry['n_elements']
        global_error = entry['global_error']
        error_pct = global_error * 100.0
        disp_mm = entry['max_displacement_mm']
        vm_mpa = entry['max_von_mises_mpa']
        
        # Compare to analytical
        relative_err = abs(disp_mm - ana_deflection_mm) / ana_deflection_mm * 100.0
        
        status = "✓ PASS" if error_pct < 5.0 else ""
        print(f"  {cycle:>4} | {n_nodes:>7,d} | {n_elems:>9,d} | {error_pct:>7.2f}% | {disp_mm:>11.6f} | {vm_mpa:>10.2f}  {status}")
    
    print("-" * 80)
    print(f"\nSummary:")
    print(f"  Initial mesh: {adaptive_log[0]['n_nodes']} nodes → Final: {adaptive_log[-1]['n_nodes']} nodes")
    print(f"  Error reduction: {adaptive_log[0]['global_error']*100:.2f}% → {adaptive_log[-1]['global_error']*100:.2f}%")
    print(f"  Total cycles: {len(adaptive_log)}")
    
    s = result['summary']
    print(f"\nFinal Result:")
    print(f"  Tip deflection: {s['max_displacement_mm']:.6f} mm")
    print(f"  Analytical:     {ana_deflection_mm:.6f} mm")
    print(f"  Relative error: {abs(s['max_displacement_mm'] - ana_deflection_mm) / ana_deflection_mm * 100:.3f}%")
    print(f"  Max von Mises:  {s['max_von_mises_mpa']:.2f} MPa")
    print(f"  Wall time:      {s['wall_time_s']:.2f} s")
    
    if adaptive_log[-1]['global_error'] < 0.05:
        print(f"\n✓ HITO FASE 3 ALCANZADO: Error < 5% después de {len(adaptive_log)} ciclos")
    else:
        print(f"\n⚠ Error final {adaptive_log[-1]['global_error']*100:.2f}% > 5% (aumentar cycles)")
    
    print("\n" + "="*80)
