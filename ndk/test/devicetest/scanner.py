#
# Copyright (C) 2022 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import logging
import os
from pathlib import Path, PurePosixPath
from typing import (
    Any,
    Callable,
    Dict,
    List,
)

import ndk.test.builder
from ndk.test.devicetest.case import TestCase, BasicTestCase, LibcxxTestCase
from ndk.test.filters import TestFilter
from ndk.test.spec import BuildConfiguration


def logger() -> logging.Logger:
    """Returns the module logger."""
    return logging.getLogger(__name__)


def _enumerate_basic_tests(
    out_dir_base: Path,
    test_src_dir: Path,
    device_base_dir: PurePosixPath,
    build_cfg: BuildConfiguration,
    build_system: str,
    test_filter: TestFilter,
) -> List[TestCase]:
    tests: List[TestCase] = []
    tests_dir = out_dir_base / str(build_cfg) / build_system
    if not tests_dir.exists():
        return tests

    for test_subdir in os.listdir(tests_dir):
        test_dir = tests_dir / test_subdir
        out_dir = test_dir / build_cfg.abi
        test_relpath = out_dir.relative_to(out_dir_base)
        device_dir = device_base_dir / test_relpath
        for test_file in os.listdir(out_dir):
            if test_file.endswith(".so"):
                continue
            if test_file.endswith(".sh"):
                continue
            if test_file.endswith(".a"):
                test_path = out_dir / test_file
                logger().error(
                    "Found static library in app install directory. Static "
                    "libraries should never be installed. This is a bug in "
                    "the build system: %s",
                    test_path,
                )
                continue
            name = ".".join([test_subdir, test_file])
            if not test_filter.filter(name):
                continue
            tests.append(
                BasicTestCase(
                    test_subdir,
                    test_file,
                    test_src_dir,
                    build_cfg,
                    build_system,
                    device_dir,
                )
            )
    return tests


def _enumerate_libcxx_tests(
    out_dir_base: Path,
    test_src_dir: Path,
    device_base_dir: PurePosixPath,
    build_cfg: BuildConfiguration,
    build_system: str,
    test_filter: TestFilter,
) -> List[TestCase]:
    tests: List[TestCase] = []
    tests_dir = out_dir_base / str(build_cfg) / build_system
    if not tests_dir.exists():
        return tests

    for root, _, files in os.walk(tests_dir):
        for test_file in files:
            if not test_file.endswith(".exe"):
                continue
            test_relpath = Path(root).relative_to(out_dir_base)
            device_dir = device_base_dir / test_relpath
            suite_name = str(PurePosixPath(Path(os.path.relpath(root, tests_dir))))

            # Our file has a .exe extension, but the name should match the
            # source file for the filters to work.
            test_name = test_file[:-4]

            # Tests in the top level don't need any mangling to match the
            # filters.
            if suite_name != "libc++":
                if not suite_name.startswith("libc++/"):
                    raise ValueError(suite_name)
                # According to the test runner, these are all part of the
                # "libc++" test, and the rest of the data is the subtest name.
                # i.e.  libc++/foo/bar/baz.cpp.exe is actually
                # libc++.foo/bar/baz.cpp.  Matching this expectation here
                # allows us to use the same filter string for running the tests
                # as for building the tests.
                test_path = suite_name[len("libc++/") :]
                test_name = "/".join([test_path, test_name])

            filter_name = ".".join(["libc++", test_name])
            if not test_filter.filter(filter_name):
                continue
            tests.append(
                LibcxxTestCase(
                    suite_name,
                    test_file,
                    test_src_dir,
                    build_cfg,
                    device_dir,
                    device_base_dir,
                )
            )
    return tests


class ConfigFilter:
    def __init__(self, test_spec: ndk.test.spec.TestSpec) -> None:
        self.spec = test_spec

    def filter(self, build_config: BuildConfiguration) -> bool:
        return build_config.abi in self.spec.abis


def enumerate_tests(
    test_dir: Path,
    test_src_dir: Path,
    device_base_dir: PurePosixPath,
    test_filter: TestFilter,
    config_filter: ConfigFilter,
) -> Dict[BuildConfiguration, List[TestCase]]:
    tests: Dict[BuildConfiguration, List[TestCase]] = {}

    # The tests directory has a directory for each type of test. For example:
    #
    #  * build.sh
    #  * cmake
    #  * libcxx
    #  * ndk-build
    #  * test.py
    #
    # We need to handle some of these differently. The test.py and build.sh
    # type tests are build only, so we don't need to run them. The libc++ tests
    # are built by a test runner we don't control, so its output doesn't quite
    # match what we expect.
    test_subdir_class_map: Dict[
        str,
        Callable[
            [Path, Path, PurePosixPath, BuildConfiguration, str, TestFilter],
            List[TestCase],
        ],
    ] = {
        "cmake": _enumerate_basic_tests,
        "libcxx": _enumerate_libcxx_tests,
        "ndk-build": _enumerate_basic_tests,
    }

    for build_cfg_str in os.listdir(test_dir):
        build_cfg = BuildConfiguration.from_string(build_cfg_str)
        if not config_filter.filter(build_cfg):
            continue

        if build_cfg not in tests:
            tests[build_cfg] = []

        for test_type, scan_for_tests in test_subdir_class_map.items():
            tests[build_cfg].extend(
                scan_for_tests(
                    test_dir,
                    test_src_dir,
                    device_base_dir,
                    build_cfg,
                    test_type,
                    test_filter,
                )
            )

    return tests
