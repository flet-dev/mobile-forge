def test_solve_simple_constraint():
    """kiwisolver is matplotlib's Cassowary constraint solver, written in
    C++. Set up a small system and check the solver finds a valid
    assignment — exercises the native solve loop."""
    from kiwisolver import Solver, Variable

    x = Variable("x")
    y = Variable("y")
    solver = Solver()

    # x + y = 10, x - y = 4  →  x=7, y=3
    solver.addConstraint(x + y == 10)
    solver.addConstraint(x - y == 4)
    solver.updateVariables()

    assert abs(x.value() - 7.0) < 1e-9
    assert abs(y.value() - 3.0) < 1e-9


def test_strength_priority():
    """Soft vs required constraint — distinct kiwi C++ codepath."""
    from kiwisolver import Solver, Variable, strength

    x = Variable("x")
    solver = Solver()
    # Required: x = 100; weak: x = 1. Required wins.
    solver.addConstraint(x == 100)
    solver.addConstraint((x == 1) | strength.weak)
    solver.updateVariables()
    assert abs(x.value() - 100.0) < 1e-9
