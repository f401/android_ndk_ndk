#!/usr/bin/env python
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
"""Shortcut for ndk/run_tests.py.

This would normally be installed by pip, but we want to keep this in place in
the source directory since the buildbots expect it to be here.
"""
import ndk.run_tests


def main() -> None:
    """Trampoline into the test runner defined in the ndk package."""
    ndk.run_tests.main()


if __name__ == "__main__":
    main()
