def test_propssi_water_boiling_point():
    """PropsSI is the Cython entry into the CoolProp C++ core. Asking for
    the saturation temperature of water at 1 atm forces the native
    extension (`CoolProp._CoolProp` / `CoolProp.CoolProp.so`) to load,
    which on Android exercises the libc++_shared.so dep declared in
    meta.yaml — same canary shape as numpy's _pocketfft test."""
    from CoolProp.CoolProp import PropsSI

    # Saturation temperature of water at P = 101325 Pa, x = 0 (sat. liquid).
    # Reference value from NIST: 373.124 K (rounded). Wider tolerance to
    # absorb fluid-property-table revisions across CoolProp versions.
    t = PropsSI("T", "P", 101325, "Q", 0, "Water")
    assert 372.5 < t < 373.5, f"saturation T at 1 atm = {t}"


def test_phase_envelope():
    """Tests a multi-arg property query — exercises the
    HumidAirProp / saturation lookup paths inside the C++ core."""
    from CoolProp.CoolProp import PropsSI

    # Density of saturated liquid water at 25 °C should be ~997 kg/m³.
    rho = PropsSI("D", "T", 298.15, "Q", 0, "Water")
    assert 990 < rho < 1005, f"liquid water density at 25 °C = {rho}"
