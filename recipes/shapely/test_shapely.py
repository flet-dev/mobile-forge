def test_geometry_ops():
    """shapely wraps GEOS (the C++ computational-geometry library). Cover
    geometry construction + a non-trivial spatial predicate."""
    from shapely.geometry import Point, Polygon

    triangle = Polygon([(0, 0), (4, 0), (0, 3)])
    assert abs(triangle.area - 6.0) < 1e-9  # ½ × base × height

    inside = Point(1, 1)
    outside = Point(5, 5)
    assert triangle.contains(inside)
    assert not triangle.contains(outside)


def test_buffer_and_intersection():
    """Buffer + intersect exercises GEOS's harder operations."""
    from shapely.geometry import Point

    circle = Point(0, 0).buffer(1.0)
    # `buffer(1)` approximates a unit circle; area ≈ π.
    assert 3.0 < circle.area < 3.2

    far = Point(10, 10).buffer(1.0)
    assert circle.intersection(far).is_empty
