def match_unsupported(abi, platform, device_platform, toolchain, subtest=None):
    if abi not in ('armeabi', 'armeabi-v7a'):
        return abi
    return None
