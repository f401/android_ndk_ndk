#!/usr/bin/env python
#
# Copyright (C) 2019 The Android Open Source Project
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
"""Unittests for ndk-stack.py"""

from __future__ import print_function

import os.path
import sys
import textwrap
import unittest

from unittest import mock
from unittest.mock import patch

try:
    # Python 2
    from cStringIO import StringIO
except ModuleNotFoundError:  # pylint:disable=undefined-variable
    # Python 3
    from io import StringIO

sys.path.insert(0, "../..")
ndk_stack = __import__("ndk-stack")


@patch("os.path.exists")
class PathTests(unittest.TestCase):
    """Tests of find_llvm_symbolizer() and find_readelf()."""

    def setUp(self):
        self.ndk_paths = ("/ndk_fake", "/ndk_fake/bin", "linux-x86_64")
        exe_suffix = ".EXE" if os.name == "nt" else ""
        self.llvm_symbolizer = "llvm-symbolizer" + exe_suffix
        self.readelf = "llvm-readelf" + exe_suffix

    def test_find_llvm_symbolizer_in_prebuilt(self, mock_exists):
        expected_path = os.path.join(
            "/ndk_fake",
            "toolchains",
            "llvm",
            "prebuilt",
            "linux-x86_64",
            "bin",
            self.llvm_symbolizer,
        )
        mock_exists.return_value = True
        self.assertEqual(expected_path, ndk_stack.find_llvm_symbolizer(*self.ndk_paths))
        mock_exists.assert_called_once_with(expected_path)

    def test_find_llvm_symbolizer_in_standalone_toolchain(self, mock_exists):
        prebuilt_path = os.path.join(
            "/ndk_fake",
            "toolchains",
            "llvm",
            "prebuilt",
            "linux-x86_64",
            "bin",
            self.llvm_symbolizer,
        )
        expected_path = os.path.join("/ndk_fake", "bin", self.llvm_symbolizer)
        mock_exists.side_effect = [False, True]
        self.assertEqual(expected_path, ndk_stack.find_llvm_symbolizer(*self.ndk_paths))
        mock_exists.assert_has_calls(
            [mock.call(prebuilt_path), mock.call(expected_path)]
        )

    def test_llvm_symbolizer_not_found(self, mock_exists):
        mock_exists.return_value = False
        with self.assertRaises(OSError) as cm:
            ndk_stack.find_llvm_symbolizer(*self.ndk_paths)
        self.assertEqual("Unable to find llvm-symbolizer", str(cm.exception))

    def test_find_readelf_in_prebuilt(self, mock_exists):
        expected_path = os.path.join(
            "/ndk_fake",
            "toolchains",
            "llvm",
            "prebuilt",
            "linux-x86_64",
            "bin",
            self.readelf,
        )
        mock_exists.return_value = True
        self.assertEqual(expected_path, ndk_stack.find_readelf(*self.ndk_paths))
        mock_exists.assert_called_once_with(expected_path)

    def test_find_readelf_in_prebuilt_arm(self, mock_exists):
        expected_path = os.path.join(
            "/ndk_fake",
            "toolchains",
            "llvm",
            "prebuilt",
            "linux-arm",
            "bin",
            self.readelf,
        )
        mock_exists.return_value = True
        self.assertEqual(
            expected_path,
            ndk_stack.find_readelf("/ndk_fake", "/ndk_fake/bin", "linux-arm"),
        )
        mock_exists.assert_called_once_with(expected_path)

    def test_find_readelf_in_standalone_toolchain(self, mock_exists):
        mock_exists.reset_mock()
        expected_path = os.path.join("/ndk_fake", "bin", self.readelf)
        mock_exists.side_effect = [False, True]
        os.path.exists = lambda path, exp=expected_path: path == exp
        self.assertEqual(expected_path, ndk_stack.find_readelf(*self.ndk_paths))

    def test_readelf_not_found(self, mock_exists):
        mock_exists.return_value = False
        self.assertFalse(ndk_stack.find_readelf(*self.ndk_paths))


class FrameTests(unittest.TestCase):
    """Test parsing of backtrace lines."""

    def test_line_with_map_name(self):
        line = "  #14 pc 00001000  /fake/libfake.so"
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        self.assertEqual("#14", frame_info.num)
        self.assertEqual("00001000", frame_info.pc)
        self.assertEqual("/fake/libfake.so", frame_info.tail)
        self.assertEqual("/fake/libfake.so", frame_info.elf_file)
        self.assertFalse(frame_info.offset)
        self.assertFalse(frame_info.container_file)
        self.assertFalse(frame_info.build_id)

    def test_line_with_function(self):
        line = "  #08 pc 00001040  /fake/libfake.so (func())"
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        self.assertEqual("#08", frame_info.num)
        self.assertEqual("00001040", frame_info.pc)
        self.assertEqual("/fake/libfake.so (func())", frame_info.tail)
        self.assertEqual("/fake/libfake.so", frame_info.elf_file)
        self.assertFalse(frame_info.offset)
        self.assertFalse(frame_info.container_file)
        self.assertFalse(frame_info.build_id)

    def test_line_with_offset(self):
        line = "  #04 pc 00002050  /fake/libfake.so (offset 0x2000)"
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        self.assertEqual("#04", frame_info.num)
        self.assertEqual("00002050", frame_info.pc)
        self.assertEqual("/fake/libfake.so (offset 0x2000)", frame_info.tail)
        self.assertEqual("/fake/libfake.so", frame_info.elf_file)
        self.assertEqual(0x2000, frame_info.offset)
        self.assertFalse(frame_info.container_file)
        self.assertFalse(frame_info.build_id)

    def test_line_with_build_id(self):
        line = "  #03 pc 00002050  /fake/libfake.so (BuildId: d1d420a58366bf29f1312ec826f16564)"
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        self.assertEqual("#03", frame_info.num)
        self.assertEqual("00002050", frame_info.pc)
        self.assertEqual(
            "/fake/libfake.so (BuildId: d1d420a58366bf29f1312ec826f16564)",
            frame_info.tail,
        )
        self.assertEqual("/fake/libfake.so", frame_info.elf_file)
        self.assertFalse(frame_info.offset)
        self.assertFalse(frame_info.container_file)
        self.assertEqual("d1d420a58366bf29f1312ec826f16564", frame_info.build_id)

    def test_line_with_container_file(self):
        line = "  #10 pc 00003050  /fake/fake.apk!libc.so"
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        self.assertEqual("#10", frame_info.num)
        self.assertEqual("00003050", frame_info.pc)
        self.assertEqual("/fake/fake.apk!libc.so", frame_info.tail)
        self.assertEqual("libc.so", frame_info.elf_file)
        self.assertFalse(frame_info.offset)
        self.assertEqual("/fake/fake.apk", frame_info.container_file)
        self.assertFalse(frame_info.build_id)

    def test_line_with_container_and_elf_equal(self):
        line = "  #12 pc 00004050  /fake/libc.so!lib/libc.so"
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        self.assertEqual("#12", frame_info.num)
        self.assertEqual("00004050", frame_info.pc)
        self.assertEqual("/fake/libc.so!lib/libc.so", frame_info.tail)
        self.assertEqual("/fake/libc.so", frame_info.elf_file)
        self.assertFalse(frame_info.offset)
        self.assertFalse(frame_info.container_file)
        self.assertFalse(frame_info.build_id)

    def test_line_everything(self):
        line = (
            "  #07 pc 00823fc  /fake/fake.apk!libc.so (__start_thread+64) "
            "(offset 0x1000) (BuildId: 6a0c10d19d5bf39a5a78fa514371dab3)"
        )
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        self.assertEqual("#07", frame_info.num)
        self.assertEqual("00823fc", frame_info.pc)
        self.assertEqual(
            "/fake/fake.apk!libc.so (__start_thread+64) "
            "(offset 0x1000) (BuildId: 6a0c10d19d5bf39a5a78fa514371dab3)",
            frame_info.tail,
        )
        self.assertEqual("libc.so", frame_info.elf_file)
        self.assertEqual(0x1000, frame_info.offset)
        self.assertEqual("/fake/fake.apk", frame_info.container_file)
        self.assertEqual("6a0c10d19d5bf39a5a78fa514371dab3", frame_info.build_id)


@patch.object(ndk_stack, "get_build_id")
@patch("os.path.exists")
class VerifyElfFileTests(unittest.TestCase):
    """Tests of verify_elf_file()."""

    def create_frame_info(self):
        line = "  #03 pc 00002050  /fake/libfake.so"
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        return frame_info

    def test_elf_file_does_not_exist(self, mock_exists, _):
        mock_exists.return_value = False
        frame_info = self.create_frame_info()
        self.assertFalse(
            frame_info.verify_elf_file(None, "/fake/libfake.so", "libfake.so")
        )
        self.assertFalse(
            frame_info.verify_elf_file("llvm-readelf", "/fake/libfake.so", "libfake.so")
        )

    def test_elf_file_build_id_matches(self, mock_exists, mock_get_build_id):
        mock_exists.return_value = True
        frame_info = self.create_frame_info()
        frame_info.build_id = "MOCKED_BUILD_ID"
        self.assertTrue(
            frame_info.verify_elf_file(None, "/mocked/libfake.so", "libfake.so")
        )
        mock_get_build_id.assert_not_called()

        mock_get_build_id.return_value = "MOCKED_BUILD_ID"
        self.assertTrue(
            frame_info.verify_elf_file(
                "llvm-readelf", "/mocked/libfake.so", "libfake.so"
            )
        )
        mock_get_build_id.assert_called_once_with("llvm-readelf", "/mocked/libfake.so")

    def test_elf_file_build_id_does_not_match(self, mock_exists, mock_get_build_id):
        mock_exists.return_value = True
        mock_get_build_id.return_value = "MOCKED_BUILD_ID"
        frame_info = self.create_frame_info()
        frame_info.build_id = "DIFFERENT_BUILD_ID"
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.assertTrue(
                frame_info.verify_elf_file(None, "/mocked/libfake.so", "none.so")
            )
            self.assertFalse(
                frame_info.verify_elf_file(
                    "llvm-readelf", "/mocked/libfake.so", "display.so"
                )
            )
        output = textwrap.dedent(
            """\
            WARNING: Mismatched build id for display.so
            WARNING:   Expected DIFFERENT_BUILD_ID
            WARNING:   Found    MOCKED_BUILD_ID
        """
        )
        self.assertEqual(output, mock_stdout.getvalue())


class GetZipInfoFromOffsetTests(unittest.TestCase):
    """Tests of get_zip_info_from_offset()."""

    def setUp(self):
        self.mock_zip = mock.MagicMock()
        self.mock_zip.filename = "/fake/zip.apk"
        self.mock_zip.infolist.return_value = []

    def test_file_does_not_exist(self):
        with self.assertRaises(IOError):
            _ = ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x1000)

    @patch("os.stat")
    def test_offset_ge_file_size(self, mock_stat):
        mock_stat.return_value.st_size = 0x1000
        self.assertFalse(ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x1000))
        self.assertFalse(ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x1100))

    @patch("os.stat")
    def test_empty_infolist(self, mock_stat):
        mock_stat.return_value.st_size = 0x1000
        self.assertFalse(ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x900))

    @patch("os.stat")
    def test_zip_info_single_element(self, mock_stat):
        mock_stat.return_value.st_size = 0x2000

        mock_zip_info = mock.MagicMock()
        mock_zip_info.header_offset = 0x100
        self.mock_zip.infolist.return_value = [mock_zip_info]

        self.assertFalse(ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x50))

        self.assertFalse(ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x2000))

        zip_info = ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x200)
        self.assertEqual(0x100, zip_info.header_offset)

    @patch("os.stat")
    def test_zip_info_checks(self, mock_stat):
        mock_stat.return_value.st_size = 0x2000

        mock_zip_info1 = mock.MagicMock()
        mock_zip_info1.header_offset = 0x100
        mock_zip_info2 = mock.MagicMock()
        mock_zip_info2.header_offset = 0x1000
        self.mock_zip.infolist.return_value = [mock_zip_info1, mock_zip_info2]

        self.assertFalse(ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x50))

        zip_info = ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x200)
        self.assertEqual(0x100, zip_info.header_offset)

        zip_info = ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x100)
        self.assertEqual(0x100, zip_info.header_offset)

        zip_info = ndk_stack.get_zip_info_from_offset(self.mock_zip, 0x1000)
        self.assertEqual(0x1000, zip_info.header_offset)


class GetElfFileTests(unittest.TestCase):
    """Tests of FrameInfo.get_elf_file()."""

    def setUp(self):
        self.mock_zipfile = mock.MagicMock()
        self.mock_zipfile.extract.return_value = "/fake_tmp/libtest.so"
        self.mock_zipfile.__enter__.return_value = self.mock_zipfile

        self.mock_tmp = mock.MagicMock()
        self.mock_tmp.get_directory.return_value = "/fake_tmp"

    def create_frame_info(self, tail):
        line = "  #03 pc 00002050  " + tail
        frame_info = ndk_stack.FrameInfo.from_line(line)
        self.assertTrue(frame_info)
        frame_info.verify_elf_file = mock.MagicMock()
        return frame_info

    def test_file_only(self):
        frame_info = self.create_frame_info("/fake/libfake.so")
        frame_info.verify_elf_file.return_value = True
        self.assertEqual(
            "/fake_dir/symbols/libfake.so",
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp),
        )
        frame_info.verify_elf_file.reset_mock()
        frame_info.verify_elf_file.return_value = False
        self.assertFalse(
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp)
        )
        self.assertEqual("/fake/libfake.so", frame_info.tail)

    def test_container_set_elf_in_symbol_dir(self):
        frame_info = self.create_frame_info("/fake/fake.apk!libtest.so")
        frame_info.verify_elf_file.return_value = True
        self.assertEqual(
            "/fake_dir/symbols/libtest.so",
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp),
        )
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)

    def test_container_set_elf_not_in_symbol_dir_apk_does_not_exist(self):
        frame_info = self.create_frame_info("/fake/fake.apk!libtest.so")
        frame_info.verify_elf_file.return_value = False
        with self.assertRaises(IOError):
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp)
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)

    @patch.object(ndk_stack, "get_zip_info_from_offset")
    @patch("zipfile.ZipFile")
    def test_container_set_elf_not_in_apk(self, _, mock_get_zip_info):
        mock_get_zip_info.return_value = None
        frame_info = self.create_frame_info("/fake/fake.apk!libtest.so")
        frame_info.verify_elf_file.return_value = False
        self.assertFalse(
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp)
        )
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)

    @patch.object(ndk_stack, "get_zip_info_from_offset")
    @patch("zipfile.ZipFile")
    def test_container_set_elf_in_apk(self, mock_zipclass, mock_get_zip_info):
        mock_zipclass.return_value = self.mock_zipfile
        mock_get_zip_info.return_value.filename = "libtest.so"

        frame_info = self.create_frame_info("/fake/fake.apk!libtest.so")
        frame_info.verify_elf_file.side_effect = [False, True]
        self.assertEqual(
            "/fake_tmp/libtest.so",
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp),
        )
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)

    @patch.object(ndk_stack, "get_zip_info_from_offset")
    @patch("zipfile.ZipFile")
    def test_container_set_elf_in_apk_verify_fails(
        self, mock_zipclass, mock_get_zip_info
    ):
        mock_zipclass.return_value = self.mock_zipfile
        mock_get_zip_info.return_value.filename = "libtest.so"

        frame_info = self.create_frame_info("/fake/fake.apk!libtest.so")
        frame_info.verify_elf_file.side_effect = [False, False]
        self.assertFalse(
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp)
        )
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)

    def test_in_apk_file_does_not_exist(self):
        frame_info = self.create_frame_info("/fake/fake.apk")
        frame_info.verify_elf_file.return_value = False
        with self.assertRaises(IOError):
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp)
        self.assertEqual("/fake/fake.apk", frame_info.tail)

    @patch.object(ndk_stack, "get_zip_info_from_offset")
    @patch("zipfile.ZipFile")
    def test_in_apk_elf_not_in_apk(self, _, mock_get_zip_info):
        mock_get_zip_info.return_value = None
        frame_info = self.create_frame_info("/fake/fake.apk")
        self.assertFalse(
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp)
        )
        self.assertEqual("/fake/fake.apk", frame_info.tail)

    @patch.object(ndk_stack, "get_zip_info_from_offset")
    @patch("zipfile.ZipFile")
    def test_in_apk_elf_in_symbol_dir(self, mock_zipclass, mock_get_zip_info):
        mock_zipclass.return_value = self.mock_zipfile
        mock_get_zip_info.return_value.filename = "libtest.so"

        frame_info = self.create_frame_info("/fake/fake.apk")
        frame_info.verify_elf_file.return_value = True
        self.assertEqual(
            "/fake_dir/symbols/libtest.so",
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp),
        )
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)

    @patch.object(ndk_stack, "get_zip_info_from_offset")
    @patch("zipfile.ZipFile")
    def test_in_apk_elf_in_apk(self, mock_zipclass, mock_get_zip_info):
        mock_zipclass.return_value = self.mock_zipfile
        mock_get_zip_info.return_value.filename = "libtest.so"

        frame_info = self.create_frame_info("/fake/fake.apk")
        frame_info.verify_elf_file.side_effect = [False, True]
        self.assertEqual(
            "/fake_tmp/libtest.so",
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp),
        )
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)

    @patch.object(ndk_stack, "get_zip_info_from_offset")
    @patch("zipfile.ZipFile")
    def test_in_apk_elf_in_apk_verify_fails(self, mock_zipclass, mock_get_zip_info):
        mock_zipclass.return_value = self.mock_zipfile
        mock_get_zip_info.return_value.filename = "libtest.so"

        frame_info = self.create_frame_info("/fake/fake.apk")
        frame_info.verify_elf_file.side_effect = [False, False]
        self.assertFalse(
            frame_info.get_elf_file("/fake_dir/symbols", None, self.mock_tmp)
        )
        self.assertEqual("/fake/fake.apk!libtest.so", frame_info.tail)


if __name__ == "__main__":
    unittest.main()
