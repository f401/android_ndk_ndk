#
# Copyright (C) 2021 The Android Open Source Project
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
"""Check that pre-LP64 API levels are correctly pulled-up for CMake."""
from pathlib import Path
import re
import subprocess

from ndk.cmake import find_cmake, find_ninja
from ndk.test.spec import BuildConfiguration, CMakeToolchainFile


def run_test(ndk_path: str, config: BuildConfiguration) -> tuple[bool, str]:
    """Check that pre-LP64 API levels are correctly pulled-up for CMake."""
    cmake = find_cmake()
    ninja = find_ninja()
    toolchain_path = Path(ndk_path) / 'build/cmake/android.toolchain.cmake'
    project_path = 'project'
    if config.toolchain_file is CMakeToolchainFile.Legacy:
        toolchain_mode = 'ON'
    else:
        toolchain_mode = 'OFF'

    test_inputs = (
        '-DANDROID_PLATFORM=19',
        '-DANDROID_PLATFORM=android-19',
        '-DANDROID_NATIVE_API_LEVEL=19',
        '-DANDROID_NATIVE_API_LEVEL=android-19',
    )

    for arg in test_inputs:
        cmake_cmd = [
            str(cmake),
            f'-DCMAKE_TOOLCHAIN_FILE={toolchain_path}',
            f'-DANDROID_ABI={config.abi}',
            arg,
            f'-DCMAKE_MAKE_PROGRAM={ninja}',
            f'-DANDROID_USE_LEGACY_TOOLCHAIN_FILE={toolchain_mode}',
            '-GNinja',
        ]
        result = subprocess.run(cmake_cmd,
                                check=False,
                                cwd=project_path,
                                capture_output=True,
                                text=True)
        if result.returncode != 0:
            return False, result.stdout
        if config.toolchain_file is CMakeToolchainFile.Default:
            expected = re.compile(
                r'android-19 is not supported.*'
                r'Using minimum supported LP64 version 21.')
            if not expected.search(result.stdout):
                return False, (f'expected pattern "{expected.pattern}" is '
                               f'missing from cmake output:\n{result.stdout}')

    return True, ''
