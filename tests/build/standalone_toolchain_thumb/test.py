#
# Copyright (C) 2017 The Android Open Source Project
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
from ndk.test.spec import BuildConfiguration
import ndk.testing.standalone_toolchain


def run_test(ndk_path: str, config: BuildConfiguration) -> tuple[bool, str]:
    return ndk.testing.standalone_toolchain.run_test(
        ndk_path, config, "foo.cpp", ["--stl=libc++"], ["-mthumb"]
    )
