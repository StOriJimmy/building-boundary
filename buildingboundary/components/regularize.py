# -*- coding: utf-8 -*-
"""

@author: Chris Lucas
"""

import math

import numpy as np
from shapely.geometry import Polygon, MultiPolygon

from ..utils.angle import min_angle_difference, perpendicular
from ..utils.error import ThresholdError
from ..utils import create_segments, distance
from .merge import merge_segments


def get_primary_segments(segments, num_points):
    """
    Checks the segments and returns the segments which are supported
    by at least the given number of points.

    Parameters
    ----------
    segments : list of BoundarySegment
        The boundary (wall) segments of the building (part).
    num_points : int, optional
        The minimum number of points a segment needs to be supported by
        to be considered a primary segment.

    Returns
    -------
    primary_segments : list of segments
        The segments which are supported by at least the given number of
        points.
    """
    primary_segments = [s for s in segments if len(s.points) >= num_points]
    return primary_segments


def find_main_orientation(segments):
    """
    Checks which segment is supported by the most points and returns
    the orientation of this segment.

    Parameters
    ----------
    segments : list of BoundarySegment
        The boundary (wall) segments of the building (part).

    Returns
    -------
    main_orientation : float
        The orientation of the segment supported by the most points.
        In radians.
    """
    longest_segment = np.argmax([len(s.points) for s in segments])
    main_orientation = segments[longest_segment].orientation
    return main_orientation


def sort_orientations(orientations):
    """
    Sort orientations by the length of the segments which have that
    orientation.

    Parameters
    ----------
    orientations : dict
        The orientations and corrisponding lengths

    Returns
    -------
    sorted_orientations : list of float

    """
    unsorted_orientations = [o['orientation'] for o in orientations]
    lengths = [o['size'] for o in orientations]
    sort = np.argsort(lengths)
    sorted_orientations = np.array(unsorted_orientations)[sort].tolist()
    return sorted_orientations


def compute_primary_orientations(primary_segments, angle_epsilon=0.1):
    """
    Computes the primary orientations based on the given primary segments.

    Parameters
    ----------
    primary_segments : list of BoundarySegment
        The primary segments.
    angle_epsilon : float, optional
        Angles will be considered equal if the difference is within
        this value (in radians).

    Returns
    -------
    primary_orientations : list of float
        The computed primary orientations in radians, sorted by the length
        of the segments which have that orientation.
    """
    orientations = []

    for s in primary_segments:
        a1 = s.orientation
        for o in orientations:
            a2 = o['orientation']
            angle_diff = min_angle_difference(a1, a2)
            if angle_diff < angle_epsilon:
                if len(s.points) > o['size']:
                    o['size'] = len(s.points)
                    o['orientation'] = a1
                break
        else:
            orientations.append({'orientation': a1,
                                 'size': len(s.points)})

    primary_orientations = sort_orientations(orientations)

    return primary_orientations


def check_perpendicular(primary_orientations, angle_epsilon=0.1):
    """
    Checks if a perpendicular orientation to the main orientation
    exists.

    Parameters
    ----------
    primary_orientations : list of floats
        The primary orientations, where the first orientation in the
        list is the main orientation (in radians).
    angle_epsilon : float, optional
        Angles will be considered equal if the difference is within
        this value (in radians).

    Returns
    -------
     : bool
        True if a perpendicular orientation to the main orientation
    exists.
    """
    main_orientation = primary_orientations[0]
    diffs = [min_angle_difference(main_orientation, a)
             for a in primary_orientations[1:]]
    diffs_perp = np.array(diffs) - math.pi/2
    return min(np.abs(diffs_perp)) < angle_epsilon


def add_perpendicular(primary_orientations, angle_epsilon=0.1):
    """
    Adds an orientation perpendicular to the main orientation if no
    approximate perpendicular orientation is present in the primary
    orientations.

    Parameters
    ----------
    primary_orientations : list of floats
        The primary orientations, where the first orientation in the
        list is the main orientation (in radians).
    angle_epsilon : float, optional
        Angles will be considered equal if the difference is within
        this value (in radians).

    Returns
    -------
    primary_orientations : list of floats
        The refined primary orientations
    """
    main_orientation = primary_orientations[0]
    # if only one primary orientation is found, add an orientation
    # perpendicular to it.
    if len(primary_orientations) == 1:
        primary_orientations.append(perpendicular(main_orientation))
    else:
        # add a perpendicular orientation if no approximate perpendicular
        # orientations were found
        if not check_perpendicular(primary_orientations,
                                   angle_epsilon=angle_epsilon):
            primary_orientations.append(perpendicular(main_orientation))

    return primary_orientations


def get_primary_orientations(segments, num_points=None,
                             angle_epsilon=0.1):
    """
    Computes the primary orientations of the building by checking the
    number of points it is supported by. If multiple orientations are
    found which are very close to each other, a mean orientation will be
    taken. If no primary orientations can be found, the orientation of the
    segment supported by the most points will be taken.

    Parameters
    ----------
    segments : list of BoundarySegment
        The boundary (wall) segments of the building (part).
    num_points : int, optional
        The minimum number of points a segment needs to be supported by
        to be considered a primary segment.
    angle_epsilon : float, optional
        Angles will be considered equal if the difference is within
        this value (in radians).

    Returns
    -------
    primary_orientations : list of float
        The computed primary orientations in radians.
    """
    if num_points is not None:
        primary_segments = get_primary_segments(segments, num_points)
    else:
        primary_segments = []

    if len(primary_segments) > 0:
        primary_orientations = compute_primary_orientations(primary_segments,
                                                            angle_epsilon)
    else:
        primary_orientations = [find_main_orientation(segments)]

    primary_orientations = add_perpendicular(primary_orientations,
                                             angle_epsilon=angle_epsilon)

    return primary_orientations


def regularize_segments(segments, primary_orientations, max_error=None):
    """
    Sets the orientation of the segments to the closest of the given
    orientations.

    Parameters
    ----------
    segments : list of BoundarySegment
        The wall segments to regularize.
    primary_orientations : list of floats
        The orientations all other orientations will be set to, given
        in radians.
    max_error : float or int, optional
        The maximum error a segment can have after regularization. If
        above the original orientation will be kept.

    Returns
    -------
    segments : list of BoundarySegment
        The wall segments after regularization.
    """
    for s in segments:
        target_orientation = s.target_orientation(primary_orientations)
        try:
            s.regularize(math.tan(target_orientation), max_error=max_error)
        except ThresholdError:
            pass

    return segments


def regularize_and_merge(segments, primary_orientations,
                         merge_angle, max_error=None,
                         max_merge_distance=None):
    """
    Keeps regularizing and merging the segments until no changes
    happen.

    Parameters
    ----------
    segments : list of BoundarySegment
        The wall segments to regularize.
    primary_orientations : list of floats
        The orientations all other orientations will be set to, given
        in radians.
    merge_angle : float or int
        Two segments will be merged if the difference between their
        orientations are within this value.
    max_error : float or int, optional
        The maximum error a segment can have after regularization. If
        above the original orientation will be kept.

    Returns
    -------
    segments : list of BoundarySegment
        The wall segments after regularization and merging.
    merge_history : list of list of int
        The indices of all merged segments
    """
    prev_num_segments = 0
    num_segments = len(segments)

    merge_history = []

    while num_segments != prev_num_segments:
        prev_num_segments = len(segments)

        segments = regularize_segments(segments,
                                       primary_orientations,
                                       max_error=max_error)

        segments, merge_history_part = merge_segments(segments,
                                                      merge_angle,
                                                      max_merge_distance)
        merge_history.extend(merge_history_part)

        num_segments = len(segments)

    segments = regularize_segments(segments, primary_orientations,
                                   max_error=max_error)

    return segments, merge_history


def polygon_orientations(polygon):
    for s in create_segments(polygon.exterior.coords[:-1]):
        dx, dy = s[0] - s[1]
        dist = distance(s[0], s[1])
        if dist > 1:
            yield math.atan2(dy, dx)


def footprint_orientations(geom):
    orientations = []
    if type(geom) == Polygon:
        orientations = list(polygon_orientations(geom))
    elif type(geom) == MultiPolygon:
        for p in geom:
            orientations.extend(list(polygon_orientations(p)))
    return orientations
