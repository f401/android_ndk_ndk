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
from pathlib import Path, PurePosixPath
import os
import shlex
import traceback
from typing import (
    Optional,
    Tuple,
    Union,
)

from ndk.test.config import DeviceTestConfig, LibcxxTestConfig
from ndk.test.devices import Device, DeviceConfig
from ndk.test.spec import BuildConfiguration


AdbResult = tuple[int, str, str, str]


def logger() -> logging.Logger:
    """Returns the module logger."""
    return logging.getLogger(__name__)


def shell_nocheck_wrap_errors(device: Device, cmd: str) -> AdbResult:
    """Invokes device.shell_nocheck and wraps exceptions as failed commands."""
    repro_cmd = f"adb -s {device.serial} shell {shlex.quote(cmd)}"
    try:
        rc, stdout, stderr = device.shell_nocheck([cmd])
        return rc, stdout, stderr, repro_cmd
    except RuntimeError:
        return 1, cmd, traceback.format_exc(), repro_cmd


# TODO: Extract a common interface from this and ndk.test.case.build.Test for the
# printer.
class TestCase:
    """A device test case found in the dist directory.

    The test directory is structured as tests/dist/$CONFIG/$BUILD_SYSTEM/...
    What follows depends on the type of test case. Each discovered test case
    will have a name, a build configuration, a build system, and a device
    directory.
    """

    def __init__(
        self,
        name: str,
        test_src_dir: Path,
        config: BuildConfiguration,
        build_system: str,
        device_dir: PurePosixPath,
    ) -> None:
        self.name = name
        self.test_src_dir = test_src_dir
        self.config = config
        self.build_system = build_system
        self.device_dir = device_dir

    def check_unsupported(self, device: DeviceConfig) -> Optional[str]:
        raise NotImplementedError

    def check_broken(
        self, device: DeviceConfig
    ) -> Union[Tuple[None, None], Tuple[str, str]]:
        raise NotImplementedError

    def run(self, device: Device) -> AdbResult:
        logger().info('%s: shell_nocheck "%s"', device.name, self.cmd)
        return shell_nocheck_wrap_errors(device, self.cmd)

    # Note that TradeFed will split this command on whitespace, and verify
    # that one of the tokens is an executable file on the device. Therefore, you
    # must ensure that TestCase.cmd contains, somewhere, the full path
    # to the executable, surrounded by whitespace.
    #
    # For example, neither of the following will work:
    #   cd /path && ./cmd      # relative path
    #   /path/cmd||echo "foo"  # no whitespace
    @property
    def cmd(self) -> str:
        """The shell command to run on the device to execute the test case."""
        raise NotImplementedError

    @property
    def negated_cmd(self) -> str:
        """The command to execute the test case, but with the exit code flipped."""
        # Note that TradeFed will split this command on whitespace, and verify
        # that one of the tokens is an executable file on the device.
        # So the whitespace around the parens is intentional, because
        # ! (/path/to/some/cmd) won't work.
        return f"! ( {self.cmd} )"


class BasicTestCase(TestCase):
    """A test case for the standard NDK test builder.

    These tests were written specifically for the NDK and thus follow the
    layout we expect. In each test configuration directory, we have
    $TEST_SUITE/$ABI/$TEST_FILES. $TEST_FILES includes both the shared
    libraries for the test and the test executables.
    """

    def __init__(
        self,
        suite: str,
        executable: str,
        test_src_dir: Path,
        config: BuildConfiguration,
        build_system: str,
        device_dir: PurePosixPath,
    ) -> None:
        name = ".".join([suite, executable])
        super().__init__(name, test_src_dir, config, build_system, device_dir)

        self.suite = suite
        self.executable = executable

    def get_test_config(self) -> DeviceTestConfig:
        # We don't run anything in tests/build, and the libc++ tests are
        # handled by a different LibcxxTest. We can safely assume that anything
        # here is in tests/device.
        test_dir = self.test_src_dir / "device" / self.suite
        return DeviceTestConfig.from_test_dir(test_dir)

    def check_unsupported(self, device: DeviceConfig) -> Optional[str]:
        return self.get_test_config().run_unsupported(self, device)

    def check_broken(
        self, device: DeviceConfig
    ) -> Union[Tuple[None, None], Tuple[str, str]]:
        return self.get_test_config().run_broken(self, device)

    @property
    def cmd(self) -> str:
        # See note in the base class above about parsing by TradeFed.
        return "cd {} && LD_LIBRARY_PATH={} {}/{} 2>&1".format(
            self.device_dir, self.device_dir, self.device_dir, self.executable
        )


class LibcxxTestCase(TestCase):
    """A libc++ test case built by LIT.

    LIT's test structure doesn't map cleanly to ours; they have a hierarchical
    test structure. The top level contains a single "libc++" directory. In that
    directory is where shared libraries common to all tests are placed. That
    directory and any under it may contain test executables (always suffixed
    with ".exe") or test data (always suffixed with ".dat").
    """

    def __init__(
        self,
        suite: str,
        executable: str,
        test_src_dir: Path,
        config: BuildConfiguration,
        device_dir: PurePosixPath,
        device_base_dir: PurePosixPath,
    ) -> None:
        # Tests in the top level don't need any mangling to match the filters.
        if suite == "libc++":
            filter_name = executable
        else:
            filter_name = os.path.join(suite[len("libc++/") :], executable)

        # The executable name ends with .exe. Remove that so it matches the
        # filter that would be used to build the test.
        name = ".".join(["libc++", filter_name[:-4]])
        super().__init__(name, test_src_dir, config, "libc++", device_dir)
        self.suite = suite
        self.executable = executable
        self.device_base_dir = device_base_dir

    @property
    def case_name(self) -> str:
        # Executable is foo.pass.cpp.exe, we want foo.pass.
        return os.path.splitext(os.path.splitext(self.executable)[0])[0]

    def get_test_config(self) -> DeviceTestConfig:
        _, _, test_subdir = self.suite.partition("/")
        test_dir = self.test_src_dir / "libc++/test" / test_subdir
        return LibcxxTestConfig.from_test_dir(test_dir)

    def check_unsupported(self, device: DeviceConfig) -> Optional[str]:
        config = self.get_test_config().run_unsupported(self, device)
        if config is not None:
            return config
        return None

    def check_broken(
        self, device: DeviceConfig
    ) -> Union[Tuple[None, None], Tuple[str, str]]:
        config, bug = self.get_test_config().run_broken(self, device)
        if config is not None:
            assert bug is not None
            return config, bug
        return None, None

    @property
    def cmd(self) -> str:
        # See note in the base class above about parsing by TradeFed.
        libcxx_so_dir = self.device_base_dir / str(self.config) / "libcxx" / "libc++"
        return "cd {} && LD_LIBRARY_PATH={} ./{} 2>&1".format(
            self.device_dir, libcxx_so_dir, self.executable
        )
