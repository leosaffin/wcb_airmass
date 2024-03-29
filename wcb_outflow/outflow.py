"""Identification of the outflow of warm conveyor belts
"""
import numpy as np
from scipy.ndimage import filters
import matplotlib as mpl
import matplotlib.pyplot as plt

import iris
import iris.plot as iplt
from iris.analysis import cartography

from pylagranto import trajectory

from wcb_outflow.plot import background_map, projection


def outflow_th(
        case,
        theta_levels,
        lon_bounds=(0, 720),
        lat_bounds=(-90, 90),
        filtersize_t=30,
        filtersize_p=30,
        resolution=5,
        save=False,
):
    """Returns numpy array of indices on contour around WCB outflow

    Args:
        case (wcb_outflow.CaseStudy):
        theta_levels (list):
        lon_bounds (tuple): Minimum and maximum in longitude when trying to find the
            outflow contour
        lat_bounds (tuple): Minimum and maximum in latitude when trying to find the
            outflow contour
        filtersize_t (int): Filter size (number of gridpoints) to apply to dtheta before
            finding contours of dtheta=0
        filtersize_p (int): Filter size (number of gridpoints) to apply to PV before
            applying PV<2 criteria to outflow regions
        resolution (scalar): Spacing (km) between outflow boundary points. In places
            where the contour nodes are further apart than the resolution, more nodes
            will be added
        save (logical): Save the outflow boundaries to the data directory for the case
            study
    """
    location_constraint = iris.Constraint(
        longitude=lambda x: lon_bounds[0] < x < lon_bounds[1],
        latitude=lambda x: lat_bounds[0] < x < lat_bounds[1],
    )

    cubes = iris.load(
        case.filename_theta(case.outflow_time),
        iris.Constraint(time=case.outflow_time)
    )

    dtheta = cubes.extract_cube("total_minus_adv_only_theta")
    z = cubes.extract("altitude")[0]
    pv = cubes.extract_cube("ertel_potential_vorticity")
    crs = pv.coord(axis="x").coord_system.as_cartopy_crs()

    fig = plt.figure(figsize=(8, 20))
    fig.suptitle(case.name)
    V = np.linspace(-10, 40, 11)
    norm = mpl.colors.Normalize(-40, 40)

    new_contours = True
    for i, theta_level in enumerate(theta_levels):
        print(theta_level)
        # restrict to outflow time and selected theta level
        # the cutoff artificially truncates the domain s.t. only the region we want is
        # found (removes West: can't see new developing storms)
        level_cs = iris.Constraint(air_potential_temperature=theta_level)
        dtheta_subset = dtheta.extract(level_cs & location_constraint).copy()
        z_subset = z.extract(level_cs & location_constraint).copy()
        pv_subset = pv.extract(level_cs & location_constraint).copy()

        # apply median filter to smooth fields
        dtheta_subset.data = filters.median_filter(dtheta_subset.data, size=filtersize_t)
        pv_subset.data = filters.median_filter(pv_subset.data, size=filtersize_p)

        # Plot the original (unsmoothed) dtheta field with the identified outflow region
        # overlayed
        ax = plt.subplot(len(theta_levels) // 3 + 1, 3, i + 1, projection=projection)
        ax.set_title("{} K".format(theta_level))
        iplt.contourf(dtheta.extract(level_cs), V, cmap="seismic", norm=norm)
        background_map(ax, pv.extract(level_cs))

        # Contour the outflow region (dtheta=0 & PV<2) and extract the outflow boundary
        # and interior points
        try:
            boundary, points = get_points(dtheta_subset, pv_subset, z_subset, resolution)

            plt.plot(boundary[:, 0] - 360, boundary[:, 1], "-c", transform=crs)

            boundary3d = np.zeros([boundary.shape[0], 3])
            boundary3d[:, 0:2] = boundary
            boundary3d[:, 2] = theta_level

            points3d = np.zeros([points.shape[0], 4])
            points3d[:, 0:3] = points
            points3d[:, 3] = theta_level

            if new_contours:
                outflow_boundaries = boundary3d
                outflow_volume = points3d
                new_contours = False
            else:
                outflow_boundaries = np.concatenate((outflow_boundaries, boundary3d))
                outflow_volume = np.concatenate((outflow_volume, points3d))

        except ValueError:
            print("No closed contours found at this level")

    if save:
        np.save(str(case.data_path / "outflow_boundaries.npy"), outflow_boundaries)
        np.save(str(case.data_path / "outflow_volume.npy"), outflow_volume)
    else:
        plt.show()

    return


def at_inflow_time(case):
    tr = trajectory.load(case.data_path / "isentropic_trajectories_from_volume.pkl")

    cube = iris.load_cube(
        case.filename_theta(case.start_time),
        iris.Constraint(name="ertel_potential_vorticity", time=case.start_time)
    )

    for theta in case.outflow_theta:
        tr_theta = tr.select("air_potential_temperature", "==", theta)
        closed_loop = contour_around_points(tr_theta.x[:, -1], tr_theta.y[:, -1], cube[0])

        np.save(str(case.data_path / "outflow_boundaries_at_inflow_time_{}K.npy".format(theta)), closed_loop)

    plt.show()

    return


def get_points(dtheta, pv, z, resolution):
    # Extract the contour surrounding the outflow region
    criteria = np.logical_and(pv.data < 2, dtheta.data > 0)
    criteria = pv.copy(data=criteria.astype(int))
    cs = iplt.contour(criteria, [0.5], colors="g")
    contours = cs.allsegs[0]
    closed_loop = get_longest_closed_contour(contours)
    increase_circuit_resolution(closed_loop, resolution)

    # Create an array containing all the grid points within the outflow region
    path = mpl.path.Path(closed_loop)
    lon, lat = cartography.get_xy_grids(dtheta)
    points = np.transpose(np.array([lon.flatten(), lat.flatten()]))
    idx = np.where(path.contains_points(points))[0]
    points3d = np.transpose(np.array([lon.flatten(), lat.flatten(), z.data.flatten()]))

    return closed_loop, points3d[idx, :]


def get_longest_closed_contour(contours, threshold=100):
    """Find the tropopause contour that wraps around the globe

    Args:
        contours (list):
            A list of contours. Each individual contour is an array of
            coordinates for each point along the contour of shape (N, 2).

    """
    # Array of lengths (in km) of the contour boundaries
    lengths = np.array([contour_length(x) for x in contours])

    # Set the length of any non-closed contours to zero
    closed = np.array([is_closed_contour(x, threshold) for x in contours])
    lengths *= closed.astype(int)

    # Extract the longest closed contour
    imax = lengths.argmax()
    long_contour = contours[imax]

    if lengths[imax] == 0:
        raise ValueError("No closed contours found")

    return long_contour


def contour_length(points):
    """Contour length in kilometres

    Args:
        points: Nx2 array of longitude and latitude points around a contour (degrees)

    Returns:
        float: The total length of the contour in kilometres
    """
    conlen = haversine(points[-1], points[0])
    for n in range(len(points) - 1):
        conlen += haversine(points[n], points[n+1])

    return conlen


def is_closed_contour(contour_section, threshold=100):
    """Checks that a contour is closed

    Checks that the final point along a contour is sufficiently close to the
    initial point on a countour to determine if it is closed

    Args:
        contour_section (np.Array):
            An array of coordinates for each point along the contour of shape
            (N, 2).

    Returns:
        True: If contour is closed

        False: If contour is open
    """
    return haversine(contour_section[0], contour_section[-1]) < threshold


def increase_circuit_resolution(points, resolution):
    """Add points around the circuit loop
    """
    # Loop over all points around the circuit.
    n = 0
    while n < len(points):
        # Allow the loop to connect the final point with the first point
        # i.e np1 = 0
        np1 = (n+1) % len(points)

        # Calculate distances from current point to next point and
        # Insert a point if the next point is further away than the required
        # resolution
        distance = haversine(points[n], points[np1])
        if distance > resolution:
            # Put the next point along the same line
            dlon = points[np1, 0] - points[n, 0]
            dlat = points[np1, 1] - points[n, 1]

            new_lon = points[n, 0] + (resolution / distance) * dlon
            new_lat = points[n, 1] + (resolution / distance) * dlat

            points = np.insert(points, np1, [new_lon, new_lat], axis=0)

        # Always jump to the next point. This will either be the inserted point
        # or the next point along that is within the required resolution
        n += 1

    return points


def haversine(x1, x2):
    """ Calculate the great circle distance between two points on the earth
    (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(np.deg2rad, [x1[0], x1[1], x2[0], x2[1]])

    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    r = 6371  # Radius of earth in kilometers
    return c * r


def contour_around_points(xpoints, ypoints, example_cube, filter_size=30, **kwargs):
    """Create a contour that encloses the given set of points
    """
    x, y = example_cube.coord(axis="x").points, example_cube.coord(axis="y").points
    bins = (_bin_edges(x), _bin_edges(y))

    # Produce a contour around all the points in the inflow
    # Use the same median filter as for the outflows
    histogram, xed, yed = np.histogram2d(xpoints, ypoints, bins=bins)
    histogram = filters.median_filter(histogram.transpose(), size=filter_size)
    histogram = example_cube.copy(data=histogram)
    cs = iplt.contour(histogram, [0.5], **kwargs)

    return get_longest_closed_contour(cs.allsegs[0])


def _bin_edges(x):
    xed = np.zeros(len(x) + 1)
    dx = np.diff(x).mean()
    xed[:-1] = x - dx
    xed[-1] = x[-1] + dx

    return xed
