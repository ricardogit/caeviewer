import meshio
import numpy as np

points = np.array([
    [0,0,0],[1,0,0],[1,1,0],[0,1,0],
    [0,0,1],[1,0,1],[1,1,1],[0,1,1],
], dtype=float)

cells = [("tetra", np.array([
    [0,1,2,4],
    [1,2,5,4],
    [2,3,6,5],
    [3,7,6,5],
    [2,6,5,4],
    [2,3,7,6],
]))]

point_data = {
    "von_mises": np.linalg.norm(points - [0.5,0.5,0.5], axis=1)
}

mesh = meshio.Mesh(points=points, cells=cells, point_data=point_data)
meshio.write("test_cube.vtu", mesh)

print("test_cube.vtu generado")