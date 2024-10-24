from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forge.cross import CrossVEnv
from forge.package import Package
from forge.pypi import get_pypi_versions


def main():
    parser = argparse.ArgumentParser(
        description="Build binary wheels for mobile platforms"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log more detail")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean the build folder prior to building.",
    )
    parser.add_argument(
        "--all-versions",
        action="store_true",
        help="Build all appropriate versions of each package.",
    )
    parser.add_argument(
        "-s",
        "--subset",
        choices=[
            "non-py",
            "py-any",
            "py",
            "smoke",
            "smoke-non-py",
            "smoke-py",
            "non-smoke",
            "all",
        ],
        default="all",
        help=(
            "The subset of packages to compile. One of: non-py (all non-Python "
            "packages), py-any (python packages that aren't platform dependent), "
            "py (all Python packages), smoke (only packages needed "
            "to do a support testbed check), smoke-non-py (only non-Python "
            "smoke packages), smoke-py (only Python smoke packages), non-smoke "
            "(all non-smoke packages), or all. Defaults to all."
        ),
    )

    parser.add_argument(
        "host",
        help=(
            "The host platform(s) to target. One of the top-level platform (android, "
            "iOS, tvOS, watchOS); or a platform:version:arch triple (e.g., "
            "iphonesimulator:12.0:x86_64 or android:21:arm64-v8a)."
        ),
    )
    parser.add_argument(
        "build_targets",
        nargs="*",
        default=None,
        help=(
            "Name of a package in ./recipes; or if it contains a slash, path "
            "to a recipe directory. Add ':<version>' to override the version; "
            "add '::<build>' to override the build number; add ':<version>:<build>' "
            "to override both the version and the build number."
        ),
    )

    args = parser.parse_args()

    try:
        platforms = [
            (sdk, CrossVEnv.BASE_VERSION[args.host], arch)
            for sdk, arch in CrossVEnv.HOST_SDKS[args.host]
        ]
    except KeyError:
        parts = args.host.split(":")
        if len(parts) == 2:
            # Derive the base version from the provided SDK
            OS_MAP = {
                platform[0]: os_name
                for os_name, platforms in CrossVEnv.HOST_SDKS.items()
                for platform in platforms
            }
            host = OS_MAP[parts[0]]
            platforms = [(parts[0], CrossVEnv.BASE_VERSION[host], parts[1])]
        elif len(parts) == 3:
            platforms = [parts]
        else:
            print()
            print("Invalid host. Host should be:")
            print(
                "  * the name of an operating system (android, iOS, tvOS, watchOS); or"
            )
            print("  * a tuple of abi:arch (e.g., iphoneos:arm64); or")
            print("  * a triple of abi:version:arch (e.g., iphoneos:12.0:arm64).")
            print()
            sys.exit(1)

    build_targets = args.build_targets or []

    successes = []
    failures = []
    for build_target in build_targets:
        if Path(build_target).is_dir():
            # If the build target is a directory, just build what it says.
            if args.all_versions:
                print("Ignoring --all-versions on an explicit recipe")

            package_name_or_recipe = build_target
            build_number = None
            target_versions = [None]
        else:
            # Target is a recipe. Look for version/build overrides
            parts = build_target.split(":")
            package_name_or_recipe = parts[0]

            try:
                requested_version = parts[1] if parts[1] else None
                try:
                    build_number = int(parts[2])
                except IndexError:
                    build_number = None
            except IndexError:
                requested_version = None
                build_number = None

            # If --all-versions was specified, build the list of versions.
            if args.all_versions:
                if requested_version:
                    print("Specific version requested; ignoring --all-versions")
                    target_versions = [requested_version]
                else:
                    target_versions = get_pypi_versions(package_name_or_recipe)
            else:
                target_versions = [requested_version]

        for version in target_versions:
            # First build of each version must be clean;
            # subsequent builds will be isolated by

            first = True
            build_platforms = platforms

            # Build the package for each required platform.
            for sdk, sdk_version, arch in build_platforms:
                package = Package(
                    package_name_or_recipe,
                    version=version,
                    build_number=build_number,
                    sdk=sdk,
                    sdk_version=sdk_version,
                    arch=arch,
                )
                cross_venv = CrossVEnv(sdk=sdk, sdk_version=sdk_version, arch=arch)
                builder = package.builder(cross_venv)
                success = builder.build(clean=first)

                # If the build was successful, subsequent passes don't need to be clean.
                if success:
                    first = False
                    successes.append((package_name_or_recipe, version, cross_venv.tag))
                else:
                    failures.append((package_name_or_recipe, version, cross_venv.tag))

    if successes:
        print()
        print("Successful builds for:")
        for name, version, tag in successes:
            print(f" * {name} {version if version else '(default version)'} ({tag})")
        print()

    if failures:
        print()
        print("Failed builds for:")
        for name, version, tag in failures:
            print(f" * {name} {version if version else '(default version)'} ({tag})")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
