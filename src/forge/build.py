from __future__ import annotations

import multiprocessing
import os
import re
import shutil
import sys
import tarfile
import zipfile
from abc import ABC, abstractmethod, abstractproperty
from email import generator, message
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

    @abstractproperty
    def build_path(self) -> Path:
        """The path in which all environment and sources for the build will be
        created."""
        ...

    @abstractproperty
    def log_file_path(self) -> Path:
        """The path where build logs should be written."""
        ...

    @property
    def error_log_file_path(self) -> Path:
        """The path for the log file if a build error occurs."""
        return self.log_file_path.parent.parent / "errors" / self.log_file_path.name

    @abstractproperty
    def source_archive_path(self) -> Path:
        """The source archive file for the package."""
        ...

    def install_requirements(self, target):
        requirements = []
        for requirement in self.package.meta["requirements"][target]:
            try:
                package, version = requirement.split()
                if version.startswith("^"):
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

        if not self.source_archive_path.is_file():
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

        log(self.log_file, f"\n[{self.cross_venv}] Install forge build requirements")
        self.install_requirements("build")

    def compile_env(self, **kwargs) -> dict[str, str]:
        sysconfig_data = self.cross_venv.sysconfig_data
        install_root = self.cross_venv.install_root

        ar = sysconfig_data["AR"]
        cc = sysconfig_data["CC"]
        cxx = sysconfig_data["CXX"]
        strip = (
            str(Path(ar).parent.joinpath("llvm-strip"))
            if ar and self.cross_venv.sdk == "android"
            else "strip"
        )

        cflags = self.cross_venv.sysconfig_data["CFLAGS"]
        cppflags = self.cross_venv.sysconfig_data["CPPFLAGS"]

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

        ldflags = self.cross_venv.sysconfig_data["LDFLAGS"]

        # -lpython3.x
        ldflags += " -L{}/lib".format(self.cross_venv.sysconfig_data["prefix"])

        # Add install root lib
        if (install_root / "lib").is_dir():
            ldflags += f" -L{install_root}/lib"

        # cargo_ldflags = re.sub(r"-march=[\w-]+", "", ldflags)
        cargo_ldflags = " -L{}/lib".format(self.cross_venv.sysconfig_data["prefix"])
        cargo_ldflags += " -C link-arg=-undefined -C link-arg=dynamic_lookup"

        if self.cross_venv.sdk != "android":

            # Replace any hard-coded reference to -isysroot <sysroot> with the actual reference
            ldflags = re.sub(
                r"-isysroot \w+", f"-isysroot={self.cross_venv.sdk_root}", ldflags
            )

            # Add SDK root lib
            if (self.cross_venv.sdk_root / "usr" / "lib").is_dir():
                ldflags += f" -L{self.cross_venv.sdk_root}/usr/lib"

            # Add the framework path
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

        env = {
            "AR": ar,
            "CC": cc,
            "CXX": cxx,
            "STRIP": strip,
            "CFLAGS": cflags,
            "CPPFLAGS": cppflags,
            "LDFLAGS": ldflags,
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
            "PYO3_CROSS_LIB_DIR": "{}/lib".format(
                self.cross_venv.sysconfig_data["prefix"]
            ),
        }
        env.update(kwargs)

        if self.cross_venv.sdk == "android":
            cc_parts = cc.split("/")
            env["NDK_ROOT"] = "/".join(cc_parts[: cc_parts.index("toolchains")])
            env["ANDROID_ABI"] = self.cross_venv.arch

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

    def write_message_file(self, filename, data):
        msg = message.Message()
        for key, value in data.items():
            msg[key] = value

        # I don't know whether maxheaderlen is required, but it's used by bdist_wheel.
        with filename.open("w", encoding="utf-8") as f:
            generator.Generator(f, maxheaderlen=0).flatten(msg)

    def make_wheel(self):
        build_num = str(self.package.meta["build"]["number"])
        name = canonicalize_name(self.package.name)
        version = canonicalize_version(self.package.version)
        info_path = self.build_path / "wheel" / f"{name}-{version}.dist-info"

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
                "Tag": f"py3-none-{self.cross_venv.tag}",
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

        # Re-pack the wheel file
        log(self.log_file, f"\n[{self.cross_venv}] Packing wheel")
        self.cross_venv.run(
            self.log_file,
            [
                "build-python",
                "-m",
                "wheel",
                "pack",
                str(self.build_path / "wheel"),
                "--dest-dir",
                str(Path.cwd() / "dist"),
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
                    "BUILD_TRIPLET": f"{os.uname().machine}-apple-darwin",
                    "CPU_COUNT": str(multiprocessing.cpu_count()),
                    "PREFIX": str(self.build_path / "wheel" / "opt"),
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

    def download_source_url(self):
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
                    ["build", "wheel"] + pyproject["build-system"]["requires"],
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
            },
            "built-in options": {
                "c_args": env["CFLAGS"],
                "cpp_args": env["CPPFLAGS"],
                "c_links_args": env["LDFLAGS"],
                "cpp_links_args": env["LDFLAGS"],
            },
            "properties": {"needs_exe_wrapper": True},
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

        script_vars = {
            **env,
            **self.cross_venv.scheme_paths,
            **self.cross_venv.sysconfig_data,
            "sysconfigdata_name": self.cross_venv.sysconfigdata_name,
        }

        # Set up any additional environment variables needed in the script environment.
        for key, value in self.package.meta["build"]["script_env"].items():
            if key == "LDFLAGS":
                env[key] += " " + value
            else:
                env[key] = str(value).format(**script_vars)

        # Set the cross host platform in the environment
        env["_PYTHON_HOST_PLATFORM"] = self.cross_venv.platform_identifier

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

        self.cross_venv.run(
            self.log_file,
            [
                "python",
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--outdir",
                str(Path.cwd() / "dist"),
            ]
            + backend_args,
            cwd=self.build_path,
            env=env,
        )
