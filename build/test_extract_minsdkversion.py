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
import textwrap
import unittest
import xml.etree.ElementPath

import build.extract_minsdkversion


class ExtractMinSdkVersionTest(unittest.TestCase):
    def testMinSdkVersion(self):
        xml_str = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <manifest
                xmlns:android="http://schemas.android.com/apk/res/android"
                package="com.test"
                android:versionCode="1"
                android:versionName="1.0">
              <application
                android:label="@string/app_name"
                android:debuggable="true">
                <activity
                  android:name=".Test"
                  android:label="@string/app_name">
                </activity>
              </application>
              <uses-sdk android:minSdkVersion="9"/>
            </manifest>
            """)
        root = xml.etree.ElementTree.fromstring(xml_str)

        self.assertEqual(
            '9', build.extract_minsdkversion.get_minsdkversion(root))

    def testUsesSdkMissingMinSdkVersion(self):
        xml_str = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <manifest
                xmlns:android="http://schemas.android.com/apk/res/android"
                package="com.test"
                android:versionCode="1"
                android:versionName="1.0">
              <application
                android:label="@string/app_name"
                android:debuggable="true">
                <activity
                  android:name=".Test"
                  android:label="@string/app_name">
                </activity>
              </application>
              <uses-sdk android:maxSdkVersion="21"/>
            </manifest>
            """)
        root = xml.etree.ElementTree.fromstring(xml_str)

        self.assertEqual(
            '', build.extract_minsdkversion.get_minsdkversion(root))

    def testNoUsesSdk(self):
        xml_str = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <manifest
                xmlns:android="http://schemas.android.com/apk/res/android"
                package="com.test"
                android:versionCode="1"
                android:versionName="1.0">
              <application
                android:label="@string/app_name"
                android:debuggable="true">
                <activity
                  android:name=".Test"
                  android:label="@string/app_name">
                </activity>
              </application>
            </manifest>
            """)
        root = xml.etree.ElementTree.fromstring(xml_str)

        self.assertEqual(
            '', build.extract_minsdkversion.get_minsdkversion(root))
