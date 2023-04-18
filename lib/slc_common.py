#!/usr/bin/env python

import argparse
import os
import sys
import zipfile
import errno
import subprocess
from distutils.version import StrictVersion

# Duplicated in slc_download.py
"""Indicates if this is running in either windows, or the host is windows."""
IS_WIN32 = "win32" in sys.platform or "cygwin" in sys.platform

"""Indicates if this is running in Cygwin. """
IS_CYGWIN = "cygwin" in sys.platform


JAVA_EXE = "java.exe" if IS_WIN32 else "java"

# JVM Constants
EXTRACT_JVM_VERSION_REGEX = r"version \"([0-9]+\.[0-9]+\.[0-9]+)"
JAVA_VERSION_11 = StrictVersion("11.0")
JAVA_11_DOWNLOAD_LINK = (
    "https://docs.aws.amazon.com/corretto/latest/corretto-11-ug/downloads-list.html"
)


def _verifyJvm(java_location, debug):
    """Verify that the installed JVM would correctly run UC.
    :param java_location path to the Java instance that is being verified.
    :param debug if true, prints additional debugging information."""
    # check jvm bitsize

    java_version_output = _runJvmVersion(java_location)
    if debug:
        if java_version_output is None:
            print("vers. check failed")
        else:
            print("vers. check: " + java_version_output)
    bitsize = _findJvmBitsize(java_version_output)
    if bitsize == 32:
        print("A 32 bit JVM was detected.")
        return False
    elif bitsize != 64:
        print("Could not determine if JVM exists and is 64 bit.")
        return False
    if bitsize != 64:
        print(
            "Non-64 bit JVMs will cause issues with any "
            + "functions that end up requring python execution, such as "
            + "template generation and configuration validation."
        )
        return False

    # check jvm is Java 11
    valid = _checkJvmVersion(java_version_output, debug)
    return valid


def _checkJvmVersion(java_version_output, debug):
    """Determine if a jvm version string is high enough.

    This accepts the entire output of the java -version command. It parses
    the java version and ensures it is 11 or higher. Returns true if that
    is the case. Returns false if the version is too low.

    Throws a ValueError if the output doesn't contain the version information.
    """
    import re

    version_raw = re.search(EXTRACT_JVM_VERSION_REGEX, java_version_output).group(1)
    if debug:
        print("Computed JRE version: " + version_raw)
    try:
        version = StrictVersion(version_raw)
        if version < JAVA_VERSION_11:
            print("Java " + version_raw + " is too low. Java 11 is required")
            print(
                "Define the 'JAVA11_HOME' environment variable to point to your Java 11 install"
            )
            print("Or download a Java 11 JVM from " + JAVA_11_DOWNLOAD_LINK)
            return False
        else:
            return True
    except ValueError:
        print("Could not determine JVM version. It must be Java 11.")
        sys.stdout.flush()
        return False


def _runJvmVersion(java_location):
    """Run java -version and return output as a lowercase string.
    :param java_location location of java instance being used to run the command line
    Returns None if the call failed."""
    try:
        javaLoc = (
            "java" if java_location is None else os.path.join(java_location, JAVA_EXE)
        )
        version_process = subprocess.Popen(
            [javaLoc, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # out = version_process.stdout.read()
        out, err = version_process.communicate()
        status = version_process.wait()
        # kind of weird -- apparently java -version sometimes
        # sends output to stderr.....
        version_info = ""
        if out:
            version_info = out.decode("ascii").lower()
        elif err:
            version_info = err.decode("ascii").lower()

        if version_info != "":
            return version_info
        else:
            # no output? Well that's not good.
            print("Call to java -version produced no output " + str(status))
            return None
    except OSError as e:
        if e.errno == errno.ENOENT:
            print("'java' command cannot be found. A JVM must be installed.")
        else:
            raise
        return None
    except subprocess.CalledProcessError:
        return None


def _findJvmBitsize(java_version_output):
    """Determine if jvm is 64 bit.

    Returns an integer indicating bit size. 64 is intended. 32 means
    this won't work properly, and anything else means this won't work at all.
    """
    if java_version_output is None:
        return 0
    elif "64-bit" in java_version_output.lower():
        return 64
    else:
        return 32


def _calculateJavaLocation(arg=None, debug=False):
    """Based on an argument from the command line, determine which Java to used.

    :param arg argument (not argument list, the actual argument) of -pyJavaLocation
    as supplied to any entry point, if available. This may be omitted if the argument
    was not supplied.
    :return location of the Java runtime to use for launching the command line"""
    java_location = None

    argumentLoc = None
    suppliedFrom = None
    if arg is not None:
        argumentLoc = arg
        suppliedFrom = "-pyJavaLocation argument"
    elif "JAVA11_HOME" in os.environ:
        argumentLoc = os.environ["JAVA11_HOME"]
        suppliedFrom = "JAVA11_HOME environment variable"
    if argumentLoc is None:
        return

    # Validate that this path is correct
    calculatedLoc = argumentLoc
    if not os.path.exists(os.path.join(calculatedLoc, JAVA_EXE)):
        calculatedLoc = os.path.join(calculatedLoc, "bin")
    if not os.path.exists(os.path.join(calculatedLoc, JAVA_EXE)):
        print(
            "Supplied Java from "
            + suppliedFrom
            + " does not have executable at "
            + os.path.join(calculatedLoc, JAVA_EXE)
            + " or "
            + os.path.join(argumentLoc, JAVA_EXE)
        )
        exit(1)

    java_location = calculatedLoc
    if debug:
        print("Using Java at " + calculatedLoc + " from " + suppliedFrom)
    return java_location


def _exportLog(args):
    """Export debug information to a file.

    This exports any debug information that the Simplicity Studio UC devs
    might need to debug a failure in running UC. This intentionally
    does not launch UC since that may not be working for some reason.

    This currently only grabs the latest error log from the workspace
    since this is all that's been needed to debug previous problems.

    Please add extra logging as necessary.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-exportLogs", nargs='?', help="Export the debug information to a specific location")
    parser.add_argument("-data", required=False,
                        default="~/SimplicityStudio/uc_workspace/",
                        help="Change the data location. This controls where the log files will be and should be set to the same value as when you ran your script")
    parsedArgs = parser.parse_args(args)

    exportDir = str(parsedArgs.exportLogs or os.getcwd())
    dataDir = parsedArgs.data

    # MCUDT-18270 Get the Simplicity Studio and UC log files
    userDir = str(_getUserDir())
    exportDir = exportDir.replace("~", userDir)
    appLogFile = os.path.join(dataDir, ".metadata/.log").replace("~", userDir)
    ucLogFile = os.path.join(userDir, ".uc/uc.core.log")

    try:
        os.makedirs(exportDir)
    except:
        pass

    zipLoc = os.path.join(exportDir, "uc_log.zip")
    errWritten = False
    coreWritten = False
    with zipfile.ZipFile(zipLoc, "w") as newzip:
        # Try for each log file. If none of them existed, report that no logs were exported
        # and delete the .zip file (otherwise it would just be empty.)
        errWritten = _tryZipWrite(newzip, zipLoc, appLogFile, "error_log.log")
        coreWritten = _tryZipWrite(newzip, zipLoc, ucLogFile, "uc_core.log")

    if not errWritten and not coreWritten:
        print("No log files existed -- nothing to export.")
        os.remove(zipLoc)
    else:
        print("Export complete.")


def _tryZipWrite(zipfile, zipLoc, file, arcname):
    try:
        zipfile.write(file, arcname=arcname)
        print("Exporting " + file + " to " + zipLoc)
        return True
    except FileNotFoundError:
        print("Skipping " + str(file) + ": not found.")
        return False


def _getUserDir():
    """Return user directory in this session, in terms of Simplicity Studio.

    This is primarily different from os.path.expanduser('~') because of
    special Cygwin specific routines.
    """
    logPath = os.path.expanduser("~")
    if "cygwin" not in sys.platform:
        return logPath
    else:
        # yay Cygwin, let's assume the username folder is the same, and
        # replace the /home/ with /cygdrive/c/Users. This assumes a hell lot,
        # but we cannot access the windows registry from within here to get
        # the real home folder so this approximation will have to do.
        # TODO better ideas welcome. cygwinreg looked like a way to get this
        # but was not working correctly when initially attempted.
        logPath = logPath.replace("home/", "cygdrive/c/Users/", 1)
        print(
            "Cygwin detected -- cannot accurately determine windows home: "
            + "directory for current user. Guessing "
            + logPath
        )
        return logPath
