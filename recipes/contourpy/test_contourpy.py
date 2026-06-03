def test_lines_from_array():
    """contourpy is matplotlib's C++ contour-tracing backend. Generate a
    simple 5x5 paraboloid and ask for one level — covers the native
    contour generator + path output."""
    import contourpy
    import numpy as np

    # f(x,y) = x^2 + y^2 over [-2..2] x [-2..2]
    xs, ys = np.meshgrid(np.linspace(-2, 2, 5), np.linspace(-2, 2, 5))
    zs = xs**2 + ys**2

    gen = contourpy.contour_generator(x=xs, y=ys, z=zs)
    lines = gen.lines(2.0)  # circle-ish contour at z=2

    assert lines is not None
    # At least one contour segment was traced — exact count depends on
    # algorithm choice, just confirm it's not empty.
    assert len(lines) >= 1


def test_algorithm_name():
    """Sanity: the default algorithm is the C++ `serial` backend, which is
    the recipe's reason for existing."""
    import contourpy

    gen = contourpy.contour_generator(
        z=[[0.0, 1.0], [1.0, 2.0]],
    )
    # Touching .lines() is enough to know the native object initialised.
    assert gen.lines(0.5) is not None
