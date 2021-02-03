"""Functions to calculate quantities from the circuit integrals
"""

import numpy as np

import iris


def diff(cube_theta, idx_0=None):
    if idx_0 is None:
        # define earliest non-zero value
        if not np.isnan(cube_theta.data).all():
            cube_initial = cube_theta[~np.isnan(cube_theta.data)][0]
        else:
            cube_initial = cube_theta[0]
    else:
        cube_initial = cube_theta[idx_0]

    # Fractional change from start to end, relative to current value
    # diff = ((cube_theta - cube_initial) / cube_theta)

    # Fractional change from start to end, relative to initial value
    return (cube_theta - cube_initial) / cube_initial


def timediff(cube, case_study):
    """Extract time and outflow time as lead time in hours
    """
    dt = cube.coord("time")
    dt.convert_units("Hours Since {}".format(
        case_study.start_time.strftime("%Y-%m-%d %H:%M:%S")
    ))

    out_time = case_study.outflow_lead_time.total_seconds() // 3600

    return dt.points, out_time


def get_cube_by_name(cubes, name):
    if name == "density":
        cube = density(cubes)
    elif "vorticity" in name:
        cube = vorticity(cubes, name[:-9])
    elif "PV" in name:
        cube = potential_vorticity(cubes, name[:-2])
    elif name=="mass area anomaly ratio":
        cube = ratio(cubes)
    else:
        cube = cubes.extract_strict(name)

    return cube


def density(cubes):
    mass = cubes.extract_strict("mass")
    area = cubes.extract_strict("area")

    return mass / area


def vorticity(cubes, circulation_name=""):
    area = cubes.extract_strict("area")
    circulation = cubes.extract_strict(circulation_name + "circulation")

    area, circulation = equate_times(area.copy(), circulation.copy())

    return circulation / area


def potential_vorticity(cubes, circulation_name=""):
    mass = cubes.extract_strict("mass")
    circulation = cubes.extract_strict(circulation_name + "circulation")
    mass, circulation = equate_times(mass.copy(), circulation.copy())

    return circulation / mass


def ratio(cubes):
    mass = cubes.extract_strict("mass")
    area = cubes.extract_strict("area")

    alpha = diff(mass)
    epsilon = diff(area)

    return alpha / epsilon


def equate_times(cube, reference_cube):
    ref_dates = [cell.point for cell in reference_cube.coord('time').cells()]
    ref_cst = iris.Constraint(time=lambda cell: cell in ref_dates)
    cube = cube.extract(ref_cst)
    cube_dates = [cell.point for cell in cube.coord('time').cells()]
    eqtim_cst = iris.Constraint(time=lambda cell: cell in cube_dates)
    reference_cube = reference_cube.extract(eqtim_cst)

    new_cube = reference_cube.copy()

    new_cube.rename(cube.name())
    new_cube.units = cube.units
    new_cube.data = cube.data

    return new_cube, reference_cube