from typing import Optional

from ndk.abis import Abi
from ndk.test.buildtest.case import Test


def build_unsupported(test: Test) -> Optional[str]:
    if test.config.abi != Abi('armeabi-v7a'):
        return test.config.abi
    return None


def extra_cmake_flags() -> list[str]:
    return ['-DANDROID_ARM_NEON=ON']
