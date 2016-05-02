#!/usr/bin/env python
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
"""Creates a toolchain installation for a given Android target.

The output of this tool is a more typical cross-compiling toolchain. It is
indended to be used with existing build systems such as autotools.
"""
import argparse
import atexit
import inspect
import logging
import platform
import os
import shutil
import sys
import tempfile
import textwrap


THIS_DIR = os.path.realpath(os.path.dirname(__file__))
NDK_DIR = os.path.realpath(os.path.join(THIS_DIR, '../..'))


def logger():
    return logging.getLogger(__name__)


def check_ndk():
    checks = [
        'build/core',
        'prebuilt',
        'platforms',
        'toolchains',
    ]

    for check in checks:
        check_path = os.path.join(NDK_DIR, check)
        if not os.path.exists(check_path):
            sys.exit('Failed sanity check: missing {}'.format(check_path))


def get_triple(arch):
    return {
        'arm': 'arm-linux-androideabi',
        'arm64': 'aarch64-linux-android',
        'mips': 'mipsel-linux-android',
        'mips64': 'mips64el-linux-android',
        'x86': 'i686-linux-android',
        'x86_64': 'x86_64-linux-android',
    }[arch]


def get_abis(arch):
    return {
        'arm': ['armeabi', 'armeabi-v7a'],
        'arm64': ['arm64-v8a'],
        'mips': ['mips'],
        'mips64': ['mips64'],
        'x86': ['x86'],
        'x86_64': ['x86_64'],
    }[arch]


def get_host_tag_or_die():
    if platform.system() == 'Linux':
        return 'linux-x86_64'
    elif platform.system() == 'Darwin':
        return 'darwin-x86_64'
    elif platform.system() == 'Windows':
        host_tag = 'windows-x86_64'
        if not os.path.exists(os.path.join(NDK_DIR, 'prebuilt', host_tag)):
            host_tag = 'windows'
        return host_tag
    sys.exit('Unsupported platform: ' + platform.system())


def get_sysroot_path_or_die(arch, api_level):
    platforms_root_path = os.path.join(NDK_DIR, 'platforms')
    platform_path = os.path.join(
        platforms_root_path, 'android-{}'.format(api_level))

    if not os.path.exists(platform_path):
        valid_platforms = os.listdir(platforms_root_path)
        sys.exit('Could not find {}. Valid platforms:\n{}'.format(
            platform_path, '\n'.join(valid_platforms)))

    sysroot_path = os.path.join(platform_path, 'arch-' + arch)
    if not os.path.exists(sysroot_path):
        sys.exit('Could not find {}'.format(sysroot_path))

    return sysroot_path


def get_gcc_path_or_die(arch, host_tag):
    toolchain = {
        'arm': 'arm-linux-androideabi',
        'arm64': 'aarch64-linux-android',
        'mips': 'mipsel-linux-android',
        'mips64': 'mips64el-linux-android',
        'x86': 'x86',
        'x86_64': 'x86_64',
    }[arch] + '-4.9'

    gcc_toolchain_path = os.path.join(
        NDK_DIR, 'toolchains', toolchain, 'prebuilt', host_tag)
    if not os.path.exists(gcc_toolchain_path):
        sys.exit('Could not find GCC/binutils: {}'.format(gcc_toolchain_path))
    return gcc_toolchain_path


def get_clang_path_or_die(host_tag):
    clang_toolchain_path = os.path.join(
        NDK_DIR, 'toolchains/llvm/prebuilt', host_tag)
    if not os.path.exists(clang_toolchain_path):
        sys.exit('Could not find Clang: {}'.format(clang_toolchain_path))
    return clang_toolchain_path


def copy_directory_contents(src, dst):
    for root, dirs, files in os.walk(src):
        subdir = os.path.relpath(root, src)
        dst_dir = os.path.join(dst, subdir)
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)

        # This makes sure we copy even empty directories. We don't actually
        # need it, but for now it lets us diff between our result and the
        # legacy tool.
        for d in dirs:
            d_path = os.path.join(root, d)
            if os.path.islink(d_path):
                linkto = os.readlink(d_path)
                dst_file = os.path.join(dst_dir, d)
                logger().debug('Symlinking %s to %s', dst_file, linkto)
                os.symlink(linkto, dst_file)
            else:
                new_dir = os.path.join(dst_dir, d)
                if not os.path.exists(new_dir):
                    logger().debug('Making directory %s', new_dir)
                    os.makedirs(new_dir)

        for f in files:
            src_file = os.path.join(root, f)
            if os.path.islink(src_file):
                linkto = os.readlink(src_file)
                dst_file = os.path.join(dst_dir, f)
                logger().debug('Symlinking %s to %s', dst_file, linkto)
                os.symlink(linkto, dst_file)
            else:
                logger().debug('Copying %s', src_file)
                shutil.copy2(src_file, dst_dir)


def make_clang_scripts(install_dir, triple, windows):
    with open(os.path.join(install_dir, 'AndroidVersion.txt')) as version_file:
        major, minor, _build = version_file.read().strip().split('.')

    version_number = major + minor

    exe = ''
    if windows:
        exe = '.exe'

    bin_dir = os.path.join(install_dir, 'bin')
    shutil.move(os.path.join(bin_dir, 'clang' + exe),
                os.path.join(bin_dir, 'clang{}'.format(version_number) + exe))
    shutil.move(os.path.join(bin_dir, 'clang++' + exe),
                os.path.join(bin_dir, 'clang{}++'.format(
                    version_number) + exe))

    arch, os_name, env = triple.split('-')
    if arch == 'arm':
        arch = 'armv7a'  # Target armv7, not armv5.

    target = '-'.join([arch, 'none', os_name, env])
    flags = '-target {} --sysroot `dirname $0`/../sysroot'.format(target)

    with open(os.path.join(install_dir, 'bin/clang'), 'w') as clang:
        clang.write(textwrap.dedent("""\
            #!/bin/bash
            if [ "$1" != "-cc1" ]; then
                `dirname $0`/clang{version} {flags} "$@"
            else
                # target/triple already spelled out.
                `dirname $0`/clang{version} "$@"
            fi
        """.format(version=version_number, flags=flags)))

    with open(os.path.join(install_dir, 'bin/clang++'), 'w') as clangpp:
        clangpp.write(textwrap.dedent("""\
            #!/bin/bash
            if [ "$1" != "-cc1" ]; then
                `dirname $0`/clang{version}++ {flags} "$@"
            else
                # target/triple already spelled out.
                `dirname $0`/clang{version}++ "$@"
            fi
        """.format(version=version_number, flags=flags)))

    shutil.copy2(os.path.join(install_dir, 'bin/clang'),
                 os.path.join(install_dir, 'bin', triple + '-clang'))
    shutil.copy2(os.path.join(install_dir, 'bin/clang++'),
                 os.path.join(install_dir, 'bin', triple + '-clang++'))

    if windows:
        flags = '-target {} --sysroot %~dp0\\..\\sysroot'.format(target)
        clangbat_path = os.path.join(install_dir, 'bin/clang.cmd')
        with open(clangbat_path, 'w') as clangbat:
            clangbat.write(textwrap.dedent("""\
                @echo off
                if "%1" == "-cc1" goto :L
                %~dp0\\clang{version}.exe {flags} %*
                if ERRORLEVEL 1 exit /b 1
                goto :done
                :L
                rem target/triple already spelled out.
                %~dp0\\clang{version}.exe %*
                if ERRORLEVEL 1 exit /b 1
                :done
            """.format(version=version_number, flags=flags)))

        clangbatpp_path = os.path.join(install_dir, 'bin/clang++.cmd')
        with open(clangbatpp_path, 'w') as clangbatpp:
            clangbatpp.write(textwrap.dedent("""\
                @echo off
                if "%1" == "-cc1" goto :L
                %~dp0\\clang{version}++.exe {flags} %*
                if ERRORLEVEL 1 exit /b 1
                goto :done
                :L
                rem target/triple already spelled out.
                %~dp0\\clang{version}++.exe %*
                if ERRORLEVEL 1 exit /b 1
                :done
            """.format(version=version_number, flags=flags)))

        shutil.copy2(os.path.join(install_dir, 'bin/clang.cmd'),
                     os.path.join(install_dir, 'bin', triple + '-clang.cmd'))
        shutil.copy2(os.path.join(install_dir, 'bin/clang++.cmd'),
                     os.path.join(install_dir, 'bin', triple + '-clang++.cmd'))


def copy_stl_abi_headers(src_dir, dst_dir, gcc_ver, triple, abi, thumb=False):
    abi_src_dir = os.path.join(
        src_dir, 'libs', abi, 'include/bits')

    # Most architectures simply install to bits. The arm32 flavors are finicky,
    # and we need bits/, thumb/bits, armv7-a/bits, and armv7-a/thumb/bits.
    bits_dst_dir = 'bits'
    if thumb:
        bits_dst_dir = os.path.join('thumb', bits_dst_dir)
    if abi == 'armeabi-v7a':
        bits_dst_dir = os.path.join('armv7-a', bits_dst_dir)
    abi_dst_dir = os.path.join(
        dst_dir, 'include/c++', gcc_ver, triple, bits_dst_dir)

    shutil.copytree(abi_src_dir, abi_dst_dir)


def get_src_libdir(src_dir, abi, thumb=False):
    src_libdir = os.path.join(src_dir, 'libs', abi)
    if thumb:
        src_libdir = os.path.join(src_libdir, 'thumb')
    return src_libdir


def get_dest_libdir(dst_dir, triple, abi, thumb=False):
    dst_libdir = os.path.join(dst_dir, triple, 'lib')
    if abi.startswith('armeabi-v7a'):
        dst_libdir = os.path.join(dst_libdir, 'armv7-a')
    if thumb:
        dst_libdir = os.path.join(dst_libdir, 'thumb')
    return dst_libdir


def copy_gnustl_libs(src_dir, dst_dir, triple, abi, thumb=False):
    src_libdir = get_src_libdir(src_dir, abi, thumb)
    dst_libdir = get_dest_libdir(dst_dir, triple, abi, thumb)

    logger().debug('Copying %s libs to %s', abi + ' thumb' if thumb else abi,
                   dst_libdir)

    if not os.path.exists(dst_libdir):
        os.makedirs(dst_libdir)

    shutil.copy2(os.path.join(src_libdir, 'libgnustl_shared.so'), dst_libdir)
    shutil.copy2(os.path.join(src_libdir, 'libsupc++.a'), dst_libdir)

    # Copy libgnustl_static.a to libstdc++.a since that's what the world
    # expects. Can't do this reliably with libgnustl_shared.so because the
    # SONAME is wrong.
    shutil.copy2(os.path.join(src_libdir, 'libgnustl_static.a'),
                 os.path.join(dst_libdir, 'libstdc++.a'))


def copy_stlport_libs(src_dir, dst_dir, triple, abi, thumb=False):
    src_libdir = get_src_libdir(src_dir, abi, thumb)
    dst_libdir = get_dest_libdir(dst_dir, triple, abi, thumb)

    if not os.path.exists(dst_libdir):
        os.makedirs(dst_libdir)

    shutil.copy2(os.path.join(src_libdir, 'libstlport_shared.so'), dst_libdir)
    shutil.copy2(os.path.join(src_libdir, 'libstlport_static.a'),
                 os.path.join(dst_libdir, 'libstdc++.a'))


def create_toolchain(install_path, arch, gcc_path, clang_path, sysroot_path,
                     stl, host_tag):
    copy_directory_contents(gcc_path, install_path)
    copy_directory_contents(clang_path, install_path)
    triple = get_triple(arch)
    make_clang_scripts(install_path, triple, host_tag.startswith('windows'))
    shutil.copytree(sysroot_path, os.path.join(install_path, 'sysroot'))

    prebuilt_path = os.path.join(NDK_DIR, 'prebuilt', host_tag)
    copy_directory_contents(prebuilt_path, install_path)

    toolchain_lib_dir = os.path.join(gcc_path, 'lib/gcc', triple)
    dirs = os.listdir(toolchain_lib_dir)
    assert len(dirs) == 1
    gcc_ver = dirs[0]

    cxx_headers = os.path.join(install_path, 'include/c++', gcc_ver)

    if stl == 'gnustl':
        gnustl_dir = os.path.join(NDK_DIR, 'sources/cxx-stl/gnu-libstdc++/4.9')
        shutil.copytree(os.path.join(gnustl_dir, 'include'), cxx_headers)

        for abi in get_abis(arch):
            copy_stl_abi_headers(gnustl_dir, install_path, gcc_ver, triple,
                                 abi)
            copy_gnustl_libs(gnustl_dir, install_path, triple, abi)
            if arch == 'arm':
                copy_stl_abi_headers(gnustl_dir, install_path,
                                     gcc_ver, triple, abi, thumb=True)
                copy_gnustl_libs(gnustl_dir, install_path,
                                 triple, abi, thumb=True)
    elif stl == 'libc++':
        libcxx_dir = os.path.join(NDK_DIR, 'sources/cxx-stl/llvm-libc++')
        libcxxabi_dir = os.path.join(NDK_DIR, 'sources/cxx-stl/llvm-libc++abi')
        support_dir = os.path.join(NDK_DIR, 'sources/android/support')
        copy_directory_contents(os.path.join(libcxx_dir, 'libcxx/include'),
                                cxx_headers)
        copy_directory_contents(os.path.join(support_dir, 'include'),
                                cxx_headers)

        # I have no idea why we need this, but the old one does it too.
        copy_directory_contents(
            os.path.join(libcxxabi_dir, 'libcxxabi/include'),
            os.path.join(install_path, 'include/llvm-libc++abi/include'))

        headers = [
            'cxxabi.h',
            '__cxxabi_config.h',
            'libunwind.h',
            'unwind.h',
        ]
        for header in headers:
            shutil.copy2(
                os.path.join(libcxxabi_dir, 'libcxxabi/include', header),
                os.path.join(cxx_headers, header))

        for abi in get_abis(arch):
            src_libdir = get_src_libdir(libcxx_dir, abi)
            dest_libdir = get_dest_libdir(install_path, triple, abi)
            shutil.copy2(os.path.join(src_libdir, 'libc++_shared.so'),
                         dest_libdir)
            shutil.copy2(os.path.join(src_libdir, 'libc++_static.a'),
                         os.path.join(dest_libdir, 'libstdc++.a'))
    elif stl == 'stlport':
        stlport_dir = os.path.join(NDK_DIR, 'sources/cxx-stl/stlport')
        gabixx_dir = os.path.join(NDK_DIR, 'sources/cxx-stl/gabi++')

        copy_directory_contents(
            os.path.join(stlport_dir, 'stlport'), cxx_headers)

        # Same as for libc++. Not sure why we have this extra directory, but
        # keep the cruft for diff.
        copy_directory_contents(
            os.path.join(gabixx_dir, 'include'),
            os.path.join(install_path, 'include/gabi++/include'))

        headers = [
            'cxxabi.h',
            'unwind.h',
            'unwind-arm.h',
            'unwind-itanium.h',
            'gabixx_config.h',
        ]
        for header in headers:
            shutil.copy2(
                os.path.join(gabixx_dir, 'include', header),
                os.path.join(cxx_headers, header))

        for abi in get_abis(arch):
            copy_stlport_libs(stlport_dir, install_path, triple, abi)
            if arch == 'arm':
                copy_stlport_libs(stlport_dir, install_path, triple, abi,
                                  thumb=True)
    else:
        raise ValueError(stl)

    # Not needed for every STL, but the old one does this. Keep it for the sake
    # of diff. Done at the end so copytree works.
    cxx_target_headers = os.path.join(cxx_headers, triple)
    if not os.path.exists(cxx_target_headers):
        os.makedirs(cxx_target_headers)


def parse_args():
    parser = argparse.ArgumentParser(
        description=inspect.getdoc(sys.modules[__name__]))

    parser.add_argument(
        '--arch', required=True,
        choices=('arm', 'arm64', 'mips', 'mips64', 'x86', 'x86_64'))
    parser.add_argument(
        '--api', type=int, help='Target the given API version.')
    parser.add_argument(
        '--stl', choices=('gnustl', 'libc++', 'stlport'), default='gnustl',
        help='C++ STL to use.')

    parser.add_argument(
        '--force', action='store_true',
        help='Remove existing installation directory if it exists.')
    parser.add_argument(
        '-v', '--verbose', action='count', help='Increase output verbosity.')

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        '--package-dir', type=os.path.realpath, default=os.getcwd(),
        help=('Build a tarball and install it to the given directory. If '
              'neither --package-dir nor --install-dir is specified, a '
              'tarball will be created and installed to the current '
              'directory.'))
    output_group.add_argument(
        '--install-dir', type=os.path.realpath,
        help='Install toolchain to the given directory instead of packaging.')

    return parser.parse_args()


def main():
    args = parse_args()

    if args.verbose == 1:
        logging.basicConfig(level=logging.INFO)
    elif args.verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)

    check_ndk()

    lp32 = args.arch in ('arm', 'mips', 'x86')
    min_api = 9 if lp32 else 21
    api = args.api
    if api is None:
        api = min_api
    elif api < min_api:
        sys.exit('{} is less than minimum platform for {} ({})'.format(
            api, args.arch, min_api))

    host_tag = get_host_tag_or_die()
    triple = get_triple(args.arch)
    sysroot_path = get_sysroot_path_or_die(args.arch, api)
    gcc_path = get_gcc_path_or_die(args.arch, host_tag)
    clang_path = get_clang_path_or_die(host_tag)

    if args.install_dir is not None:
        install_path = args.install_dir
        if os.path.exists(install_path):
            if args.force:
                logger().info('Cleaning installation directory %s',
                              install_path)
                shutil.rmtree(install_path)
            else:
                sys.exit('Installation directory already exists. Use --force.')
    else:
        tempdir = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, tempdir)
        install_path = os.path.join(tempdir, triple)

    create_toolchain(install_path, args.arch, gcc_path, clang_path,
                     sysroot_path, args.stl, host_tag)

    # TODO(danalbert): Do the packaging step if we were not installing.


if __name__ == '__main__':
    main()
