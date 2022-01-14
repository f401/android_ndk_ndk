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
import argparse
import logging
import os
import subprocess
import sys

from bootstrap import bootstrap, python_cmd


THIS_DIR = os.path.realpath(os.path.dirname(__file__))


def parse_args():
    """Parses and returns command line arguments."""
    # Don't add help because it inhibits the real run_tests.py's --help.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        dest="verbosity",
        default=0,
        help="Increase logging verbosity.",
    )
    return parser.parse_known_args()


def main():
    """Program entry point.

    Bootstraps the real run_tests wrapper, do_runtests.py.
    """
    args, _ = parse_args()

    if args.verbosity >= 2:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    bootstrap()
    subprocess.check_call(
        [python_cmd(), os.path.join(THIS_DIR, "do_runtests.py")] + sys.argv[1:]
    )


if __name__ == "__main__":
    main()
