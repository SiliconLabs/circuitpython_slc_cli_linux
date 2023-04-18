# Code taken from other open source projects

# This can be removed once https://github.com/tartley/colorama/pull/226 is merged
# and a new version of Colorama is updated
# Taken directly from
# https://github.com/tartley/colorama/pull/226/commits/04a00a3c19cd35222be3ab30cb4ba739ee319528
# an as-of-this-writing unmerged pull request to prevent ANSI stripping in git-bash
# and cygwin.
# Should be called with sys.stdout for our purposes.
# Modified only in formatting due to automatic formatting using black.
def is_msys_cygwin_tty(stream):
    # https://github.com/msys2/MINGW-packages/pull/2675/files
    try:
        import msvcrt
        import ctypes
        import sys
        import re

        if not hasattr(stream, "fileno"):
            return False

        if not hasattr(ctypes, "windll") or not hasattr(
            ctypes.windll.kernel32, "GetFileInformationByHandleEx"
        ):
            return False

        fileno = stream.fileno()
        handle = msvcrt.get_osfhandle(fileno)
        FileNameInfo = 2

        class FILE_NAME_INFO(ctypes.Structure):
            _fields_ = [
                ("FileNameLength", ctypes.c_ulong),
                ("FileName", ctypes.c_wchar * 40),
            ]

        info = FILE_NAME_INFO()
        ret = ctypes.windll.kernel32.GetFileInformationByHandleEx(
            handle, FileNameInfo, ctypes.byref(info), ctypes.sizeof(info)
        )
        if ret == 0:
            return False

        msys_pattern = r"\\msys-[0-9a-f]{16}-pty\d-(to|from)-master"
        cygwin_pattern = r"\\cygwin-[0-9a-f]{16}-pty\d-(to|from)-master"
        return (
            re.match(msys_pattern, info.FileName) is not None
            or re.match(cygwin_pattern, info.FileName) is not None
        )

    except ImportError:
        return False
