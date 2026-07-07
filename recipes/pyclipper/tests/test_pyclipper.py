def test_intersection():
    """pyclipper is a Cython C++ extension over the vendored Clipper library.
    Clip a triangle against a square — the shape rapidocr uses it for
    (text-box postprocessing) is exactly this kind of polygon math."""
    import pyclipper

    subj = [[180, 200], [260, 200], [260, 150], [180, 150]]  # square
    clip = [[190, 210], [240, 210], [240, 130], [190, 130]]  # square

    pc = pyclipper.Pyclipper()
    pc.AddPath(clip, pyclipper.PT_CLIP, True)
    pc.AddPath(subj, pyclipper.PT_SUBJECT, True)
    solution = pc.Execute(pyclipper.CT_INTERSECTION)

    assert len(solution) == 1
    # intersection of the two squares is the 50x50 box (190..240, 150..200)
    assert sorted(map(tuple, solution[0])) == [(190, 150), (190, 200), (240, 150), (240, 200)]


def test_offset():
    """PyclipperOffset (polygon dilation) — rapidocr's unclip step."""
    import pyclipper

    pco = pyclipper.PyclipperOffset()
    pco.AddPath([[0, 0], [100, 0], [100, 100], [0, 100]],
                pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
    solution = pco.Execute(10)

    assert len(solution) == 1
    xs = [p[0] for p in solution[0]]
    ys = [p[1] for p in solution[0]]
    assert min(xs) == -10 and max(xs) == 110
    assert min(ys) == -10 and max(ys) == 110


def test_scale_helpers():
    """The float<->int fixed-point helpers used by every real caller."""
    import pyclipper

    path = [(0.5, 0.25), (1.5, 2.75)]
    scaled = pyclipper.scale_to_clipper(path)
    back = pyclipper.scale_from_clipper(scaled)
    assert [tuple(p) for p in back] == [(0.5, 0.25), (1.5, 2.75)]
