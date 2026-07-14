from __future__ import annotations

import multiprocessing
import os
import re
import shutil
import struct
import sys
import tarfile
import zipfile
from abc import ABC, abstractmethod, abstractproperty
from email import generator, message, parser
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from packaging.utils import canonicalize_name, canonicalize_version

from forge import subprocess
from forge.logger import log, log_exception
from forge.pypi import get_pypi_source_urls
from forge.utils import merge_dicts

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no-cover-if-gte-py310
    import tomli as tomllib


if TYPE_CHECKING:
    from forge.cross import CrossVEnv
    from forge.package import Package


class Builder(ABC):
    def __init__(self, cross_venv: CrossVEnv, package: Package):
        self.cross_venv = cross_venv
        self.package = package

    @property
    @abstractmethod
    def build_path(self) -> Path:
        """The path in which all environment and sources for the build will be
        created."""
        ...

    @property
    @abstractmethod
    def log_file_path(self) -> Path:
        """The path where build logs should be written."""
        ...

    @property
    def error_log_file_path(self) -> Path:
        """The path for the log file if a build error occurs."""
        return self.log_file_path.parent.parent / "errors" / self.log_file_path.name

    @property
    @abstractmethod
    def source_archive_path(self) -> Path:
        """The source archive file for the package."""
        ...

    def install_requirements(self, target):
        requirements = []
        for requirement in self.package.meta["requirements"][target]:
            try:
                package, version = requirement.split(maxsplit=1)
                if version.startswith((">=", "<=", "!=", "==", "~=", ">", "<")):
                    specifier = f"{package}{version}"
                elif version.startswith("^"):
                    specifier = f"{package}>={version[1:]}"
                elif version.startswith("~"):
                    specifier = f"{package}~={version[1:]}"
                else:
                    specifier = f"{package}=={version}"
            except ValueError:
                specifier = requirement
            requirements.append(specifier)

        if requirements:
            self.cross_venv.pip_install(
                self.log_file,
                requirements,
                paths=[Path.cwd() / "dist"],
                build=target == "build",
            )
        else:
            log(self.log_file, f"No {target} requirements.")

    def fix_host_tool_shims(self):
        python_path = (
            self.cross_venv.venv_path
            / "cross"
            / "bin"
            / f"python3.{sys.version_info.minor}"
        )
        for shim in (self.cross_venv.venv_path / "cross" / "bin").iterdir():
            with open(shim, "r") as f:
                lines = f.readlines()
            if len(lines) > 0 and lines[0].strip() == f"#!{python_path}":
                log(self.log_file, f"Fixing host shim: {shim}")
                with open(shim, "w") as f:
                    f.writelines(
                        [
                            "#!/bin/sh\n",
                            "'''exec' {} \"$0\" \"$@\"\n".format(python_path),
                            "' '''\n\n",
                        ]
                        + lines[1:]
                    )
            elif (
                len(lines) > 2
                and lines[0].strip() == "#!/bin/sh"
                and lines[1].startswith("'''exec' ")
                and lines[2].startswith("' '''")
                and lines[2].strip() != "' '''"
            ):
                # Repair legacy malformed shim output where the separator line was
                # accidentally merged with Python code (e.g. "' '''import sys").
                log(self.log_file, f"Repairing malformed host shim: {shim}")
                suffix = lines[2][len("' '''") :]
                repaired = [lines[0], lines[1], "' '''\n"]
                if suffix:
                    repaired.append(suffix)
                repaired += lines[3:]
                with open(shim, "w") as f:
                    f.writelines(repaired)

    @abstractmethod
    def download_source_url(self): ...

    def download_source(self):
        """Download the source tarball."""
        url = self.download_source_url()
        log(self.log_file, f"Downloading {url}...", end="", flush=True)
        self.source_archive_path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, follow_redirects=True) as response:
            with self.source_archive_path.open("wb") as f:
                for i, chunk in enumerate(response.iter_bytes()):
                    if i % 100 == 0:
                        log(self.log_file, ".", end="", flush=True)
                    f.write(chunk)
        log(self.log_file, " done.")

    def unpack_source(self):
        log(
            self.log_file,
            f"Unpacking {self.source_archive_path.relative_to(Path.cwd())}...",
        )
        # Determine the stripping level. By default, this is 1;
        # but some source types can override.
        try:
            strip = self.package.meta["source"]["strip"]
        except (TypeError, KeyError):
            strip = 1

        # Some packages (e.g., brotli) have uploaded a .tar.gz file... that is
        # actually a zipfile (!).
        if tarfile.is_tarfile(self.source_archive_path):
            # This is the equivalent of --strip-components=<strip>
            def members(tf: tarfile.TarFile, strip=1):
                for member in tf.getmembers():
                    parts = member.path.split("/", strip)
                    try:
                        if parts[strip]:
                            member.path = parts[strip]
                            yield member
                    except IndexError:
                        pass

            with tarfile.open(self.source_archive_path) as tf:
                tf.extractall(
                    path=self.build_path,
                    members=members(tf, strip=strip) if strip else None,
                )
        elif zipfile.is_zipfile(self.source_archive_path):
            # Strip the top level folder.
            zf = zipfile.ZipFile(self.source_archive_path)

            def members(zf, strip=1):
                for member in zf.infolist():
                    parts = member.filename.split("/", strip)
                    try:
                        if parts[strip]:
                            member.filename = parts[strip]
                            yield member
                    except IndexError:
                        pass

            zf.extractall(
                path=self.build_path,
                members=members(zf, strip=strip) if strip else None,
            )
        else:
            raise RuntimeError(
                f"Can't identify archive type of {self.source_archive_path}"
            )

    def patch_source(self):
        patched = False
        for patch in self.package.meta["patches"]:
            patchfile = self.package.recipe_path / "patches" / patch
            log(
                self.log_file,
                f"Applying {patchfile.relative_to(self.package.recipe_path)}...",
            )
            # This can use a raw subprocess.run because it's a system command,
            # not anything dependent on the Python environment.
            subprocess.run(
                self.log_file,
                [
                    "patch",
                    "-p1",
                    "--ignore-whitespace",
                    "--quiet",
                    "--input",
                    str(patchfile),
                ],
                cwd=self.build_path,
            )
            patched = True

        if not patched:
            log(self.log_file, "No patches to apply.")

    def prepare(self, clean=True):
        if clean and self.build_path.is_dir():
            if clean:
                log(self.log_file, f"\n[{self.cross_venv}] Clean up old builds")
                log(
                    self.log_file,
                    f"Removing {self.build_path.relative_to(Path.cwd())}...",
                )
                shutil.rmtree(self.build_path)

        if self.package.meta.get("source") is None:
            # A `source: null` recipe has no upstream archive to download: its build.sh
            # produces its own sources (e.g. copying a library out of the NDK, or
            # generating one inline). Skip the download/unpack and just create an empty
            # build directory for build.sh to work in.
            if not self.build_path.is_dir():
                log(
                    self.log_file,
                    f"\n[{self.cross_venv}] No source to download; "
                    "creating empty build directory",
                )
                self.build_path.mkdir(parents=True, exist_ok=True)
        else:
            # Re-download sources if caching is disabled or no cached tarball exists.
            # By default, the cached tarball is reused across arch builds to avoid downloading
            # the same source multiple times. Disable caching when testing source-tarball patches,
            # since each arch reuses and re-unpacks the same cached archive.
            if (
                os.getenv("MOBILE_FORGE_CACHE_DOWNLOADS_OFF")
                or not self.source_archive_path.is_file()
            ):
                log(self.log_file, f"\n[{self.cross_venv}] Download package sources")
                self.download_source()

            if not self.build_path.is_dir():
                log(self.log_file, f"\n[{self.cross_venv}] Unpack sources")
                self.unpack_source()

                log(self.log_file, f"\n[{self.cross_venv}] Apply patches")
                self.patch_source()

        # Create a clean cross environment.
        log(self.log_file, f"\n[{self.cross_venv}] Create clean build environment")
        self.cross_venv.create(location=self.build_path, clean=True)

        log(self.log_file, f"\n[{self.cross_venv}] Install forge host requirements")
        self.install_requirements("host")
        # host_build deps install into the cross env like host deps (so the build
        # can link them), but are NOT promoted to the wheel's Requires-Dist (that
        # loop below only walks "host"). For statically-linked native libs.
        log(
            self.log_file,
            f"\n[{self.cross_venv}] Install forge host_build requirements",
        )
        self.install_requirements("host_build")
        self.fix_host_tool_shims()

        log(self.log_file, f"\n[{self.cross_venv}] Install forge build requirements")
        self.install_requirements("build")

    def compile_env(self, **kwargs) -> dict[str, str]:
        sysconfig_data = self.cross_venv.sysconfig_data
        install_root = self.cross_venv.install_root

        ar = sysconfig_data["AR"]
        cc = sysconfig_data["CC"]
        cxx = sysconfig_data["CXX"]
        strip = "strip"
        ranlib = "ranlib"
        cflags = self.cross_venv.sysconfig_data["CFLAGS"]
        cppflags = self.cross_venv.sysconfig_data["CPPFLAGS"]
        ndk_sysroot = None

        # Add install root include
        if (install_root / "include").is_dir():
            cflags += f" -I{install_root}/include"

        if self.cross_venv.sdk != "android":
            # Pre Python 3.11 versions included BZip2 and XZ includes in CFLAGS. Remove them.
            cflags = re.sub(r"-I.*/merge/iOS/.*/bzip2-.*/include", "", cflags)
            cflags = re.sub(r"-I.*/merge/iOS/.*/xs-.*/include", "", cflags)

            # Replace any hard-coded reference to --sysroot=<sysroot> with the actual reference
            cflags = re.sub(
                r"--sysroot=\w+", f"--sysroot={self.cross_venv.sdk_root}", cflags
            )

            # Add SDK root include
            if (self.cross_venv.sdk_root / "usr" / "include").is_dir():
                cflags += f" -I{self.cross_venv.sdk_root}/usr/include"

            cppflags += f" -mios-version-min={self.cross_venv.sdk_version}"
        else:
            # Some Python Android support archives reference an embedded NDK path
            # that isn't present in CI. If NDK_HOME is set, re-point missing
            # compiler/binutils paths to that installed NDK toolchain.
            ndk_home = os.environ.get("NDK_HOME")
            if ndk_home:
                prebuilt_dirs = list(
                    (Path(ndk_home) / "toolchains" / "llvm" / "prebuilt").glob("*")
                )
                if prebuilt_dirs:
                    ndk_bin = prebuilt_dirs[0] / "bin"
                    if not Path(cc).is_file():
                        cc = str(ndk_bin / Path(cc).name)
                    if not Path(cxx).is_file():
                        cxx = str(ndk_bin / Path(cxx).name)
                    if not Path(ar).is_file():
                        ar = str(ndk_bin / Path(ar).name)
                    if not Path(strip).is_file():
                        strip = str(ndk_bin / "llvm-strip")
                    if not Path(ranlib).is_file():
                        ranlib = str(ndk_bin / "llvm-ranlib")

            # Derive strip/ranlib from the final AR location when available.
            if ar:
                ar_parent = Path(ar).parent
                derived_strip = ar_parent / "llvm-strip"
                derived_ranlib = ar_parent / "llvm-ranlib"
                if derived_strip.is_file():
                    strip = str(derived_strip)
                if derived_ranlib.is_file():
                    ranlib = str(derived_ranlib)
            ndk_sysroot = Path(cc).parent.parent / "sysroot"
            if (ndk_sysroot / "usr" / "include").is_dir():
                cflags += f" -I{ndk_sysroot}/usr/include"
        if self.cross_venv.sdk != "android":
            strip = "strip"
            ranlib = "ranlib"

        ldflags = self.cross_venv.sysconfig_data["LDFLAGS"]

        # -lpython3.x
        ldflags += " -L{}/lib".format(self.cross_venv.sysconfig_data["prefix"])

        # Add install root lib
        if (install_root / "lib").is_dir():
            ldflags += f" -L{install_root}/lib"

        if self.cross_venv.sdk == "android" and ndk_sysroot:
            ndk_triplet_lib = (
                ndk_sysroot
                / "usr"
                / "lib"
                / self.cross_venv.platform_triplet
                / str(self.cross_venv.sdk_version)
            )
            ndk_arch_lib = (
                ndk_sysroot / "usr" / "lib" / self.cross_venv.platform_triplet
            )
            if ndk_triplet_lib.is_dir():
                ldflags += f" -L{ndk_triplet_lib}"
            elif ndk_arch_lib.is_dir():
                ldflags += f" -L{ndk_arch_lib}"

            # 16 KB page alignment required by Google Play (Android 15+)
            ldflags += " -Wl,-z,max-page-size=16384"

        # cargo_ldflags = re.sub(r"-march=[\w-]+", "", ldflags)
        cargo_ldflags = " -L{}/lib".format(self.cross_venv.sysconfig_data["prefix"])
        # On Android, pyo3-ffi (and similar) link `-lpython3` / `-lpython3.<X>`.
        # PYO3_CROSS_LIB_DIR points at the host stdlib directory (so maturin can
        # find _sysconfigdata__*.py and build-details.json there), but the
        # actual `libpython*.so` files live in the host install's `lib/`
        # directory (LIBDIR). Add LIBDIR as an extra library search path so the
        # linker can resolve those `-lpython*` references.
        host_libdir = self.cross_venv.sysconfig_data.get("LIBDIR")
        if host_libdir:
            cargo_ldflags += f" -L{host_libdir}"
        cargo_ldflags += " -C link-arg=-undefined -C link-arg=dynamic_lookup"

        if self.cross_venv.sdk == "android":
            # 16 KB page alignment required by Google Play (Android 15+)
            cargo_ldflags += " -C link-arg=-z -C link-arg=max-page-size=16384"

            # NDK r23+ removed libgcc.a (unwinding moved to libunwind), but some
            # Rust toolchains still emit `-lgcc` on the link line -- e.g. recipes
            # that pin an older nightly via rust-toolchain.toml (polars). The
            # current stable target spec no longer does, so most recipes are
            # unaffected. Drop a libgcc.a *linker script* that redirects to
            # libunwind (already linked) onto the search path so `-lgcc` resolves
            # instead of failing with `ld.lld: error: unable to find library -lgcc`.
            libgcc_shim = self.build_path / ".libgcc-shim"
            libgcc_shim.mkdir(parents=True, exist_ok=True)
            (libgcc_shim / "libgcc.a").write_text("INPUT(-lunwind)\n")
            cargo_ldflags += f" -L{libgcc_shim}"

        if self.cross_venv.sdk != "android":
            # Replace any hard-coded reference to -isysroot <sysroot> with the actual reference
            ldflags = re.sub(
                r"-isysroot \w+", f"-isysroot={self.cross_venv.sdk_root}", ldflags
            )

            # Add SDK root lib
            if (self.cross_venv.sdk_root / "usr" / "lib").is_dir():
                ldflags += f" -L{self.cross_venv.sdk_root}/usr/lib"

            # Add the framework search path. We do *not* append `-framework Python`
            # here -- doing so breaks autoconf-based builds like flet-libfreetype, whose
            # `./configure` probes the C compiler by linking a trivial hello.c against $LDFLAGS;
            # `-framework Python` makes that probe fail with `configure: error: C compiler cannot create executables`.
            # Cargo/setuptools/meson recipes each get the framework link via their own channel (cargo_ldflags
            # below, the cross sysconfig'\''s LDSHARED for setuptools, and the meson cross-file'\''s
            # c_link_args / cpp_link_args augmented in _create_meson_cross for meson).
            ldflags += f' -F "{self.cross_venv.host_python_home}"'
            cargo_ldflags += f" -C link-arg=-F{self.cross_venv.host_python_home} -C link-arg=-framework -C link-arg=Python"

        cargo_build_target = (
            {
                "arm64-apple-ios": "aarch64-apple-ios",
                "arm64-apple-ios-simulator": "aarch64-apple-ios-sim",
                # This one is odd; Rust doesn't provide an `x86_64-apple-ios-simulator`,
                # but there's no such thing as an x86_64 ios *device*.
                "x86_64-apple-ios-simulator": "x86_64-apple-ios",
            }[self.cross_venv.platform_triplet]
            if self.cross_venv.sdk != "android"
            else self.cross_venv.platform_triplet
        )

        # Point pkg-config at the pkgconfig dirs that matter for the target build:
        #   1. host_python_home/lib/pkgconfig — where python-X.Y.pc lives.
        #      Required for meson's `py.dependency()` to resolve the
        #      Python C dep via the relocated `.pc` files.
        #   2. install_root/lib/pkgconfig — where flet-lib* extract their
        #      own `.pc` files when installed as host wheels.
        #   3. <cross-venv>/{build,cross}/lib/pythonX.Y/site-packages/*/share/pkgconfig
        #      — pure-Python wheels (pybind11, …) ship their .pc files bundled
        #      inside site-packages rather than the usual lib/pkgconfig dir, so
        #      `dependency('pybind11')` via meson's pkg-config method only resolves
        #      once the .pc dir under the installed wheel is added explicitly.
        # All three sets of `.pc` files use `prefix=${pcfiledir}/../..` so
        # pkg-config emits paths relative to the on-disk .pc location.
        pkg_config_paths = []
        python_pc_dir = self.cross_venv.host_python_home / "lib" / "pkgconfig"
        if python_pc_dir.is_dir():
            pkg_config_paths.append(str(python_pc_dir))
        pc_dir = install_root / "lib" / "pkgconfig"
        if pc_dir.is_dir():
            pkg_config_paths.append(str(pc_dir))
        if self.cross_venv.venv_path.is_dir():
            py_short = f"python3.{sys.version_info.minor}"
            for env_root in ("build", "cross"):
                site_dir = (
                    self.cross_venv.venv_path
                    / env_root
                    / "lib"
                    / py_short
                    / "site-packages"
                )
                if site_dir.is_dir():
                    # Wheels bundle their .pc files in assorted spots under
                    # site-packages: pybind11 -> <pkg>/share/pkgconfig, while
                    # numpy ships numpy/_core/lib/pkgconfig/numpy.pc. Search the
                    # known locations so meson's pkg-config method resolves them.
                    for pattern in (
                        "*/share/pkgconfig",
                        "*/lib/pkgconfig",
                        "*/_core/lib/pkgconfig",
                    ):
                        for wheel_pc in site_dir.glob(pattern):
                            if wheel_pc.is_dir():
                                pkg_config_paths.append(str(wheel_pc))
        pkg_config_path = ":".join(pkg_config_paths)

        env = {
            "AR": ar,
            "CC": cc,
            "CXX": cxx,
            "STRIP": strip,
            "RANLIB": ranlib,
            "CFLAGS": cflags,
            "CPPFLAGS": cppflags,
            "LDFLAGS": ldflags,
            "PKG_CONFIG_PATH": pkg_config_path,
            # PKG_CONFIG_LIBDIR overrides pkg-config's *default* search list
            # (typically /opt/homebrew/lib/pkgconfig + /usr/lib/pkgconfig on
            # macOS, /usr/lib/pkgconfig on Linux). Without it, recipes like
            # Pillow that scan via pkg-config will happily resolve libtiff /
            # liblcms2 / libpng to the build host's macOS dylibs and try to
            # link them into iOS .so files -- the linker then aborts with
            # "ld: building for 'iOS', but linking in dylib (...) built for
            # 'macOS'". Point LIBDIR at the same support-tree-only paths
            # PKG_CONFIG_PATH already enumerates so pkg-config can't even
            # see Homebrew's pkgconfig dir.
            "PKG_CONFIG_LIBDIR": pkg_config_path,
            "CROSS_VENV_SDK": self.cross_venv.sdk,
            "CARGO_BUILD_TARGET": cargo_build_target,
            "CARGO_TARGET_{}_LINKER".format(
                cargo_build_target.replace("-", "_").upper()
            ): cc,
            "CARGO_TARGET_{}_RUSTFLAGS".format(
                cargo_build_target.replace("-", "_").upper()
            ): cargo_ldflags,
            "PYO3_CROSS_PYTHON_VERSION": self.cross_venv.sysconfig_data[
                "py_version_short"
            ],
            # pyo3 expects a directory containing _sysconfigdata__*.py.
            # Newer Apple support layouts place this outside prefix/lib.
            "PYO3_CROSS_LIB_DIR": str(
                (
                    self.cross_venv.host_sysconfig.parent
                    if self.cross_venv.host_sysconfig is not None
                    else Path(self.cross_venv.sysconfig_data["prefix"]) / "lib"
                )
            ),
            # The on-disk python install directory for the target SDK /
            # arch inside the mobile-forge support tree
            # (`MOBILE_FORGE_<SDK>_SUPPORT_PATH/install/<sdk>/<arch>/python-<X.Y.Z>`
            # on Android, the matching Python.xcframework slice on
            # iOS). Always a real directory on disk -- useful when a
            # recipe needs to locate sibling artifacts shipped alongside
            # Python in the support tree, or to pin Python_LIBRARY /
            # Python_INCLUDE_DIR against a path that doesn't move with
            # crossenv relocation across python-build versions.
            "HOST_PYTHON_HOME": str(self.cross_venv.host_python_home),
            # The host-runnable Python interpreter provided by crossenv: a
            # wrapper script that runs the build-machine Python but reports
            # the *target* sysconfig. Use this for CMake's -DPython_EXECUTABLE
            # (FindPython's Interpreter component). Pointing at
            # {prefix}/bin/python (the cross-compiled target binary) makes
            # FindPython try to exec a non-host binary; it fails and drops the
            # Interpreter + Development.Module + Development.Embed components.
            "CROSS_VENV_PYTHON": str(
                self.cross_venv.venv_path
                / "cross"
                / "bin"
                / f"python{self.cross_venv.sysconfig_data['py_version_short']}"
            ),
        }
        env.update(kwargs)

        if self.cross_venv.sdk == "android":
            cc_parts = cc.split("/")
            env["NDK_ROOT"] = "/".join(cc_parts[: cc_parts.index("toolchains")])
            env["NDK_SYSROOT"] = str(
                ndk_sysroot or (Path(cc).parent.parent / "sysroot")
            )
            env["ANDROID_ABI"] = self.cross_venv.arch
            env["ANDROID_API_LEVEL"] = str(self.cross_venv.sdk_version)
            env["HOST_TRIPLET"] = self.cross_venv.platform_triplet

        script_vars = {
            **env,
            **self.cross_venv.scheme_paths,
            **self.cross_venv.sysconfig_data,
            "sysconfigdata_name": self.cross_venv.sysconfigdata_name,
        }

        # Set up any additional environment variables needed in the script environment.
        for key, value in self.package.meta["build"]["script_env"].items():
            if key in ["LDFLAGS", "CFLAGS", "CPPFLAGS"]:
                env[key] += " " + str(value).format(**script_vars)
            else:
                env[key] = str(value).format(**script_vars)

        # Add in some user environment keys that are useful
        for key in [
            "TMPDIR",
            "USER",
            "HOME",
            "LANG",
            "TERM",
        ]:
            try:
                env[key] = os.environ[key]
            except KeyError:
                # User's environment doesn't provide the key.
                pass

        return env

    def build(self, clean):
        # If there's an error log file, remove it.
        # The log file will be overwritten by being re-opened.
        if self.error_log_file_path.exists():
            self.error_log_file_path.unlink()

        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file_path.open("w", encoding="utf-8") as self.log_file:
            log(self.log_file, "=" * 80)
            log(self.log_file, f"Building {self.package} for {self.cross_venv.tag}")
            log(self.log_file, "=" * 80)

            # Surface a recipe's build.before_all (host build-tool setup) locally.
            # This is skipped on CI, where they get installed on the ephemeral runner.
            before_all = (self.package.meta.get("build") or {}).get("before_all")
            if before_all and not os.environ.get("GITHUB_ACTIONS"):
                cmds = [before_all] if isinstance(before_all, str) else before_all
                log(
                    self.log_file,
                    "NOTE: this recipe needs host build tools set up first",
                )
                log(
                    self.log_file,
                    "      (forge does not run these — run them yourself):",
                )
                for c in cmds:
                    log(self.log_file, f"      $ {c}")
                log(self.log_file, "-" * 80)

            try:
                self.prepare(clean=clean)
                self._build()
                success = True
            except Exception:
                log(self.log_file, "*" * 80)
                log(
                    self.log_file,
                    f"Failed build: {self.package} for {self.cross_venv.sdk} "
                    f"{self.cross_venv.sdk_version} on {self.cross_venv.arch}",
                )
                log(self.log_file, "*" * 80)
                log_exception(self.log_file)

                success = False

        # If the build failed, move the log file to the error location.
        if not success:
            self.error_log_file_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(self.log_file_path, self.error_log_file_path)

        return success

    @abstractmethod
    def _build(self):
        """Build the package."""
        ...

    def read_message_file(self, filename: Path):
        return parser.Parser().parse(filename.open("r"))

    def write_message_file(self, filename: Path, data):
        msg = message.Message()
        for key, value in data.items():
            msg[key] = value

        # I don't know whether maxheaderlen is required, but it's used by bdist_wheel.
        with filename.open("w", encoding="utf-8") as f:
            generator.Generator(f, maxheaderlen=0).flatten(msg)

    @property
    def wheel_tag(self) -> str:
        return f"py3-none-{self.cross_venv.tag}"

    def _rewrite_absolute_needed(self, so_path: Path):
        # Some libraries (notably libpython built without DT_SONAME) end up
        # recorded in DT_NEEDED by their absolute build-host path when linked
        # via CMake's absolute-path style. That path won't exist on the
        # target device. Shift each DT_NEEDED d_val past the last '/' in the
        # existing string — no string rewriting needed because the basename
        # already lives at the suffix of the absolute path.
        with open(so_path, "r+b") as f:
            if f.read(4) != b"\x7fELF":
                return
            ei_class = struct.unpack("B", f.read(1))[0]
            if ei_class == 1:
                # ELF32: 4-byte fields, 8-byte dyn entries, 40-byte sections.
                shoff_pos, shoff_fmt = 32, "<I"
                shnum_pos = 46
                sh_addr_off, sh_off_off, sh_size_off = 12, 16, 20
                dyn_entry_size, dyn_fmt = 8, "<iI"
                word_fmt = "<I"
            elif ei_class == 2:
                # ELF64: 8-byte fields, 16-byte dyn entries, 64-byte sections.
                shoff_pos, shoff_fmt = 40, "<Q"
                shnum_pos = 58
                sh_addr_off, sh_off_off, sh_size_off = 16, 24, 32
                dyn_entry_size, dyn_fmt = 16, "<qQ"
                word_fmt = "<Q"
            else:
                return

            word_size = struct.calcsize(word_fmt)
            f.seek(shoff_pos)
            e_shoff = struct.unpack(shoff_fmt, f.read(word_size))[0]
            f.seek(shnum_pos)
            e_shentsize, e_shnum = struct.unpack("<HH", f.read(4))

            sections = []
            dyn_offset = dyn_size = 0
            for i in range(e_shnum):
                f.seek(e_shoff + i * e_shentsize)
                sh = f.read(e_shentsize)
                sh_type = struct.unpack_from("<I", sh, 4)[0]
                sh_addr = struct.unpack_from(word_fmt, sh, sh_addr_off)[0]
                sh_offset = struct.unpack_from(word_fmt, sh, sh_off_off)[0]
                sections.append((sh_type, sh_addr, sh_offset))
                if sh_type == 6:  # SHT_DYNAMIC
                    dyn_offset = sh_offset
                    dyn_size = struct.unpack_from(word_fmt, sh, sh_size_off)[0]

            if not dyn_offset:
                return

            strtab_addr = 0
            needed_entries = []
            for i in range(dyn_size // dyn_entry_size):
                f.seek(dyn_offset + i * dyn_entry_size)
                d_tag, d_val = struct.unpack(dyn_fmt, f.read(dyn_entry_size))
                if d_tag == 0:  # DT_NULL
                    break
                if d_tag == 5:  # DT_STRTAB
                    strtab_addr = d_val
                elif d_tag == 1:  # DT_NEEDED
                    needed_entries.append(
                        (dyn_offset + i * dyn_entry_size + word_size, d_val)
                    )

            dynstr_offset = 0
            for sh_type, sh_addr, sh_offset in sections:
                if sh_type == 3 and sh_addr == strtab_addr:  # SHT_STRTAB
                    dynstr_offset = sh_offset
                    break

            if not dynstr_offset:
                return

            for entry_offset, d_val in needed_entries:
                f.seek(dynstr_offset + d_val)
                chunk = f.read(4096)
                end = chunk.find(b"\x00")
                if end < 0:
                    continue
                name = chunk[:end]
                slash = name.rfind(b"/")
                if slash < 0:
                    continue
                f.seek(entry_offset)
                f.write(struct.pack(word_fmt, d_val + slash + 1))
                log(
                    self.log_file,
                    f"[{self.cross_venv}] {so_path.name}: NEEDED "
                    f"'{name.decode(errors='replace')}' -> "
                    f"'{name[slash + 1 :].decode(errors='replace')}'",
                )

    def _check_elf_alignment(self, so_path: Path):
        """Verify that all PT_LOAD segments are 16KB-aligned."""
        MIN_ALIGNMENT = 16384
        with open(so_path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x7fELF":
                return
            ei_class = struct.unpack("B", f.read(1))[0]
            if ei_class != 2:  # skip 32-bit ELFs
                return

            # Read e_phoff, e_phentsize, e_phnum from ELF64 header
            f.seek(32)
            e_phoff = struct.unpack("<Q", f.read(8))[0]
            f.seek(54)
            e_phentsize, e_phnum = struct.unpack("<HH", f.read(4))

            for i in range(e_phnum):
                f.seek(e_phoff + i * e_phentsize)
                p_type = struct.unpack("<I", f.read(4))[0]
                if p_type != 1:  # PT_LOAD
                    continue
                f.seek(e_phoff + i * e_phentsize + 48)
                p_align = struct.unpack("<Q", f.read(8))[0]

                if p_align < MIN_ALIGNMENT:
                    raise RuntimeError(
                        f"{so_path.name}: PT_LOAD alignment is {p_align}, "
                        f"expected >= {MIN_ALIGNMENT}. "
                        f"Library is not 16KB page-aligned."
                    )
        log(self.log_file, f"[{self.cross_venv}] {so_path.name}: 16KB alignment OK")

    def _bundle_to_dylib(self, so_path: Path) -> bool:
        """Convert a thin `MH_BUNDLE` Mach-O extension to `MH_DYLIB` in place.

        Injects an `LC_ID_DYLIB` load command into the header's free padding and
        flips the filetype byte. Returns True if a conversion was made, False if
        the file is not a thin little-endian `MH_BUNDLE` (already a dylib, a fat
        binary, or not Mach-O — all left untouched). The caller must re-sign
        (`codesign --force --sign -`) afterwards, since the edit invalidates the
        linker's ad-hoc signature.
        """
        MH_MAGIC_64 = 0xFEEDFACF
        MH_BUNDLE = 0x8
        MH_DYLIB = 0x6
        LC_ID_DYLIB = 0xD
        LC_SEGMENT_64 = 0x19

        data = bytearray(so_path.read_bytes())
        if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != MH_MAGIC_64:
            return False  # not a thin 64-bit LE Mach-O (fat/other -> leave alone)
        (_magic, _cpu, _sub, filetype, ncmds, sizeofcmds, flags, _res) = (
            struct.unpack_from("<IiiIIIII", data, 0)
        )
        if filetype != MH_BUNDLE:
            return False  # already MH_DYLIB (LDSHARED-honoring backends) or other

        # Bound the free header space by the lowest section file offset in __TEXT
        # (its data follows the load commands; we must not overwrite it).
        lc_end = 32 + sizeofcmds
        min_fileoff = len(data)
        off = 32
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from("<II", data, off)
            if (
                cmd == LC_SEGMENT_64
                and data[off + 8 : off + 24].split(b"\0")[0] == b"__TEXT"
            ):
                nsects = struct.unpack_from("<I", data, off + 8 + 16 + 8 * 4)[0]
                soff = off + 72  # section_64 records follow the 72-byte segment cmd
                for _s in range(nsects):
                    sect_fileoff = struct.unpack_from("<I", data, soff + 48)[0]
                    if sect_fileoff and sect_fileoff < min_fileoff:
                        min_fileoff = sect_fileoff
                    soff += 80
            off += cmdsize

        name = b"@rpath/" + so_path.name.encode()
        raw = name + b"\0"
        raw += b"\0" * ((-len(raw)) % 8)
        cmdsize_new = 24 + len(raw)  # dylib_command header (24) + padded name
        if (min_fileoff - lc_end) < cmdsize_new:
            raise RuntimeError(
                f"{so_path.name}: not enough Mach-O header padding to inject "
                f"LC_ID_DYLIB ({min_fileoff - lc_end} < {cmdsize_new}); cannot "
                f"convert MH_BUNDLE -> MH_DYLIB in place."
            )

        # dylib_command: cmd, cmdsize, name.offset(24), timestamp, cur_ver, compat_ver
        idcmd = (
            struct.pack("<IIIIII", LC_ID_DYLIB, cmdsize_new, 24, 0, 0x10000, 0x10000)
            + raw
        )
        data[lc_end : lc_end + cmdsize_new] = idcmd
        struct.pack_into(
            "<IIII", data, 12, MH_DYLIB, ncmds + 1, sizeofcmds + cmdsize_new, flags
        )
        so_path.write_bytes(data)
        return True

    def fix_wheel(self, wheel_dir: Path):

        log(self.log_file, f"[{self.cross_venv}] Fixing wheel contents")

        # Normalize wheel tags to forge platform tags so repacked wheels use
        # android_24_arm64_v8a / ios_13_0_arm64_iphoneos style platform tags.
        wheel_metadata_path = next(wheel_dir.glob("*.dist-info")) / "WHEEL"
        wheel_metadata = self.read_message_file(wheel_metadata_path)
        if "Tag" in wheel_metadata:
            del wheel_metadata["Tag"]
        wheel_metadata["Tag"] = self.wheel_tag
        self.write_message_file(wheel_metadata_path, wheel_metadata)

        if self.cross_venv.sdk == "android":
            env = self.compile_env()

            # Drop foreign-arch extension modules that leaked into this wheel.
            # setuptools' in-place `build_ext` writes NAME.cpython-<ver>-<triplet>.so
            # into the (reused) unpacked-sdist source tree; when forge builds each
            # ABI from that same tree, a prior slice's arch-tagged .so lingers and
            # bdist_wheel globs it into the next slice's wheel (pymongo: the x86_64
            # wheel carried the arm64 `_cbson`/`_cmessage` byte-for-byte). Downstream
            # serious_python strips the arch off the SOABI tag when writing `.soref`
            # markers, so two arches collide on one `<name>.soref` and Gradle fails
            # with "duplicate entry". A per-arch wheel must be arch-pure — keep only
            # this target's platform triplet.
            keep_triplet = self.cross_venv.platform_triplet
            foreign_triplets = "|".join(
                re.escape(triplet)
                for triplet in self.cross_venv.ANDROID_PLATFORM_TRIPLET.values()
                if triplet != keep_triplet
            )
            foreign_ext_re = re.compile(rf"\.cpython-\d+-(?:{foreign_triplets})\.so$")
            for so in wheel_dir.glob("**/*.so"):
                if foreign_ext_re.search(so.name):
                    log(
                        self.log_file,
                        f"[{self.cross_venv}] Dropping foreign-arch extension "
                        f"{so.name}",
                    )
                    so.unlink()

            # ABI-tag bare CPython extension modules so serious_python's Android
            # packaging recognizes them. That packaging only relocates a native
            # module into jniLibs and writes the `.soref` marker its on-device
            # importer resolves for extensions whose filename carries a CPython
            # ABI tag (`*.cpython-*.so` / `*.abi3.so`); a bare `NAME.so` is
            # treated as a plain dependency library, gets no `.soref`, and so
            # fails to import on-device (ModuleNotFoundError). CMake / SWIG /
            # Cython / nanobind builds routinely emit un-tagged extensions
            # (ncnn, faiss, coolprop, ...) because they can't derive the target
            # SOABI when cross-compiling. Rename ONLY genuine extension modules —
            # those exporting `PyInit_<basename>` — so real dependency
            # libraries bundled alongside them are left untouched.
            ext_tag_re = re.compile(r"\.(cpython-[^/]+|abi3)\.so$")
            ext_suffix = f".cpython-3{sys.version_info.minor}.so"
            nm = Path(env["STRIP"]).with_name("llvm-nm")
            for so in wheel_dir.glob("**/*.so"):
                if ext_tag_re.search(so.name):
                    continue  # already ABI-tagged
                module = so.name[: -len(".so")]
                try:
                    symbols = subprocess.check_output(
                        [str(nm), "-D", "--defined-only", str(so)], text=True
                    )
                except (subprocess.CalledProcessError, OSError):
                    continue  # not an analyzable ELF; leave it alone
                # Match `PyInit_<module>`, tolerating a symbol-version suffix.
                # A build applying a linker version script exports the init
                # symbol versioned (onnxruntime: `PyInit_..._state@@VERS_1.0`),
                # which an exact-equality check would miss — leaving the module
                # bare, unrecognized by serious_python, and unimportable on-device.
                pyinit = f"PyInit_{module}"
                if any(
                    tok == pyinit or tok.startswith(pyinit + "@")
                    for tok in symbols.split()
                ):
                    tagged = so.with_name(module + ext_suffix)
                    log(
                        self.log_file,
                        f"[{self.cross_venv}] ABI-tagging extension "
                        f"{so.name} -> {tagged.name}",
                    )
                    so.rename(tagged)

            for so in wheel_dir.glob("**/*.so"):
                log(self.log_file, f"[{self.cross_venv}] Stripping {so}")
                self.cross_venv.run(
                    self.log_file,
                    [env["STRIP"], "--strip-unneeded", str(so)],
                )

            # Rewrite any absolute-path DT_NEEDED entries to their basename
            # (e.g. libpython linked by absolute path under CMake builds).
            for so in wheel_dir.glob("**/*.so"):
                self._rewrite_absolute_needed(so)

            # Verify 16KB page alignment (required by Google Play)
            for so in wheel_dir.glob("**/*.so"):
                self._check_elf_alignment(so)

        elif self.cross_venv.host_os == "iOS":
            # Convert MH_BUNDLE Python extensions to MH_DYLIB so serious_python's
            # darwin packaging can frameworkize AND link them. iOS CPython's
            # sysconfig sets LDSHARED='...-dynamiclib -F . -framework Python', which
            # setuptools/Cython/meson/maturin honor (-> MH_DYLIB); but CMake /
            # scikit-build recipes (opencv, ncnn, coolprop, faiss, ...) link a
            # Python MODULE with Apple's default -bundle (-> MH_BUNDLE), ignoring
            # LDSHARED. serious_python turns every site-packages .so into a
            # `.framework` binary that SwiftPM LINKS (a Package.swift binaryTarget
            # the plugin target depends on), and `ld` rejects a bundle with
            # "Unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB can be
            # linked)". Injecting an LC_ID_DYLIB and flipping the header filetype
            # makes the extension a linkable dylib; dlopen (the import path) works
            # on both filetypes, so nothing downstream regresses. serious_python's
            # own `install_name_tool -id` then overwrites the placeholder id.
            for so in wheel_dir.glob("**/*.so"):
                if self._bundle_to_dylib(so):
                    log(
                        self.log_file,
                        f"[{self.cross_venv}] MH_BUNDLE -> MH_DYLIB: {so.name}",
                    )
                    # The header edit invalidates the linker's ad-hoc signature;
                    # re-sign ad-hoc so dyld/codesign accept the dylib.
                    self.cross_venv.run(
                        self.log_file,
                        ["codesign", "--force", "--sign", "-", str(so)],
                    )

        # Normalize a dotted distribution name (e.g. "zope.interface" -> "zope-interface")
        # to its PEP 503 canonical form in the wheel METADATA. pypi.flet.dev (Gemfury)
        # returns 409 "version already exists" for every wheel after the first when the
        # METADATA Name contains dots, so a dotted-name package could otherwise only ever
        # publish ONE platform wheel per version. We rewrite just the `Name:` header (a
        # targeted text edit that preserves the rest of METADATA, including the
        # long-description body that the message round-trip below would drop); the wheel
        # filename, .dist-info dir and import name are already dot-free, and pip treats the
        # dotted and normalized names as equivalent so dependents resolve transparently.
        metadata_path = next(wheel_dir.glob("*.dist-info")) / "METADATA"
        metadata_text = metadata_path.read_text(encoding="utf-8")
        name_match = re.search(r"(?m)^Name:[ \t]*(.+?)[ \t]*$", metadata_text)
        if name_match and "." in name_match[1]:
            normalized = canonicalize_name(name_match[1])
            log(
                self.log_file,
                f"[{self.cross_venv}] Normalizing dotted dist name "
                f"{name_match[1]!r} -> {normalized!r} in METADATA",
            )
            metadata_path.write_text(
                metadata_text[: name_match.start()]
                + f"Name: {normalized}"
                + metadata_text[name_match.end() :],
                encoding="utf-8",
            )

        # add missing requirements from "host"
        if len(self.package.meta["requirements"]["host"]):
            metadata_path = next(wheel_dir.glob("*.dist-info")) / "METADATA"
            metadata = self.read_message_file(metadata_path)
            for req in self.package.meta["requirements"]["host"]:
                if req.startswith("flet-"):
                    log(
                        self.log_file,
                        f"[{self.cross_venv}] Adding {req} requirement to METADATA",
                    )
                    parts = req.split(" ", 1)
                    req_name = parts[0]
                    if len(parts) > 1:
                        req_ver = parts[1]
                        if req_ver[0].isdigit():
                            req_ver = f"=={req_ver}"
                        metadata["Requires-Dist"] = f"{req_name} ({req_ver})"
                    else:
                        metadata["Requires-Dist"] = req_name
            self.write_message_file(metadata_path, metadata)


class SimplePackageBuilder(Builder):
    """A builder for projects that have a build.sh entry point."""

    @property
    def source_archive_path(self) -> Path:
        url = self.download_source_url()
        filename = url.split("/")[-1]
        return Path.cwd() / "downloads" / filename

    @property
    def build_path(self) -> Path:
        # Generate a separate build path for each platform, since we can't guarantee
        # that the Makefile will do a truly clean build for each platform.
        # The path can be independent of the Python version, because it's not built
        # against the Python ABI.
        return (
            Path.cwd()
            / "build"
            / "any"
            / self.package.name
            / self.package.version
            / self.cross_venv.tag
        )

    @property
    def log_file_path(self) -> Path:
        return (
            Path.cwd()
            / "logs"
            / f"{self.package.name}-{self.package.version}-{self.cross_venv.tag}.log"
        )

    def download_source_url(self):
        return self.package.meta["source"]["url"].format(
            version=self.package.meta["package"]["version"],
            build=self.package.meta["build"]["number"],
            sdk=self.cross_venv.sdk,
            arch=self.cross_venv.arch,
        )

    def prepare(self, clean=True):
        # Always clean a non-Python build.
        super().prepare(clean=True)

        log(self.log_file, f"\n[{self.cross_venv}] Installing wheel-building tools")
        self.cross_venv.pip_install(self.log_file, ["wheel"], build=True)

    def make_wheel(self):
        build_num = str(self.package.meta["build"]["number"])
        name = canonicalize_name(self.package.name)
        version = canonicalize_version(self.package.version, strip_trailing_zero=False)
        info_path = (
            self.build_path / "wheel" / f"{name.replace('-', '_')}-{version}.dist-info"
        )

        log(self.log_file, f"\n[{self.cross_venv}] Writing wheel metadata")
        info_path.mkdir(exist_ok=True)

        # Write the packaging metadata
        self.write_message_file(
            info_path / "WHEEL",
            {
                "Wheel-Version": "1.0",
                "Root-Is-Purelib": "false",
                "Generator": "mobile-forge",
                "Build": build_num,
                "Tag": self.wheel_tag,
            },
        )
        self.write_message_file(
            info_path / "METADATA",
            {
                "Metadata-Version": "1.2",
                "Name": self.package.name,
                "Version": self.package.version,
                "Summary": "",  # Compulsory according to PEP 345,
                "Download-URL": "",
            },
        )

        # fix wheel before packaging
        self.fix_wheel(self.build_path / "wheel")

        # Re-pack the wheel file
        log(self.log_file, f"\n[{self.cross_venv}] Packing wheel")
        dist_dir = Path.cwd() / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        self.cross_venv.run(
            self.log_file,
            [
                "build-python",
                "-m",
                "wheel",
                "pack",
                str(self.build_path / "wheel"),
                "--dest-dir",
                str(dist_dir),
                "--build-number",
                str(build_num),
            ],
        )

    def compile(self):
        self.cross_venv.run(
            self.log_file,
            [
                str(self.package.recipe_path / "build.sh"),
            ],
            cwd=self.build_path,
            env=self.compile_env(
                **{
                    "HOST_TRIPLET": self.cross_venv.platform_triplet,
                    "HOST_ARCH": self.cross_venv.arch,
                    "SDK": self.cross_venv.sdk,
                    "SDK_VERSION": self.cross_venv.sdk_version,
                    "SDK_ROOT": (
                        str(self.cross_venv.sdk_root)
                        if self.cross_venv.sdk != "android"
                        else ""
                    ),
                    "BUILD_TRIPLET": f"{os.uname().machine}-apple-darwin",
                    "CPU_COUNT": str(multiprocessing.cpu_count()),
                    "PREFIX": str(self.build_path / "wheel" / "opt"),
                    "PYTHON_PREFIX": self.cross_venv.sysconfig_data["prefix"],
                    "PLATLIB": self.cross_venv.scheme_paths["platlib"],
                }
            ),
        )

    def _build(self):
        self.compile()
        self.make_wheel()


class CMakePackageBuilder(SimplePackageBuilder):
    """A builder for cmake-based projects."""

    def _build(self):
        pass


class PythonPackageBuilder(Builder):
    """A builder for projects available on PyPI."""

    @property
    def source_archive_path(self) -> Path:
        return (
            Path.cwd()
            / "downloads"
            / f"{self.package.name}-{self.package.version}.tar.gz"
        )

    @property
    def build_path(self) -> Path:
        # Generate a separate build path for each Python version to ensure we have a
        # clean build. SDK versions can co-exist because wheel builds are cleanly
        # separated.
        return (
            Path.cwd()
            / "build"
            / f"cp3{sys.version_info.minor}"
            / self.package.name
            / self.package.version
        )

    @property
    def log_file_path(self) -> Path:
        return (
            Path.cwd()
            / "logs"
            / f"{self.package.name}-{self.package.version}-cp3{sys.version_info.minor}-{self.cross_venv.tag}.log"
        )

    @property
    def wheel_tag(self) -> str:
        py_tag = f"cp3{sys.version_info.minor}"
        return f"{py_tag}-{py_tag}-{self.cross_venv.tag}"

    def download_source_url(self):
        # Honor an explicit source.url (e.g. a GitHub tag archive) for Python
        # packages that publish no PyPI sdist (wheels-only, like pyzbar);
        # otherwise resolve the sdist from PyPI.
        source = self.package.meta.get("source")
        if isinstance(source, dict) and "url" in source:
            return source["url"].format(
                version=self.package.meta["package"]["version"],
                build=self.package.meta["build"]["number"],
                sdk=self.cross_venv.sdk,
                arch=self.cross_venv.arch,
            )
        return get_pypi_source_urls(self.package.name)[self.package.version]

    def prepare(self, clean=True):
        super().prepare(clean=clean)

        # Install any build requirements (PEP517 or otherwise)
        if (self.build_path / "pyproject.toml").is_file():
            log(
                self.log_file,
                f"\n[{self.cross_venv}] Install pyproject.toml build requirements",
            )

            # Install the requirements from pyproject.toml
            with (self.build_path / "pyproject.toml").open("rb") as f:
                pyproject = tomllib.load(f)

                # Install the build requirements in the cross environment
                # self.cross_venv.pip_install(
                #     self.log_file,
                #     ["build", "wheel"] + pyproject["build-system"]["requires"],
                #     paths=[Path.cwd() / "dist"],
                # )

                # Install the build requirements in the build environment
                self.cross_venv.pip_install(
                    self.log_file,
                    ["build", "wheel"]
                    + (
                        pyproject["build-system"]["requires"]
                        if "build-system" in pyproject
                        else []
                    ),
                    paths=[Path.cwd() / "dist"],
                    build=True,
                )
        else:
            log(
                self.log_file,
                f"\n[{self.cross_venv}] Installing non-PEP517 build requirements",
            )
            # Ensure the cross environment has the most recent tools
            self.cross_venv.pip_install(self.log_file, ["setuptools"], update=True)
            self.cross_venv.pip_install(self.log_file, ["build", "wheel"])

            # Ensure the build environment has the most recent tools
            self.cross_venv.pip_install(
                self.log_file, ["setuptools"], update=True, build=True
            )
            self.cross_venv.pip_install(self.log_file, ["build", "wheel"], build=True)

    def _create_meson_cross(self, env: dict[str, str]):
        cpu_family = {
            "arm64-v8a": "aarch64",
            "arm64": "aarch64",
            "armeabi-v7a": "arm",
            "x86_64": "x86_64",
            "x86": "x86",
        }[self.cross_venv.arch]
        cpu = {
            "arm64-v8a": "aarch64",
            "arm64": "aarch64",
            "armeabi-v7a": "armv7",
            "x86_64": "x86_64",
            "x86": "i686",
        }[self.cross_venv.arch]

        master_meson_config = {
            "binaries": {
                "c": env["CC"],
                "cpp": env["CXX"],
                "ar": env["AR"],
                "strip": env["STRIP"],
                "python": str(
                    self.cross_venv.venv_path
                    / "cross"
                    / "bin"
                    / f"python3.{sys.version_info.minor}"
                ),
                # Declare pkg-config explicitly. Meson cross-compile mode otherwise treats
                # pkg-config as a build-machine-only tool and refuses to use it for target dep
                # resolution -- even when it's installed and on PATH. Without this declaration
                # meson reports "Found pkg-config: NO" regardless, defeats `py.dependency()` via
                # pkg-config, and falls through to the sysconfig path that 3.14 doesn't tolerate the
                # autoconf-baked `/usr/local` paths in. With it declared, meson invokes
                # pkg-config + honors PKG_CONFIG_PATH (set in compile_env() above), reads the
                # relocated `.pc` file, and emits the consumer-correct -I/-L flags.
                "pkg-config": "pkg-config",
            },
            "built-in options": {
                "c_args": env["CFLAGS"],
                "cpp_args": env["CPPFLAGS"],
                # iOS: append `-framework Python` to the meson c/cpp link args (not LDFLAGS env) so
                # meson recipes (numpy, contourpy with pybind11, …) resolve the Python C API at link time
                # without breaking autoconf-based builds whose hello.c probe also reads $LDFLAGS.
                # See compile_env() in this file for the matching half of this split.
                "c_links_args": (
                    env["LDFLAGS"]
                    + (" -framework Python" if self.cross_venv.host_os == "iOS" else "")
                ),
                "cpp_links_args": (
                    env["LDFLAGS"]
                    + (" -framework Python" if self.cross_venv.host_os == "iOS" else "")
                ),
            },
            "properties": {"needs_exe_wrapper": False},
            "host_machine": {
                "cpu_family": cpu_family,
                "cpu": cpu,
                "endian": "little",
                "system": self.cross_venv.sdk,
            },
        }

        package_meson_config = (
            self.package.meta["build"]["meson"]
            if "build" in self.package.meta and "meson" in self.package.meta["build"]
            else {}
        )

        meson_config = merge_dicts(master_meson_config, package_meson_config)

        meson_cross = str(self.build_path / "meson.cross")
        with open(meson_cross, "w") as m:
            for section in meson_config.keys():
                m.write(f"[{section}]\n")
                for k, v in meson_config[section].items():
                    m.write(
                        "{} = {}\n".format(
                            k, f"'{v}'" if isinstance(v, str) else str(v).lower()
                        )
                    )
        return meson_cross

    def _build(self):
        env = self.compile_env()

        # Set the cross host platform in the environment
        env["_PYTHON_HOST_PLATFORM"] = self.cross_venv._tag_identifier(
            self.cross_venv.sdk, self.cross_venv.sdk_version, self.cross_venv.arch
        )

        meson_cross_file = self._create_meson_cross(env)

        # final environment
        env.update(
            {
                "PACKAGE_BUILD_PATH": str(self.build_path),
                "MESON_CROSS_FILE": meson_cross_file,
            }
        )

        backend_args = (
            [
                arg.format(**self.cross_venv.scheme_paths, **env)
                for arg in self.package.meta["build"]["backend-args"]
            ]
            if "build" in self.package.meta
            and "backend-args" in self.package.meta["build"]
            else []
        )

        # build wheel to a temp dir
        tmp_dist = self.build_path / "tmp_dist"
        if tmp_dist.exists():
            shutil.rmtree(tmp_dist)
        tmp_dist.mkdir(parents=True, exist_ok=True)

        self.cross_venv.run(
            self.log_file,
            [
                "python",
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--outdir",
                str(tmp_dist),
            ]
            + backend_args,
            cwd=self.build_path,
            env=env,
        )
        tmp_wheel = next(tmp_dist.glob("*.whl"))

        # unpack wheel to a temp directory
        tmp_wheel_dir = self.build_path / "tmp_wheel"
        if tmp_wheel_dir.exists():
            shutil.rmtree(tmp_wheel_dir)
        tmp_wheel_dir.mkdir(parents=True, exist_ok=True)

        log(self.log_file, f"\n[{self.cross_venv}] Unpacking wheel to temp directory")
        self.cross_venv.run(
            self.log_file,
            [
                "build-python",
                "-m",
                "wheel",
                "unpack",
                "--dest",
                str(tmp_wheel_dir),
                str(tmp_wheel),
            ],
        )

        tmp_wheel_dir = next(tmp_wheel_dir.iterdir())

        # fix wheel
        self.fix_wheel(tmp_wheel_dir)

        # re-pack the wheel to "dist"
        log(self.log_file, f"\n[{self.cross_venv}] Packing wheel to dist")
        dist_dir = Path.cwd() / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        pack_args = [
            "build-python",
            "-m",
            "wheel",
            "pack",
            str(tmp_wheel_dir),
            "--dest-dir",
            str(dist_dir),
        ]
        if self.package.meta["build"]["number"]:
            pack_args.extend(
                ["--build-number", str(self.package.meta["build"]["number"])]
            )
        self.cross_venv.run(
            self.log_file,
            pack_args,
        )
