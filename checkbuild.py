#!/usr/bin/env python
#
# Copyright (C) 2018 The Android Open Source Project
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
"""Shortcut for ndk/checkbuild.py.

Differs from do_checkbuild.py because it launches a new Python interpreter,
allowing this script to bootstrap our build with a specific version of Python.
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
    # Don't add help because it inhibits the real checkbuild.py's --help.
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

    Bootstraps the real checkbuild wrapper, do_checkbuild.py.
    """
    args, _ = parse_args()

    if args.verbosity >= 2:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    bootstrap()
    new_env = os.environ.copy()
    new_env["PYTHONNOUSERSITE"] = "1"
    if "PYTHONPATH" in new_env:
        del new_env["PYTHONPATH"]
    subprocess.check_call(
        [python_cmd(), os.path.join(THIS_DIR, "do_checkbuild.py")] + sys.argv[1:],
        env=new_env,
    )


if __name__ == "__main__":
    main()
