"""make_dep_wheels.py.

A utility script for converting the "installed" versions of dependencies into wheels
that can be referenced during forge builds.

You should not need to invoke this script directly; it should be called by `./setup-
iOS.sh` when creating a new forge environment.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def make_wheel(package, os_name, target):
    """Create a target-specific wheel for a given package.

    Requires that PYTHON_APPLE_SUPPORT is set in the environment, and that variable
    points to a completed support build.

    :param package: The name of the package to build (e.g., "BZip2")
    :param os_name: The OS name to target (e.g., "iOS")
    :param target: The target specifier (e.g., "iphoneos.arm64")
    """
    support = Path(os.environ["PYTHON_ANDROID_SUPPORT" if os_name == "android" else "PYTHON_APPLE_SUPPORT"])

    versions_file = (
        support
        / "support"
        / ".".join(sys.version.split(".")[:2])
        / os_name
        / "VERSIONS"
    )
    with versions_file.open(encoding="utf-8") as f:
        versions = f.read()

    package_version_build = re.search(rf"^{package}: (.*)", versions, re.MULTILINE)[1]
    min_version = re.search(rf"^Min {os_name} version: (.*)", versions, re.MULTILINE)[1]

    package_version, package_build = package_version_build.split("-")

    wheel_tag = f"py3-none-{os_name}_{min_version}_{target.replace('-', '_')}".lower().replace(".", "_")

    wheel_file = (
        Path("dist") / f"{package.lower()}-{package_version_build}-{wheel_tag}.whl"
    )
    if wheel_file.exists():
        print(f"{wheel_file} already exists")
        return

    install_path = (
        support
        / "install"
        / os_name
        / target
        / f"{package.lower()}-{package_version_build}"
    )
    if not install_path.exists():
        print(
            f"Cannot build {target} wheel for {package}; can't find installed version in {install_path}"
        )
        sys.exit(1)

    with tempfile.TemporaryDirectory(dir=".") as tmp:
        wheel_path = Path(tmp)
        distinfo_path = wheel_path / f"{package.lower()}-{package_version}.dist-info"
        distinfo_path.mkdir()

        # Copy the installed content.
        # TODO: Enable ignore_dangling_symlinks because of https://github.com/beeware/cpython-android-source-deps/issues/2
        shutil.copytree(install_path, wheel_path / "opt", ignore_dangling_symlinks=True)

        # Write package metadata
        with (distinfo_path / "METADATA").open("w", encoding="utf-8") as f:
            f.write(
                "\n".join(
                    [
                        "Metadata-Version: 1.2",
                        f"Name: {package.lower()}",
                        f"Version: {package_version}",
                        "Summary: ",
                        "Download-URL: ",
                    ]
                )
            )

        # Write wheel metadata
        with (distinfo_path / "WHEEL").open("w", encoding="utf-8") as f:
            f.write(
                "\n".join(
                    [
                        "Wheel-Version: 1.0",
                        "Root-Is-Purelib: false",
                        "Generator: Mobile-Forge.BeeWare",
                        f"Build: {package_build}",
                        f"Tag: {wheel_tag}",
                    ]
                )
            )

        # Ensure the dist folder exists
        Path("dist").mkdir(exist_ok=True)

        # Pack the wheel
        subprocess.run(
            [
                sys.executable,
                "-m",
                "wheel",
                "pack",
                "--dest-dir",
                "dist",
                wheel_path,
            ]
        )


if __name__ == "__main__":
    os_name = sys.argv[1]
    for target in {
        "android": [
            "arm64-v8a",
            "armeabi-v7a",
            "x86_64",
            "x86"
        ],
        "iOS": [
            "iphoneos.arm64",
            "iphonesimulator.arm64",
            "iphonesimulator.x86_64",
        ],
        "tvOS": [
            "appletvos.arm64",
            "appletvsimulator.arm64",
            "appletvsimulator.x86_64",
        ],
        "watchOS": [
            "watchos.arm64_32",
            "watchsimulator.arm64",
            "watchsimulator.x86_64",
        ],
    }[os_name]:
        for dep in ["BZip2", "XZ", "libFFI", "OpenSSL"]:
            make_wheel(dep, os_name, target)
