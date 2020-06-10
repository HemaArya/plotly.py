from ._core import make_figure, build_dataframe
from ._doc import make_docstring, docs
from ._chart_types import choropleth_mapbox
import plotly.graph_objs as go
import numpy as np
import pandas as pd
import re


def _project_latlon_to_wgs84(lat, lon):
    """
    Projects lat and lon to WGS84 to get regular hexagons on a mapbox map
    """
    x = lon * np.pi / 180
    y = np.arctanh(np.sin(lat * np.pi/180))
    return x, y

def _project_wgs84_to_latlon(x, y):
    """
    Projects lat and lon to WGS84 to get regular hexagons on a mapbox map
    """
    lon = x * 180 / np.pi
    lat = (2 * np.arctan(np.exp(y)) - np.pi / 2) * 180 / np.pi
    return lat, lon

def _human_format(number):
    """
    Transforms high numbers to human readable numer string
    """
    units = ["", "K", "M", "G", "T", "P"]
    k = 1000.0
    magnitude = int(np.floor(np.log(number, k)))
    return "%.2f%s" % (number / k ** magnitude, units[magnitude])

def _getBoundsZoomLevel(lon_min, lon_max, lat_min, lat_max, mapDim):
    """
    Get the mapbox zoom level given bounds and a figure dimension
    Source: https://stackoverflow.com/questions/6048975/google-maps-v3-how-to-calculate-the-zoom-level-for-a-given-bounds
    """

    scale = 2 # adjustment to reflect MapBox base tiles are 512x512 vs. Google's 256x256
    WORLD_DIM = {'height': 256 * scale, 'width': 256 * scale}
    ZOOM_MAX = 18

    def latRad(lat):
        sin = np.sin(lat * np.pi / 180)
        radX2 = np.log((1 + sin) / (1 - sin)) / 2
        return max(min(radX2, np.pi), -np.pi) / 2

    def zoom(mapPx, worldPx, fraction):
        return 0.95 * np.log(mapPx / worldPx / fraction) / np.log(2)

    latFraction = (latRad(lat_max) - latRad(lat_min)) / np.pi

    lngDiff = lon_max - lon_min
    lngFraction = ((lngDiff + 360) if lngDiff < 0 else lngDiff) / 360

    latZoom = zoom(mapDim['height'], WORLD_DIM['height'], latFraction)
    lngZoom = zoom(mapDim['width'], WORLD_DIM['width'], lngFraction)

    return min(latZoom, lngZoom, ZOOM_MAX)

def _compute_hexbin(
    lat=None,
    lon=None,
    lat_range=None,
    lon_range=None,
    color=None,
    nx=None,
    agg_func=None,
    min_count=None
):
    """
    Computes the aggregation at hexagonal bin level.
    Also defines the coordinates of the hexagons for plotting.
    The binning is inspired by matplotlib's implementation.

    Parameters
    ----------
    lat : np.ndarray
        Array of latitudes
    lon : np.ndarray
        Array of longitudes
    lat_range : np.ndarray
        Min and max latitudes
    lon_range : np.ndarray
        Min and max longitudes
    color : np.ndarray
        Metric to aggregate at hexagon level
    nx : int
        Number of hexagons horizontally
    agg_func : function
        Numpy compatible aggregator, this function must take a one-dimensional
        np.ndarray as input and output a scalar
    min_count : float
        Minimum value for which to display the aggregate

    Returns
    -------

    """
    # Project to WGS 84
    x, y = _project_latlon_to_wgs84(lat, lon)

    if lat_range is None:
        lat_range = np.array([lat.min(), lat.max()])
    if lon_range is None:
        lon_range = np.array([lon.min(), lon.max()])

    x_range, y_range = _project_latlon_to_wgs84(lat_range, lon_range)

    xmin = x_range.min()
    xmax = x_range.max()
    ymin = y_range.min()
    ymax = y_range.max()

    Dx = xmax - xmin
    Dy = ymax - ymin
    dx = Dx / nx
    dy = dx * np.sqrt(3)
    ny = np.round(Dy / dy).astype(int)

    x = (x - xmin) / dx
    y = (y - ymin) / dy
    ix1 = np.round(x).astype(int)
    iy1 = np.round(y).astype(int)
    ix2 = np.floor(x).astype(int)
    iy2 = np.floor(y).astype(int)

    nx1 = nx + 1
    ny1 = ny + 1
    nx2 = nx
    ny2 = ny
    n = nx1 * ny1 + nx2 * ny2

    d1 = (x - ix1) ** 2 + 3.0 * (y - iy1) ** 2
    d2 = (x - ix2 - 0.5) ** 2 + 3.0 * (y - iy2 - 0.5) ** 2
    bdist = (d1 < d2)

    if color is None:
        lattice1 = np.zeros((nx1, ny1))
        lattice2 = np.zeros((nx2, ny2))
        c1 = (0 <= ix1) & (ix1 < nx1) & (0 <= iy1) & (iy1 < ny1) & bdist
        c2 = (0 <= ix2) & (ix2 < nx2) & (0 <= iy2) & (iy2 < ny2) & ~bdist
        np.add.at(lattice1, (ix1[c1], iy1[c1]), 1)
        np.add.at(lattice2, (ix2[c2], iy2[c2]), 1)
        if min_count is not None:
            lattice1[lattice1 < min_count] = np.nan
            lattice2[lattice2 < min_count] = np.nan
        accum = np.concatenate([lattice1.ravel(), lattice2.ravel()])
        good_idxs = ~np.isnan(accum)
    else:
        if min_count is None:
            min_count = 0

        # create accumulation arrays
        lattice1 = np.empty((nx1, ny1), dtype=object)
        for i in range(nx1):
            for j in range(ny1):
                lattice1[i, j] = []
        lattice2 = np.empty((nx2, ny2), dtype=object)
        for i in range(nx2):
            for j in range(ny2):
                lattice2[i, j] = []

        for i in range(len(x)):
            if bdist[i]:
                if 0 <= ix1[i] < nx1 and 0 <= iy1[i] < ny1:
                    lattice1[ix1[i], iy1[i]].append(color[i])
            else:
                if 0 <= ix2[i] < nx2 and 0 <= iy2[i] < ny2:
                    lattice2[ix2[i], iy2[i]].append(color[i])

        for i in range(nx1):
            for j in range(ny1):
                vals = lattice1[i, j]
                if len(vals) > min_count:
                    lattice1[i, j] = agg_func(vals)
                else:
                    lattice1[i, j] = np.nan
        for i in range(nx2):
            for j in range(ny2):
                vals = lattice2[i, j]
                if len(vals) > min_count:
                    lattice2[i, j] = agg_func(vals)
                else:
                    lattice2[i, j] = np.nan

        accum = np.hstack((lattice1.astype(float).ravel(),
                        lattice2.astype(float).ravel()))
        good_idxs = ~np.isnan(accum)
        
    agreggated_value = accum[good_idxs]

    centers = np.zeros((n, 2), float)
    centers[:nx1 * ny1, 0] = np.repeat(np.arange(nx1), ny1)
    centers[:nx1 * ny1, 1] = np.tile(np.arange(ny1), nx1)
    centers[nx1 * ny1:, 0] = np.repeat(np.arange(nx2) + 0.5, ny2)
    centers[nx1 * ny1:, 1] = np.tile(np.arange(ny2), nx2) + 0.5
    centers[:, 0] *= dx
    centers[:, 1] *= dy
    centers[:, 0] += xmin
    centers[:, 1] += ymin
    centers = centers[good_idxs]

    # Define normalised regular hexagon coordinates
    hx = [0, .5, .5, 0, -.5, -.5]
    hy = [
        -0.5 / np.cos(np.pi / 6),
        -0.5 * np.tan(np.pi / 6),
        0.5 * np.tan(np.pi / 6),
        0.5 / np.cos(np.pi / 6),
        0.5 * np.tan(np.pi / 6),
        -0.5 * np.tan(np.pi / 6)
    ]

    # Number of hexagons needed
    m = len(centers)

    # Scale of hexagons
    dxh = sorted(list(set(np.diff(sorted(centers[:, 0])))))[1]
    dyh = sorted(list(set(np.diff(sorted(centers[:, 1])))))[1]
    nx = dxh * 2
    ny = 2/3 * dyh / (0.5 / np.cos(np.pi / 6))

    # Coordinates for all hexagonal patches
    hxs = np.array([hx] * m) * nx + np.vstack(centers[:, 0])
    hys = np.array([hy] * m) * ny + np.vstack(centers[:, 1])

    # Convert back to lat-lon
    hexagons_lats, hexagons_lons = _project_wgs84_to_latlon(hxs, hys)

    # Create unique feature id based on hexagon center
    centers = centers.astype(str)
    hexagons_ids = pd.Series(centers[:, 0]) + "," + pd.Series(centers[:, 1])

    return hexagons_lats, hexagons_lons, hexagons_ids, agreggated_value

def _hexagons_to_geojson(hexagons_lats, hexagons_lons, ids=None):
    """
    Creates a geojson of hexagonal features based on the outputs of
    _compute_hexbin
    """
    features = []
    if ids is None:
        ids = np.arange(len(hexagons_lats))
    for lat, lon, idx in zip(hexagons_lats, hexagons_lons, ids):
        points = np.array([lon, lat]).T.tolist()
        points.append(points[0])
        features.append(
            dict(
                type='Feature',
                id=idx,
                geometry=dict(type='Polygon', coordinates=[points])
            )
        )
    return dict(type='FeatureCollection', features=features)

def hexbin_mapbox(
    data_frame=None,
    lat=None,
    lon=None,
    color=None,
    gridsize=5,
    agg_func=None,
    animation_frame=None,
    color_discrete_sequence=None,
    color_discrete_map={},
    labels={},
    color_continuous_scale=None,
    range_color=None,
    color_continuous_midpoint=None,
    opacity=None,
    zoom=None,
    center=None,
    mapbox_style=None,
    title=None,
    template=None,
    width=None,
    height=None,
):
    args = build_dataframe(args=locals(), constructor=None)
    
    if agg_func is None:
        agg_func = np.mean
    
    lat_range = args["data_frame"][args["lat"]].agg(["min", "max"]).values
    lon_range = args["data_frame"][args["lon"]].agg(["min", "max"]).values

    hexagons_lats, hexagons_lons, hexagons_ids, count = _compute_hexbin(
        lat=args["data_frame"][args["lat"]].values,
        lon=args["data_frame"][args["lon"]].values,
        lat_range=lat_range,
        lon_range=lon_range,
        color=None,
        nx=gridsize,
        agg_func=agg_func,
        min_count=-np.inf,
    )

    geojson = _hexagons_to_geojson(hexagons_lats, hexagons_lons, hexagons_ids)

    if zoom is None:
        if height is None and width is None:
            mapDim = dict(height=450, width=450)
        elif height is None and width is not None:
            mapDim = dict(height=450, width=width)
        elif height is not None and width is None:
            mapDim = dict(height=height, width=height)
        else:
            mapDim = dict(height=height, width=width)
        zoom = _getBoundsZoomLevel(*lon_range, *lat_range, mapDim)
    
    if center is None:
        center=dict(lat=lat_range.mean(), lon=lon_range.mean())

    if args["animation_frame"] is not None:
        groups = args["data_frame"].groupby(args["animation_frame"]).groups
    else:
        groups = {0: args["data_frame"].index}

    agg_data_frame_list = []
    for frame, index in groups.items():
        df = args["data_frame"].loc[index]
        _, _, hexagons_ids, aggregated_value = _compute_hexbin(
            lat=df[args["lat"]].values,
            lon=df[args["lon"]].values,
            lat_range=lat_range,
            lon_range=lon_range,
            color=df[args["color"]].values if args["color"] else None,
            nx=gridsize,
            agg_func=agg_func,
            min_count=None,
        )
        agg_data_frame_list.append(
            pd.DataFrame(
                np.c_[hexagons_ids, aggregated_value],
                columns=["locations", "color"]
            )
        )
    agg_data_frame = pd.concat(
        agg_data_frame_list, axis=0, keys=groups.keys()
    ).rename_axis(index=("frame", "index")).reset_index("frame")
    
    agg_data_frame["color"] = pd.to_numeric(agg_data_frame["color"])

    if range_color is None:
        range_color = [
            agg_data_frame["color"].min(),
            agg_data_frame["color"].max()
        ]

    return choropleth_mapbox(
        data_frame=agg_data_frame,
        geojson=geojson,
        locations="locations",
        color="color",
        hover_data={"color": True, "locations": False, "frame": False},
        animation_frame=(
            "frame" if args["animation_frame"] is not None else None
        ),
        color_discrete_sequence=color_discrete_sequence,
        color_discrete_map=color_discrete_map,
        labels=labels,
        color_continuous_scale=color_continuous_scale,
        range_color=range_color,
        color_continuous_midpoint=color_continuous_midpoint,
        opacity=opacity,
        zoom=zoom,
        center=center,
        mapbox_style=mapbox_style,
        title=title,
        template=template,
        width=width,
        height=height,
    )

hexbin_mapbox.__doc__ = make_docstring(hexbin_mapbox)
