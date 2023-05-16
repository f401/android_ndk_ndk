#!/usr/bin/env python3
#
# Copyright (C) 2015 The Android Open Source Project
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

from __future__ import print_function

import argparse
import contextlib
import logging
import operator
import os
import posixpath
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree

import adb
import gdbrunner

NDK_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))

def log(msg):
    logger = logging.getLogger(__name__)
    logger.info(msg)


def enable_verbose_logging():
    logger = logging.getLogger(__name__)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter()

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False

    logger.setLevel(logging.INFO)


def error(msg):
    sys.exit("ERROR: {}".format(msg))


class ArgumentParser(gdbrunner.ArgumentParser):
    def __init__(self):
        super(ArgumentParser, self).__init__()
        self.add_argument(
            "--verbose", "-v", action="store_true", help="enable verbose mode"
        )

        self.add_argument(
            "--force",
            "-f",
            action="store_true",
            help="kill existing debug session if it exists",
        )

        self.add_argument(
            "--port",
            type=int,
            nargs="?",
            default="5039",
            help="override the port used on the host.",
        )

        self.add_argument(
            "--delay",
            type=float,
            default=0.25,
            help="delay in seconds to wait after starting activity.\n"
            "defaults to 0.25, higher values may be needed on slower devices.",
        )

        self.add_argument(
            "-p", "--project", dest="project", help="specify application project path"
        )

        lldb_group = self.add_mutually_exclusive_group()
        lldb_group.add_argument("--lldb", action="store_true", help="Use lldb.")
        lldb_group.add_argument(
            "--no-lldb", action="store_true", help="Do not use lldb."
        )

        app_group = self.add_argument_group("target selection")
        start_group = app_group.add_mutually_exclusive_group()

        start_group.add_argument(
            "--attach",
            nargs="?",
            dest="package_name",
            metavar="PKG_NAME",
            help="attach to application (default)\n"
            "autodetects PKG_NAME if not specified",
        )

        # NB: args.launch can be False (--attach), None (--launch), or a string
        start_group.add_argument(
            "--launch",
            nargs="?",
            dest="launch",
            default=False,
            metavar="ACTIVITY",
            help="launch application activity\n"
            "launches main activity if ACTIVITY not specified",
        )

        start_group.add_argument(
            "--launch-list",
            action="store_true",
            help="list all launchable activity names from manifest",
        )

        debug_group = self.add_argument_group("debugging options")
        debug_group.add_argument(
            "-x",
            "--exec",
            dest="exec_file",
            help="execute gdb commands in EXEC_FILE after connection",
        )

        debug_group.add_argument(
            "--nowait",
            action="store_true",
            help="do not wait for debugger to attach (may miss early JNI "
            "breakpoints)",
        )

        if sys.platform.startswith("win"):
            tui_help = argparse.SUPPRESS
        else:
            tui_help = "use GDB's tui mode"

        debug_group.add_argument(
            "-t", "--tui", action="store_true", dest="tui", help=tui_help
        )


def extract_package_name(xmlroot):
    if "package" in xmlroot.attrib:
        return xmlroot.attrib["package"]
    error("Failed to find package name in AndroidManifest.xml")


ANDROID_XMLNS = "{http://schemas.android.com/apk/res/android}"


def extract_launchable(xmlroot):
    """
    A given application can have several activities, and each activity
    can have several intent filters. We want to only list, in the final
    output, the activities which have a intent-filter that contains the
    following elements:

      <action android:name="android.intent.action.MAIN" />
      <category android:name="android.intent.category.LAUNCHER" />
    """
    launchable_activities = []
    application = xmlroot.findall("application")[0]

    main_action = "android.intent.action.MAIN"
    launcher_category = "android.intent.category.LAUNCHER"
    name_attrib = "{}name".format(ANDROID_XMLNS)

    for activity in application.iter("activity"):
        if name_attrib not in activity.attrib:
            continue

        for intent_filter in activity.iter("intent-filter"):
            found_action = False
            found_category = False
            for child in intent_filter:
                if child.tag == "action":
                    if not found_action and name_attrib in child.attrib:
                        if child.attrib[name_attrib] == main_action:
                            found_action = True
                if child.tag == "category":
                    if not found_category and name_attrib in child.attrib:
                        if child.attrib[name_attrib] == launcher_category:
                            found_category = True
            if found_action and found_category:
                launchable_activities.append(activity.attrib[name_attrib])
    return launchable_activities


def ndk_bin_path():
    return os.path.dirname(os.path.realpath(__file__))


def handle_args():
    def find_program(program, paths):
        """Find a binary in paths"""
        exts = [""]
        if sys.platform.startswith("win"):
            exts += [".exe", ".bat", ".cmd"]
        for path in paths:
            if os.path.isdir(path):
                for ext in exts:
                    full = path + os.sep + program + ext
                    if os.path.isfile(full):
                        return full
        return None

    # FIXME: This is broken for PATH that contains quoted colons.
    paths = os.environ["PATH"].replace('"', "").split(os.pathsep)

    args = ArgumentParser().parse_args()

    if args.tui and sys.platform.startswith("win"):
        error("TUI is unsupported on Windows.")

    ndk_bin = ndk_bin_path()
    args.make_cmd = find_program("make", [ndk_bin])
    args.jdb_cmd = find_program("jdb", paths)
    if args.make_cmd is None:
        error("Failed to find make in '{}'".format(ndk_bin))
    if args.jdb_cmd is None:
        print("WARNING: Failed to find jdb on your path, defaulting to " "--nowait")
        args.nowait = True

    if args.verbose:
        enable_verbose_logging()

    return args


def find_project(args):
    manifest_name = "AndroidManifest.xml"
    if args.project is not None:
        log("Using project directory: {}".format(args.project))
        args.project = os.path.realpath(os.path.expanduser(args.project))
        if not os.path.exists(os.path.join(args.project, manifest_name)):
            msg = "could not find AndroidManifest.xml in '{}'"
            error(msg.format(args.project))
    else:
        # Walk upwards until we find AndroidManifest.xml, or run out of path.
        current_dir = os.getcwd()
        while not os.path.exists(os.path.join(current_dir, manifest_name)):
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                error(
                    "Could not find AndroidManifest.xml in current"
                    " directory or a parent directory.\n"
                    "       Launch this script from inside a project, or"
                    " use --project=<path>."
                )
            current_dir = parent_dir
        args.project = current_dir
        log("Using project directory: {} ".format(args.project))
    args.manifest_path = os.path.join(args.project, manifest_name)
    return args.project


def canonicalize_activity(package_name, activity_name):
    if activity_name.startswith("."):
        return "{}{}".format(package_name, activity_name)
    return activity_name


def parse_manifest(args):
    manifest = ElementTree.parse(args.manifest_path)
    manifest_root = manifest.getroot()
    package_name = extract_package_name(manifest_root)
    log("Found package name: {}".format(package_name))

    activities = extract_launchable(manifest_root)
    activities = [canonicalize_activity(package_name, a) for a in activities]

    if args.launch_list:
        print("Launchable activities: {}".format(", ".join(activities)))
        sys.exit(0)

    args.activities = activities
    args.package_name = package_name


def select_target(args):
    assert args.launch != False

    if len(args.activities) == 0:
        error("No launchable activities found.")

    if args.launch is None:
        target = args.activities[0]

        if len(args.activities) > 1:
            print(
                "WARNING: Multiple launchable activities found, choosing"
                " '{}'.".format(args.activities[0])
            )
    else:
        activity_name = canonicalize_activity(args.package_name, args.launch)

        if activity_name not in args.activities:
            msg = "Could not find launchable activity: '{}'."
            error(msg.format(activity_name))
        target = activity_name
    return target


@contextlib.contextmanager
def cd(path):
    curdir = os.getcwd()
    os.chdir(path)
    os.environ["PWD"] = path
    try:
        yield
    finally:
        os.environ["PWD"] = curdir
        os.chdir(curdir)


def dump_var(args, variable, abi=None):
    make_args = [
        args.make_cmd,
        "--no-print-dir",
        "-f",
        os.path.join(NDK_PATH, "build/core/build-local.mk"),
        "-C",
        args.project,
        "DUMP_{}".format(variable),
    ]

    if abi is not None:
        make_args.append("APP_ABI={}".format(abi))

    with cd(args.project):
        try:
            make_output = subprocess.check_output(make_args, cwd=args.project)
        except subprocess.CalledProcessError:
            error("Failed to retrieve application ABI from Android.mk.")
    return make_output.splitlines()[-1].decode()


def get_api_level(device):
    # Check the device API level
    try:
        api_level = int(device.get_prop("ro.build.version.sdk"))
    except (TypeError, ValueError):
        error(
            "Failed to find target device's supported API level.\n"
            "ndk-gdb only supports devices running Android 2.2 or higher."
        )
    if api_level < 8:
        error(
            "ndk-gdb only supports devices running Android 2.2 or higher.\n"
            "(expected API level 8, actual: {})".format(api_level)
        )

    return api_level


def fetch_abi(args):
    """
    Figure out the intersection of which ABIs the application is built for and
    which ones the device supports, then pick the one preferred by the device,
    so that we know which gdbserver to push and run on the device.
    """

    app_abis = dump_var(args, "APP_ABI").split(" ")
    if "all" in app_abis:
        app_abis = dump_var(args, "NDK_ALL_ABIS").split(" ")
    app_abis_msg = "Application ABIs: {}".format(", ".join(app_abis))
    log(app_abis_msg)

    new_abi_props = ["ro.product.cpu.abilist"]
    old_abi_props = ["ro.product.cpu.abi", "ro.product.cpu.abi2"]
    abi_props = new_abi_props
    if args.device.get_prop("ro.product.cpu.abilist") is None:
        abi_props = old_abi_props

    device_abis = []
    for key in abi_props:
        value = args.device.get_prop(key)
        if value is not None:
            device_abis.extend(value.split(","))

    device_abis_msg = "Device ABIs: {}".format(", ".join(device_abis))
    log(device_abis_msg)

    for abi in device_abis:
        if abi in app_abis:
            # TODO(jmgao): Do we expect gdb to work with ARM-x86 translation?
            log("Selecting ABI: {}".format(abi))
            return abi

    msg = "Application cannot run on the selected device."

    # Don't repeat ourselves.
    if not args.verbose:
        msg += "\n{}\n{}".format(app_abis_msg, device_abis_msg)

    error(msg)


def get_run_as_cmd(user, cmd):
    return ["run-as", user] + cmd


def get_app_data_dir(args, package_name):
    cmd = ["/system/bin/sh", "-c", "pwd", "2>/dev/null"]
    cmd = get_run_as_cmd(package_name, cmd)
    (rc, stdout, _) = args.device.shell_nocheck(cmd)
    if rc != 0:
        error(
            "Could not find application's data directory. Are you sure that "
            "the application is installed and debuggable?"
        )
    data_dir = stdout.strip()

    # Applications with minSdkVersion >= 24 will have their data directories
    # created with rwx------ permissions, preventing adbd from forwarding to
    # the gdbserver socket. To be safe, if we're on a device >= 24, always
    # chmod the directory.
    if get_api_level(args.device) >= 24:
        chmod_cmd = ["/system/bin/chmod", "a+x", data_dir]
        chmod_cmd = get_run_as_cmd(package_name, chmod_cmd)
        (rc, _, _) = args.device.shell_nocheck(chmod_cmd)
        if rc != 0:
            error("Failed to make application data directory world executable")

    log("Found application data directory: {}".format(data_dir))
    return data_dir


def abi_to_arch(abi):
    if abi.startswith("armeabi"):
        return "arm"
    elif abi == "arm64-v8a":
        return "arm64"
    else:
        return abi


def abi_to_llvm_arch(abi):
    if abi.startswith("armeabi"):
        return "arm"
    elif abi == "arm64-v8a":
        return "aarch64"
    elif abi == "x86":
        return "i386"
    else:
        return "x86_64"


def get_llvm_host_name():
    platform = sys.platform
    if platform.startswith("win"):
        return "windows-x86_64"
    elif platform.startswith("darwin"):
        return "darwin-x86_64"
    else:
        return "linux-x86_64"


def get_python_executable(toolchain_path):
    if sys.platform.startswith("win"):
        return os.path.join(toolchain_path, "python3", "python.exe")
    else:
        return os.path.join(toolchain_path, "python3", "bin", "python3")


def get_lldb_path(toolchain_path):
    for lldb_name in ["lldb.sh", "lldb.cmd", "lldb", "lldb.exe"]:
        debugger_path = os.path.join(toolchain_path, "bin", lldb_name)
        if os.path.isfile(debugger_path):
            return debugger_path
    return None


def get_llvm_package_version(llvm_toolchain_dir):
    version_file_path = os.path.join(llvm_toolchain_dir, "AndroidVersion.txt")
    try:
        version_file = open(version_file_path, "r")
    except IOError:
        error(
            "Failed to open llvm package version file: '{}'.".format(version_file_path)
        )

    with version_file:
        return version_file.readline().strip()


def get_debugger_server_path(
    args, package_name, app_data_dir, arch, server_name, local_path
):
    app_debugger_server_path = "{}/lib/{}".format(app_data_dir, server_name)
    cmd = ["ls", app_debugger_server_path, "2>/dev/null"]
    cmd = get_run_as_cmd(package_name, cmd)
    (rc, _, _) = args.device.shell_nocheck(cmd)
    if rc == 0:
        log("Found app {}: {}".format(server_name, app_debugger_server_path))
        return app_debugger_server_path

    # We need to upload our debugger server
    log(
        "App {} not found at {}, uploading.".format(
            server_name, app_debugger_server_path
        )
    )
    remote_path = "/data/local/tmp/{}-{}".format(arch, server_name)
    args.device.push(local_path, remote_path)

    # Copy debugger server into the data directory on M+, because selinux prevents
    # execution of binaries directly from /data/local/tmp.
    if get_api_level(args.device) >= 23:
        destination = "{}/{}-{}".format(app_data_dir, arch, server_name)
        log("Copying {} to {}.".format(server_name, destination))
        cmd = [
            "cat",
            remote_path,
            "|",
            "run-as",
            package_name,
            "sh",
            "-c",
            "'cat > {}'".format(destination),
        ]
        (rc, _, _) = args.device.shell_nocheck(cmd)
        if rc != 0:
            error("Failed to copy {} to {}.".format(server_name, destination))
        (rc, _, _) = args.device.shell_nocheck(
            ["run-as", package_name, "chmod", "700", destination]
        )
        if rc != 0:
            error("Failed to chmod {} at {}.".format(server_name, destination))

        remote_path = destination

    log("Uploaded {} to {}".format(server_name, remote_path))
    return remote_path


def pull_binaries(device, out_dir, app_64bit):
    required_files = []
    libraries = ["libc.so", "libm.so", "libdl.so"]

    if app_64bit:
        required_files = ["/system/bin/app_process64", "/system/bin/linker64"]
        library_path = "/system/lib64"
    else:
        required_files = ["/system/bin/linker"]
        library_path = "/system/lib"

    for library in libraries:
        required_files.append(posixpath.join(library_path, library))

    for required_file in required_files:
        # os.path.join not used because joining absolute paths will pick the last one
        local_path = os.path.realpath(out_dir + required_file)
        local_dirname = os.path.dirname(local_path)
        if not os.path.isdir(local_dirname):
            os.makedirs(local_dirname)
        log("Pulling '{}' to '{}'".format(required_file, local_path))
        device.pull(required_file, local_path)

    # /system/bin/app_process is 32-bit on 32-bit devices, but a symlink to
    # app_process64 on 64-bit. If we need the 32-bit version, try to pull
    # app_process32, and if that fails, pull app_process.
    if not app_64bit:
        destination = os.path.realpath(out_dir + "/system/bin/app_process")
        try:
            device.pull("/system/bin/app_process32", destination)
        except:
            device.pull("/system/bin/app_process", destination)


def generate_lldb_script(
    args, sysroot, binary_path, app_64bit, jdb_pid, llvm_toolchain_dir
):
    lldb_commands = []
    solib_search_paths = [
        "{}/system/bin".format(sysroot),
        "{}/system/lib{}".format(sysroot, "64" if app_64bit else ""),
    ]
    lldb_commands.append(
        "settings append target.exec-search-paths {}".format(
            " ".join(solib_search_paths)
        )
    )

    lldb_commands.append("target create '{}'".format(binary_path))
    lldb_commands.append("target modules search-paths add / {}/".format(sysroot))

    lldb_commands.append("gdb-remote {}".format(args.port))
    if jdb_pid is not None:
        # After we've interrupted the app, reinvoke ndk-gdb.py to start jdb and
        # wake up the app.
        lldb_commands.append(
            """
script
def start_jdb_to_unblock_app():
  import subprocess
  subprocess.Popen({})

start_jdb_to_unblock_app()
exit()
    """.format(
                repr(
                    [
                        # We can't use sys.executable because it is the python2.
                        # lldb wrapper will set PYTHONHOME to point to python3.
                        get_python_executable(llvm_toolchain_dir),
                        os.path.realpath(__file__),
                        "--internal-wakeup-pid-with-jdb",
                        args.device.adb_path,
                        args.device.serial,
                        args.jdb_cmd,
                        str(jdb_pid),
                        str(bool(args.verbose)),
                    ]
                )
            )
        )

    if args.tui:
        lldb_commands.append("gui")

    if args.exec_file is not None:
        try:
            exec_file = open(args.exec_file, "r")
        except IOError:
            error("Failed to open lldb exec file: '{}'.".format(args.exec_file))

        with exec_file:
            lldb_commands.append(exec_file.read())

    return "\n".join(lldb_commands)


def generate_gdb_script(
    args, sysroot, binary_path, app_64bit, jdb_pid, connect_timeout=5
):
    if sys.platform.startswith("win"):
        # GDB expects paths to use forward slashes.
        sysroot = sysroot.replace("\\", "/")
        binary_path = binary_path.replace("\\", "/")

    gdb_commands = "set osabi GNU/Linux\n"
    gdb_commands += "file '{}'\n".format(binary_path)

    solib_search_path = [sysroot, "{}/system/bin".format(sysroot)]
    if app_64bit:
        solib_search_path.append("{}/system/lib64".format(sysroot))
    else:
        solib_search_path.append("{}/system/lib".format(sysroot))
    solib_search_path = os.pathsep.join(solib_search_path)
    gdb_commands += "set solib-absolute-prefix {}\n".format(sysroot)
    gdb_commands += "set solib-search-path {}\n".format(solib_search_path)

    # Try to connect for a few seconds, sometimes the device gdbserver takes
    # a little bit to come up, especially on emulators.
    gdb_commands += """
python

def target_remote_with_retry(target, timeout_seconds):
  import time
  end_time = time.time() + timeout_seconds
  while True:
    try:
      gdb.execute('target remote ' + target)
      return True
    except gdb.error as e:
      time_left = end_time - time.time()
      if time_left < 0 or time_left > timeout_seconds:
        print("Error: unable to connect to device.")
        print(e)
        return False
      time.sleep(min(0.25, time_left))

target_remote_with_retry(':{}', {})

end
""".format(
        args.port, connect_timeout
    )

    if jdb_pid is not None:
        # After we've interrupted the app, reinvoke ndk-gdb.py to start jdb and
        # wake up the app.
        gdb_commands += """
python
def start_jdb_to_unblock_app():
  import subprocess
  subprocess.Popen({})
start_jdb_to_unblock_app()
end
    """.format(
            repr(
                [
                    sys.executable,
                    os.path.realpath(__file__),
                    "--internal-wakeup-pid-with-jdb",
                    args.device.adb_path,
                    args.device.serial,
                    args.jdb_cmd,
                    str(jdb_pid),
                    str(bool(args.verbose)),
                ]
            )
        )

    if args.exec_file is not None:
        try:
            exec_file = open(args.exec_file, "r")
        except IOError:
            error("Failed to open GDB exec file: '{}'.".format(args.exec_file))

        with exec_file:
            gdb_commands += exec_file.read()

    return gdb_commands


def start_jdb(adb_path, serial, jdb_cmd, pid, verbose):
    pid = int(pid)
    device = adb.get_device(serial, adb_path=adb_path)
    if verbose == "True":
        enable_verbose_logging()

    log("Starting jdb to unblock application.")

    # Do setup stuff to keep ^C in the parent from killing us.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    windows = sys.platform.startswith("win")
    if not windows:
        os.setpgrp()

    jdb_port = 65534
    device.forward("tcp:{}".format(jdb_port), "jdwp:{}".format(pid))
    jdb_cmd = [
        jdb_cmd,
        "-connect",
        "com.sun.jdi.SocketAttach:hostname=localhost,port={}".format(jdb_port),
    ]

    flags = subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0
    jdb = subprocess.Popen(
        jdb_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )

    # Wait until jdb can communicate with the app. Once it can, the app will
    # start polling for a Java debugger (e.g. every 200ms). We need to wait
    # a while longer then so that the app notices jdb.
    jdb_magic = "__verify_jdb_has_started__"
    jdb.stdin.write('print "{}"\n'.format(jdb_magic).encode("utf-8"))
    saw_magic_str = False
    while True:
        line = jdb.stdout.readline()
        if line == "":
            break
        log("jdb output: " + line.rstrip())
        if jdb_magic in line and not saw_magic_str:
            saw_magic_str = True
            time.sleep(0.3)
            jdb.stdin.write("exit\n")
    jdb.wait()
    if saw_magic_str:
        log("JDB finished unblocking application.")
    else:
        log("error: did not find magic string in JDB output.")


def main():
    if sys.argv[1:2] == ["--internal-wakeup-pid-with-jdb"]:
        return start_jdb(*sys.argv[2:])

    args = handle_args()
    device = args.device
    use_lldb = not args.no_lldb

    if not use_lldb:
        print("WARNING: --no-lldb was used but GDB is no longer supported.")
        print("GDB will be used, but will be removed in the next release.")

    if device is None:
        error("Could not find a unique connected device/emulator.")

    # Warn on old Pixel C firmware (b/29381985). Newer devices may have Yama
    # enabled but still work with ndk-gdb (b/19277529).
    yama_check = device.shell_nocheck(
        ["cat", "/proc/sys/kernel/yama/ptrace_scope", "2>/dev/null"]
    )
    if (
        yama_check[0] == 0
        and yama_check[1].rstrip() not in ["", "0"]
        and (device.get_prop("ro.build.product"), device.get_prop("ro.product.name"))
        == ("dragon", "ryu")
    ):
        print(
            "WARNING: The device uses Yama ptrace_scope to restrict debugging. ndk-gdb will"
        )
        print(
            "    likely be unable to attach to a process. With root access, the restriction"
        )
        print(
            "    can be lifted by writing 0 to /proc/sys/kernel/yama/ptrace_scope. Consider"
        )
        print("    upgrading your Pixel C to MXC89L or newer, where Yama is disabled.")

    adb_version = subprocess.check_output(device.adb_cmd + ["version"]).decode()
    log("ADB command used: '{}'".format(" ".join(device.adb_cmd)))
    log("ADB version: {}".format(" ".join(adb_version.splitlines())))

    project = find_project(args)
    if args.package_name:
        log("Attaching to specified package: {}".format(args.package_name))
    else:
        parse_manifest(args)

    pkg_name = args.package_name

    if args.launch is False:
        log("Attaching to existing application process.")
    else:
        args.launch = select_target(args)
        log("Selected target activity: '{}'".format(args.launch))

    abi = fetch_abi(args)
    arch = abi_to_arch(abi)

    out_dir = os.path.join(project, (dump_var(args, "TARGET_OUT", abi)))
    out_dir = os.path.realpath(out_dir)

    app_data_dir = get_app_data_dir(args, pkg_name)

    llvm_toolchain_dir = os.path.join(
        NDK_PATH, "toolchains", "llvm", "prebuilt", get_llvm_host_name()
    )
    if use_lldb:
        server_local_path = os.path.join(
            llvm_toolchain_dir,
            "lib64",
            "clang",
            get_llvm_package_version(llvm_toolchain_dir),
            "lib",
            "linux",
            abi_to_llvm_arch(abi),
            "lldb-server",
        )
        server_name = "lldb-server"
    else:
        server_local_path = "{}/prebuilt/android-{}/gdbserver/gdbserver"
        server_local_path = server_local_path.format(NDK_PATH, arch)
        server_name = "gdbserver"
    if not os.path.exists(server_local_path):
        error("Can not find {}: {}".format(server_name, server_local_path))
    log("Using {}: {}".format(server_name, server_local_path))
    debugger_server_path = get_debugger_server_path(
        args, pkg_name, app_data_dir, arch, server_name, server_local_path
    )

    # Kill the process and gdbserver if requested.
    if args.force:
        kill_pids = gdbrunner.get_pids(device, debugger_server_path)
        if args.launch:
            kill_pids += gdbrunner.get_pids(device, pkg_name)
        kill_pids = [str(pid) for pid in kill_pids]
        if kill_pids:
            log("Killing processes: {}".format(", ".join(kill_pids)))
            device.shell_nocheck(["run-as", pkg_name, "kill", "-9"] + kill_pids)

    # Launch the application if needed, and get its pid
    if args.launch:
        am_cmd = ["am", "start"]
        if not args.nowait:
            am_cmd.append("-D")
        component_name = "{}/{}".format(pkg_name, args.launch)
        am_cmd.append(component_name)
        log("Launching activity {}...".format(component_name))
        (rc, _, _) = device.shell_nocheck(am_cmd)
        if rc != 0:
            error("Failed to start {}".format(component_name))

        if args.delay > 0.0:
            log("Sleeping for {} seconds.".format(args.delay))
            time.sleep(args.delay)

    pids = gdbrunner.get_pids(device, pkg_name)
    if len(pids) == 0:
        error("Failed to find running process '{}'".format(pkg_name))
    if len(pids) > 1:
        error("Multiple running processes named '{}'".format(pkg_name))
    pid = pids[0]

    # Pull the linker, zygote, and notable system libraries
    app_64bit = "64" in abi
    pull_binaries(device, out_dir, app_64bit)
    if app_64bit:
        zygote_path = os.path.join(out_dir, "system", "bin", "app_process64")
    else:
        zygote_path = os.path.join(out_dir, "system", "bin", "app_process")

    # Start gdbserver.
    debug_socket = posixpath.join(app_data_dir, "debug_socket")
    log("Starting {}...".format(server_name))
    gdbrunner.start_gdbserver(
        device,
        None,
        debugger_server_path,
        target_pid=pid,
        run_cmd=None,
        debug_socket=debug_socket,
        port=args.port,
        run_as_cmd=["run-as", pkg_name],
        lldb=use_lldb,
    )

    # Start jdb to unblock the application if necessary.
    jdb_pid = pid if (args.launch and not args.nowait) else None

    # Start gdb.
    if use_lldb:
        script_commands = generate_lldb_script(
            args, out_dir, zygote_path, app_64bit, jdb_pid, llvm_toolchain_dir
        )
        debugger_path = get_lldb_path(llvm_toolchain_dir)
        flags = []
    else:
        script_commands = generate_gdb_script(
            args, out_dir, zygote_path, app_64bit, jdb_pid
        )
        debugger_path = os.path.join(ndk_bin_path(), "gdb")
        flags = ["--tui"] if args.tui else []
    print(debugger_path)
    gdbrunner.start_gdb(debugger_path, script_commands, flags, lldb=use_lldb)


if __name__ == "__main__":
    main()
