# pyxirr

[`pyxirr`](https://github.com/Anexen/pyxirr) is a Rust implementation of the financial
functions a spreadsheet calls XIRR, XNPV, IRR, NPV, MIRR, PMT, PV and FV, plus a
[`pyxirr.pe`](https://anexen.github.io/pyxirr/private_equity.html) module of
private-equity measures such as DPI, TVPI, KS-PME and direct alpha. XIRR is the one it is
named after: the annualised rate at which a schedule of *dated, irregularly spaced* cash
flows breaks even. In a Flet app it prices a portfolio, a loan book or a fund's drawdowns
on the device, offline — the wheel has no dependencies at all.

It is a numerical root-finder, so the interesting question is not throughput but whether
the number it hands back is the one you wanted. See [Convergence](#convergence).

## Install

Add pyxirr to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pyxirr",
]
```

Nothing else is pulled in. pyxirr accepts `numpy` arrays and `pandas` Series and
DataFrames if your app happens to have them — and hands a `numpy` array back when it was
given one — but lists, tuples, dicts and generators work with neither installed, and
importing pyxirr imports neither.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`cashflow-desk`](examples/cashflow-desk) — solves four dated schedules for their
  break-even rate and shows what the solver does when there is no answer, or several.

## Usage in a Flet app

Two calls do the job: one to solve, one to check the answer.

```python
import pyxirr

dates = ["2022-03-14", "2022-09-30", "2023-03-31", "2025-06-13"]
amounts = [-240000.0, 8400.0, 8400.0, 274000.0]

rate = pyxirr.xirr(dates, amounts)
residual = pyxirr.xnpv(rate, dates, amounts)   # ~0, because that is the definition
result.value = f"{rate:.2%}"
```

Dates may be zero-padded ISO strings as above or `datetime.date`/`datetime.datetime`
objects, and the two sequences may be replaced by a dict, a list of `(date, amount)` pairs
or a DataFrame. Amounts may be `int`, `float` or `Decimal`. By upstream's convention money
leaving is negative and money arriving is positive; a schedule needs at least one of each.

### Storage

pyxirr never touches the filesystem — every function takes sequences and returns numbers.
What needs a home is the schedule. Put a ledger the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "cashflows.csv")
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for results worth keeping between launches and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a statement imported but not yet accepted. A reference schedule or benchmark index
shipped with the app is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and reach it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

### Threading

**pyxirr releases the GIL, and its functions hold no shared state.** Measured on desktop,
four concurrent `irr()` calls over a 400,000-payment schedule finished in about 1.3× the
time one took, so threads really do run in parallel rather than queueing on the
interpreter. No lock is needed around a call.

That matters less often than it sounds, because a realistic schedule solves in
microseconds. Reach for
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) when
the work *around* the solve is the slow part — reading a file, parsing a statement,
repricing a book — and finish the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), which a
background thread does not get for free.

### Convergence

`xirr` and `irr` search for the rate at which the discounted flows sum to zero. There is
no closed form, so three different things can come back, and they need different handling:

* **An exception.** A schedule with no sign change, or dates and amounts of different
  lengths, raises `InvalidPaymentsError`. That is the only failure `silent=True` converts
  into `None` — a malformed date still raises `ValueError` straight through it, so a
  user-supplied schedule needs its own `try` regardless.
* **`None`.** A curve that never reaches zero returns `None` *without* raising, with or
  without `silent`. Non-convergence is a value here, not an error.
* **One number out of several.** When the amounts change sign more than once the curve can
  cross zero repeatedly and every crossing is a correct answer. `guess` alone decides
  which you get: `[-1_000_000, +4_100_000, -4_100_000, +1_000_000]` dated `2020-01-02`,
  `2021-01-04`, `2022-01-03` and `2023-01-03` has roots at −63.31%, 0.00% and +168.69%.
  The roots move with the dates as much as with the amounts — put the same four amounts on
  exact anniversaries and the outer two become −63.42% and +172.06%.

So a rate that came from user data is worth two lines of scrutiny. The residual is rarely
exactly zero — on a schedule moving 556,800 currency units it comes back around `4e-04` —
so the tolerance has to be scaled to the money involved rather than compared to `0.0`:

```python
rate = pyxirr.xirr(dates, amounts, silent=True)
if rate is None or not math.isfinite(rate):
    status.value = "no rate for this schedule"
elif abs(pyxirr.xnpv(rate, dates, amounts)) > 0.01:
    status.value = "solver did not settle"
```

`is_conventional_cash_flow(amounts)` is the cheap screen for that third case: `True` only
when the amounts change sign exactly once, which is when there can be at most one rate.
`zero_crossing_points(amounts)` counts those changes — an upper bound, never a count of
roots. To locate the roots themselves, aim the same helper at an NPV curve instead, which
is [upstream's own approach](https://github.com/Anexen/pyxirr#multiple-irr-problem):
`xnpv` broadcasts over rates, so one call gives the profile and every crossing in it
brackets a root that `guess` can be pointed into. Both helpers are documented in that
README only — the docs site does not mention either.

```python
rates = [i / 40 for i in range(-36, 121)]        # -90% to +300%
curve = pyxirr.xnpv(rates, dates, amounts)
for index in pyxirr.zero_crossing_points(curve):
    root = pyxirr.xirr(dates, amounts, guess=rates[index], silent=True)
```

When one defensible number is wanted instead of whichever root the solver walked into,
[`mirr`](https://anexen.github.io/pyxirr/functions.html#mirr) always has exactly one.

### App size

The wheel is approximately 430–550 KB compressed and 1.0–1.3 MB unpacked per
architecture: one extension module, a four-line `__init__.py`, two type stubs, a `py.typed`
marker and an SBOM. There is no data directory and nothing worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup).

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
when the application does not need every ABI — though at this size that lever is worth
pulling for the rest of the app, not for pyxirr.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, built from the same Rust crate, and returns
the same values. The asymmetry to watch is optional-dependency drift: on a laptop `pandas`
is usually installed, so handing a DataFrame straight to `xirr` works and nobody notices
the coupling — on device that needs `pandas` in the app's dependencies too. Converting at
the boundary keeps the mobile path independent of what the laptop happens to have.

## Things to know

- **Date strings must be zero-padded.** `"2024-01-15"` parses; `"2024-1-15"` raises
  `ValueError: the 'month' component could not be parsed`, and so do `"15.01.2024"`,
  `"15/01/2024"` and `"1/15/2024"`. That message blames the month whichever component is
  actually wrong, so do not read it as a diagnosis. Accepted are `YYYY-MM-DD`,
  `YYYY-MM-DD HH:MM:SS` or `YYYY-MM-DDTHH:MM:SS` with or without a trailing `Z`, and
  `MM/DD/YYYY` — American order in the last one. `date` and `datetime` objects avoid the question.

- **`day_count` wants the market spelling, not the attribute name.** `"ACT/365F"` works;
  `"ACT_365F"` raises `ValueError: Invalid Day Count Convention`, even though
  `DayCount.ACT_365F` is the constant's name, and passing the constant itself always works.
  The choice moves the answer: the three-payment schedule in `tests/test_pyxirr.py`
  solves to 17.50% under the ACT/365F default and 17.24% under ACT/360.

- **A degenerate schedule answers instead of complaining.** Two payments on the same date
  return `inf` if the schedule gains and `-1.0` if it loses, while three or more on one
  date return `None` — so `inf` is not the tell you can guard on. A schedule spanning a
  single day returns a finite but meaningless rate: `[-100, 200]` one day apart solves to
  `7.5e+109`. Nothing raises in any of these, so check `math.isfinite` *and* sanity-check
  the magnitude before putting a rate on screen.

- **Which root you get is `guess`, not a policy.** Upstream describes looking for a result
  near Excel's default guess of 0.1 and, only if that fails, trying other starting points
  and taking the lowest to be conservative. On the three-root schedule above the default
  returns 0.00% — the middle root, not the lowest. Enumerate a non-conventional schedule
  rather than trusting a default to be conservative for you.

- **`npv` discounts from period 0, which is not what Excel does.** The default
  `start_from_zero=True` treats `amounts[0]` as today's money; Excel's `NPV` discounts the
  first element by one period. Pass `start_from_zero=False` to match a spreadsheet.

- **`Decimal` goes in, `float` comes out.** Amounts and rates accept `Decimal` and every
  return value is a plain `float`. Re-quantise on the way out if the surrounding ledger is
  exact.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name, a version and a build number, and that is the whole recipe: no
patches, no build requirements, no `script_env`. pyxirr is a maturin/PyO3 crate with no C
dependencies and no build script that probes the host, so the cross-build needs nothing
beyond a Rust toolchain carrying the mobile targets. That is the zero-configuration case
rather than an oversight — sibling Rust recipes here do carry settings (`cbor2` and
`jiter` both pass `_PYTHON_SYSCONFIGDATA_NAME` through `build.script_env`) and pyxirr
needs none. All four Android ABIs and all three iOS slices build, `armeabi-v7a` included,
so there is no `excluded_arches` entry either.

### Upgrade hazards

Because the recipe is only a pin, a bump is a rebuild, and everything that can change
underneath it is upstream's: the vendored `Cargo.lock`, the minimum Rust version and the
numerical behaviour documented above. A bump failing with `can't find crate for core` is a
toolchain missing the mobile targets, not a recipe fault.

The consumer sections assert upstream behaviour a minor release can change with no signal
here — error taxonomy, accepted date forms, day-count spelling, which root the default
reaches, `inf` results — none of which is pinned by a test.

### Re-verification checklist

- **Failure taxonomy:** no sign change raises `InvalidPaymentsError`; a curve with no root
  returns `None` without raising; a bad date string raises `ValueError`; `silent=True`
  still covers only the first of the three.
- **Parsing and conventions:** zero-padded ISO and `MM/DD/YYYY` accepted, unpadded forms
  rejected; `"ACT/365F"` accepted and `"ACT_365F"` rejected, with the ACT/360 spread
  re-measured on a fixed schedule.
- **Root selection:** re-solve a known three-root schedule at the default guess and record
  which root comes back before repeating the "not the lowest" claim; re-run the degenerate
  cases, which return `inf`, `-1.0` or `None` depending on payment count and direction.
- **Threading:** re-measure the parallel scaling. It is the one consumer claim here that
  rests on a timing rather than a value.
- **Wheel shape and size:** still one extension with no data directory, with the ranges
  re-measured from the built wheels rather than scaled from these. maturin also drops a
  copy of upstream's `pyproject.toml` at the site-packages root; harmless today, but it is
  the kind of unnamespaced file that collides once another wheel ships one.

### Coverage gaps

`tests/test_pyxirr.py` exercises two things on device: `irr` with an `npv` round-trip, and
`xirr` over `datetime.date` objects with an `xnpv` round-trip. It does not cover string
date parsing, `silent=True`, non-convergence, the day-count conventions, `Decimal` amounts,
the vectorised call forms, the `pyxirr.pe` module, or multi-root behaviour. Every claim
here about those was measured on desktop against the same 0.10.8 release; treat them as
desktop-verified until device tests exist.
