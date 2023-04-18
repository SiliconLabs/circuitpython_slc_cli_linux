import re

VERSION_REGEX = re.compile(r"\d(?:\.\d)*")


class Version:
    """A mini replication of OSGI version class in Java.

    Allows comparison of version identifier strings properly -- as in,
    the versions 5.0 and 5.0.0 are considered the same."""

    version = ""

    def __init__(self, vers_str):
        self.version = vers_str

    def __eq__(self, other):
        if isinstance(other, Version):
            return _versionCompare(self.version, other.version)
        return NotImplemented

    def __hash__(self):
        return hash(_versionNormalise(self.version))


def _isVersion(data):
    """Returns whether some input is a valid version string."""
    return VERSION_REGEX.match(data.strip())


def _versionCompare(first_verse, second_verse):
    first_normalised = _versionNormalise(first_verse)
    second_normalised = _versionNormalise(second_verse)
    return first_normalised == second_normalised


def _versionNormalise(vers):
    """Give a version string all four version parts, padding with 0's.
    For instance, 2.7 turns int 2.7.0.0 Essentially explicitly sets the
    majour, minor, patch, and qualifier versions for string comparison.
    In the event (which really shouldn't happen if used with Simplicity Studio)
    that there are more version specifiers, this just returns the string as
    is."""
    decimals = vers.count(".")
    missing_decimals = 3 - decimals
    if missing_decimals < 0:
        # if this came from a .version file I'm Madonna.
        return vers

    zero_pad = "".join(".0" * missing_decimals)
    return vers + zero_pad
