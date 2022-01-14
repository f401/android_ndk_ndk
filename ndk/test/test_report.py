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
"""Tests for ndk.test.report."""
import unittest

import ndk.run_tests
import ndk.test.report


class MockTest:
    def __init__(self, name: str = "") -> None:
        self.name = name


class ReportTest(unittest.TestCase):
    def test_remove_all_failing_flaky(self) -> None:
        report = ndk.test.report.Report()
        # Success. Not filtered.
        report.add_result("build", ndk.test.result.Success(MockTest()))

        # Normal failure. Not filtered.
        report.add_result("build", ndk.test.result.Failure(MockTest(), "failed"))

        # Skipped test. Not filtered.
        report.add_result("build", ndk.test.result.Skipped(MockTest(), "skipped"))

        # Expected failure. Not filtered.
        report.add_result(
            "build",
            ndk.test.result.ExpectedFailure(MockTest(), "failed", "bug", "config"),
        )

        # Unexpected success. Not filtered.
        report.add_result(
            "build", ndk.test.result.UnexpectedSuccess(MockTest(), "bug", "config")
        )

        # adb didn't tell us anything. Filtered.
        report.add_result(
            "build",
            ndk.test.result.Failure(
                MockTest(), "Could not find exit status in shell output."
            ),
        )

        # Flaky libc++ tests. Filtered.
        report.add_result(
            "build", ndk.test.result.Failure(MockTest("libc++.libcxx/thread/foo"), "")
        )
        report.add_result(
            "build", ndk.test.result.Failure(MockTest("libc++.std/thread/foo"), "")
        )

        results = report.remove_all_failing_flaky(ndk.run_tests.flake_filter)
        self.assertEqual(3, len(results))
