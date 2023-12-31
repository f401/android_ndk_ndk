#
# Copyright (C) 2016 The Android Open Source Project
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
"""Tests for ndk.paths."""
from __future__ import absolute_import

import unittest
from pathlib import Path
from unittest import mock

import ndk.config
import ndk.hosts
import ndk.paths


class GetInstallPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.release = "bar"
        self.saved_release = ndk.config.release
        ndk.config.release = self.release

    def tearDown(self) -> None:
        ndk.config.release = self.saved_release

    @mock.patch("ndk.paths.get_out_dir")
    def test_inferred_out_dir(self, mock_get_out_dir: mock.Mock) -> None:
        """Tests that the correct path is returned for an inferred out_dir"""
        out_dir = Path("foo")
        mock_get_out_dir.return_value = out_dir
        release = "android-ndk-" + self.release
        self.assertEqual(
            ndk.paths.get_install_path(),
            out_dir / ndk.hosts.get_default_host().value / release,
        )

    def test_supplied_out_dir(self) -> None:
        """Tests that the correct path is returned for a supplied out_dir"""
        out_dir = Path("foo")
        release = "android-ndk-" + self.release
        self.assertEqual(
            ndk.paths.get_install_path(Path("foo")),
            out_dir / ndk.hosts.get_default_host().value / release,
        )
