#!/usr/bin/env python3

"""Software Configuration Command Line Tool.

Entry point and library used for actually running the SLC software configuration
tools command line.
"""


import subprocess
import sys
import os
import json
import time
import shutil
import re

# This script uses requests, asyncio, websockets, and colorama.
# however, it is possible to launch slc directly such that these are not
# needed, so they are only imported in the methods in which they are required.

# ---- syspath changes in entry points allow this. ----
# pylint: disable=import-error
from slc_common import (
    IS_WIN32,
    IS_CYGWIN,
    _calculateJavaLocation,
    _exportLog,
    _getUserDir,
)
from slc_thirdparty import is_msys_cygwin_tty
from version import Version, _isVersion

# ---- End things flagged badly ----


UC_NAME_BASE = "slc-cli"


JAVA_LOCATION = None
DEBUG = False

# If true, indicates that when launching the command line, it should instead
# follow the rules defined
# https://confluence.silabs.com/pages/viewpage.action?spaceKey=SS&title=SLC+CLI+Productisation
DAEMON = True

# If explicitly set, indicates the value to send when making a new daemon -- effectively,
# this becomes -Dslc_cli_servlet_shutdown_minutes when the daemon is launched.
# has no effect if not running as a Daemon, and if the Daemon is already running,
# warns it won't take effect until the next time the daemon is started.
# Incompatible with DO_NOT_LAUNCH_DAEMON
DAEMON_CUSTOM_TIMEOUT = None

# If true, this will not request a websocket during the action/respond and will
# not provide any context for commands. In other words, only the REST response will
# be a factour, and server side will opt to send data there instead of to a websocket.
IGNORE_WEBSOCKETS = False

# end part of URI (including /ws preamble) that should be appended to host and
# port to get the websocket connection for the correct version of Simplicity Studio.
CLI_WS_URI = "/ws/uccli/feedback"

# Naming conventions used for the two different shared files representing a primary
# Simplicity Studio install vs the cli one we can spin up.
# Some features, such as Simplicity Studio project generation, are not available in the mini
# cli version packaged with this command line runner.
SHARED_FILE_MAIN = "mainstudio"
SHARED_FILE_CLI = "cli"

# If true, prevents this script from launching Simplicity Studio as a
# Daemon process, even if there is no currently
# running instance to connect to.
DO_NOT_LAUNCH_DAEMON = False

# Normally colorama is used for Windows and native ANSI support works for other
# systems. This is provided if the terminal just can't handle colour for whatever
# reason as a last-resort fallback so the output doesn't resemble abstract art.
COLOUR_FORCED_OFF = False

# References to repo contents shouldn't be dependent on location of python call
REPO_LOCATION = os.path.dirname(__file__)

# If set to true, this signals that the REST Url should be composed by a constant
# 'test' value, which the server can also ask for (allowing either development). Otherwise,
# the REST Url is composed of a version that is obtained from the same folder as the
# slc executable.
DEV_TESTING = False

# Whether this run should launch/use the Daemon serivce or not. This differs
# from DO_NOT_LAUNCH_DAEMON in that that command still used the socket and REST
# connections, it just won't spin up Simplicity Studio. This always spins up Simplicity Studio,
# and it uses a 'wait until process terminates' method.
USE_DAEMON = False

# By default, connecting to a running Simplicity Studio installation is not allowed,
# only a same-versioned CLI installation. This is to prevent small divergences that
# could occur in generation (even if functionality is not affected) since a full
# installation has more parts to the generation cycle. Therefore, people must opt-in to
# asking the command line to connect to a full running Simplicity Studio installation.
USE_SIMPLICITY_STUDIO = False


def _runningSharedHome():
    """Create the shared home if it does not exist and return it."""
    shared_home = os.path.join(_getUserDir(), ".uc", "cli")
    if not os.path.exists(shared_home):
        os.makedirs(shared_home)
    return shared_home


def _daemonSlc(
    args,
    folder,
    java_location,
    ignore_websockets,
    dev_test=False,
    debug=False,
    do_not_launch_daemon=False,
    use_full_installation=False,
    daemon_timeout=None,
    do_timing=None,
):
    """Connects to a running Simplicity Studio daemon, spinning one up if not exists.

    This will first try connecting to an existing instance by checking, in order,
    special .shared files at an expected location Simplicity Studio would create them to find
    a Simplicity Studio to communicate with using the contained port numbers. If nothing exists,
    it will spin up the local CLI based version of Simplicity Studio, and then connect to that.
    :param args arguments that are sent to Daemon. This is not passed to the executable,
    but sent via REST request to an available open endpoint.
    :param folder the location of the CLI Simplicity Studio executable. Needed if no currently
    running Simplicity Simplicity Studios exist to service the request, and one has to be spun up.
    :java_location java used to launch Simplicity Studio.
    :param debug true to turn on debugging.
    :ignore_websockets true to request server not use websockets. This means that
    results will be returned via REST response, which can be easier to work with in
    some circumstances, but does mean that realtime output is disabled (so any results
    will only be seen once the entire command is finished)
    :dev_test: whether to include versioning when looking for .running lock files.
    if True, then it looks for unversioned lock files, making it easier for
    development and testing. Otherwise, uses version locked files based on the
    slc_cli.version file in the executable directory. If this is set to false but
    there is no .version file, then this call will fail with -1 status code.
    :debug whether to print debugging info. Default is false.
    :do_not_launch_daemon defaults to False, but if True will not even attempt a launch
    even if the shared files are missing and launching the CLI would otherwise be
    the next step.
    :use_full_installation defaults to False. Unless True, will not attempt to connect
    to a full version of Simplicity Studio.
    :daemon_timeout the timeout for new daemon processes, in minutes. Passed as a string --
    it is up to command line interpreter to deal with bad inputs.
    :do_timing either None (default) indicating not to time anything, or is the starting
    time of the script, in which case the time will be output as soon as a message is
    SENT to the daemon. Script timing is most concerned about time to make it to launching
    or communicating with the actual Simplicity Studio installation. Other tools can take
    over for profiling Simplicity Studio itself.
    """

    # -- sanity check our arguments --
    # 1) Telling not to launch a daemon and providing daemon launch args are mutually exclusive.
    if daemon_timeout != None and do_not_launch_daemon:
        _localPrint(
            "Cannot specify both a timeout and a request not to launch the daemon: timeout effects only matter when launching the daemon. Ignoring timeout value "
            + daemon_timeout
        )
        daemon_timeout = None

    our_version_dictionary = _findRestVersion(folder) if not dev_test else ""
    # make sure that implicit no-version systems make scripts, such as cli launches,
    # act like dev mode is already enabled.
    if our_version_dictionary == None:
        dev_test = True

    shared_home = _runningSharedHome()
    return_code = _tryToTalkToSimplicityStudio(
        args,
        shared_home,
        our_version_dictionary,
        ignore_websockets,
        dev_test,
        debug,
        use_full_installation,
        do_timing=do_timing,
    )

    if return_code != None:
        if daemon_timeout != None:
            _localPrint(
                "A timeout amount cannot be specified whilst a daemon is already running. Use daemon-shutdown first."
            )
        return return_code
    else:
        # no one is currently running, so it's up to us to start one up.
        if do_not_launch_daemon:
            _localPrint(
                "No running Simplicity Studio found but requested not to launch a new daemon."
            )
            _localPrint(
                "If you expected a connection, turn on -pyDebug and make sure "
                + "the shared files match the server version (or that both the "
                + "server and the script are using no version)"
            )
            return -1
        else:
            if debug:
                _localPrint("Starting SLC Daemon.")

            expected_running_file = _calculateExpectedNextRunningFile(SHARED_FILE_CLI)

            spawnResult = _spawnCliSimplicityStudio(
                folder, java_location, dev_test, daemon_timeout, debug
            )
            if not spawnResult:
                _localPrint(
                    "SLC Daemon could not be started. Falling back to direct call."
                )
                return _simpleSlc(args, folder, java_location, debug, do_timing)
            else:
                # the logic for .running files is starting at ${SHARED_FILE_CLI}.running{number},
                # Simplicity Studio looks for the lowest number (or none) that does not exist when
                # it creates its own .running file, and at this point it will have to create its
                # own running file if we already determined none of the existing ones, if any,
                # works. So, we use the .running filename calculation made before the daemon started
                # and poll for its existence for a few seconds. Failure means falling back to direct
                # call, otherwise once its ready we use the Daemon as normal.
                time.sleep(2)
                give_up = 0
                while give_up != 4 and not os.path.exists(expected_running_file):
                    time.sleep(1)
                    give_up += 1
                if os.path.exists(expected_running_file):
                    if debug:
                        _localPrint(
                            "polled for and found " + str(expected_running_file)
                        )
                    # there may be a delay between when the file 'appears' vs when
                    # it is actually written to. We must also play the same waiting
                    # game if there happens to be no content
                    props = {}
                    give_up = 0
                    while give_up != 2 and "port_number" not in props:
                        props = _readJavaPropertiesFile(expected_running_file)
                        if "port_number" not in props:
                            time.sleep(1)
                            give_up += 1

                    if "port_number" not in props:
                        _localPrint(
                            "Newly created daemon wrote a .running file, but the port_number was never properly written out within a reasonable timeframe once the file was created. Dropping down to direct launch to service request."
                        )
                        return _simpleSlc(args, folder, java_location, debug, do_timing)
                    port_number = props["port_number"]
                    if debug:
                        _localPrint(
                            "Newly created Daemon ready at port " + str(port_number)
                        )
                    return_code = _talkToSimplicityStudio(
                        args,
                        port_number,
                        ignore_websockets,
                        debug=debug,
                        do_timing=do_timing,
                    )
                    if return_code == None:
                        _localPrint(
                            "Daemon started, .running file polled, but it wasn't actually ready when we tried to talk to it. Falling back to direct call."
                        )
                        return _simpleSlc(args, folder, java_location, debug, do_timing)
                    else:
                        return return_code
                else:
                    _localPrint(
                        "CLI Daemon was started, but is either taking too long to start or the daemon startup failed. Falling back to direct call."
                    )
                    return _simpleSlc(args, folder, java_location, debug, do_timing)


def _generateUuid():
    """Generates an infinitely probable unique id for a single cli session."""
    import uuid

    return str(uuid.uuid4())


def _tryToTalkToSimplicityStudio(
    args,
    shared_home,
    our_version_dictionary,
    ignore_websockets,
    dev_test,
    debug,
    use_full_installation=False,
    do_timing=None,
):
    return_code = (
        _searchForVersion(
            args,
            shared_home,
            SHARED_FILE_MAIN,
            our_version_dictionary,
            ignore_websockets,
            do_version_check=not dev_test,
            debug=debug,
            do_timing=do_timing,
        )
        if use_full_installation
        else None
    )

    if return_code == None:
        if debug:
            _localPrint(
                "No Main Simplicity Studio to connect to. Finding a CLI Daemon..."
            )

        return_code = _searchForVersion(
            args,
            shared_home,
            SHARED_FILE_CLI,
            our_version_dictionary,
            ignore_websockets,
            do_version_check=not dev_test,
            debug=debug,
            do_timing=do_timing,
        )

    return return_code


def _calculateExpectedNextRunningFile(prefix):
    """Determine the name a new .running file will take when newly created by Simplicity Studio"""
    raw_filename = prefix + ".running"
    home = _runningSharedHome()

    # this shouldn't hit an infinite loop unless the filesystem has undergone
    # spontanous massive existence failure.
    counter = 0
    original_destination = os.path.join(home, raw_filename)
    calculated_destination = original_destination
    while os.path.exists(calculated_destination):
        calculated_destination = original_destination + str(counter)
        counter = counter + 1
    return calculated_destination


def _findRestVersion(folder):
    file = os.path.join(folder, "our_version.version")
    if os.path.exists(file):
        return _loadVersionDictionary(file)
    else:
        return None


def _searchForVersion(
    args,
    folder,
    type_prefix,
    our_version_dictionary,
    ignore_websockets,
    do_version_check=True,
    debug=False,
    do_timing=None,
):
    """Find a .running file for the given daemon type matching our version, if any.

    This will immediately attempt to contact the Simplicity Studio server with the
    arguments passed to this wrapper. In other words, it's 'are you alive' question
    includes the arguments itself to avoid communication overhead. A correctly
    running Simplicity Studio will be able to successfully respond.

    :param args arguments to Simplicity Studio
    :param folder the folder where the running files should all live
    :param type_prefix either 'main' or 'cli' depending on the Simplicity Studio
    type currently being searched for.
    :param ignore_websockets whether to attempts to connect to studio should not include
    websockets for real-time results.
    :param debug whether to print debugging information. Defaults to false.
    :return the return code if a matching Simplicity Studio version was found and
    serviced the request. None if no such luck."""

    # It is possible for the .uc folder to just not be available yet. In that case,
    # there cannot possibly be something to connect to.
    if not os.path.exists(folder):
        return None

    with os.scandir(folder) as items:
        for item in items:
            # Basic levels of check in order are:
            # 1) is this a proper .running file?
            # 2) does this actually have properties we need?
            # --- note: checking process livelihood with psutils was removed due to
            #     issues installing it on some machines. The REST request is good
            #     enough.
            # 3) is the linked version matching ours?
            # 4) is it responding to hails?
            # MCUDT-23798 clean up .running files we detect are outdated
            # Occurs for all non-version related failures.
            file = item.path
            if _isRunningFile(file, type_prefix):
                if debug:
                    _localPrint("checking .running file " + file)
                props = _readJavaPropertiesFile(file)
                if "version_file" in props and "port_number" in props:
                    if do_version_check and our_version_dictionary != None:
                        version_file_name = props.get("version_file")
                        version_file = os.path.join(folder, version_file_name)
                        if os.path.exists(version_file):
                            their_version_dictionary = _loadVersionDictionary(
                                version_file
                            )
                            works = _compareVersion(
                                our_version_dictionary, their_version_dictionary
                            )

                            if not works:
                                # not removing file intended -- its valid
                                # just used for another version
                                if debug:
                                    _localPrint(
                                        "skipping "
                                        + file
                                        + " due to version incompatibility."
                                    )
                                continue
                        else:
                            # Asked to do a version check with no version
                            # file? Also remove it.
                            os.remove(file)
                            continue

                    if debug:
                        _localPrint("Found working shared file " + str(file))

                    return_code = _talkToSimplicityStudio(
                        args,
                        props["port_number"],
                        ignore_websockets,
                        debug=debug,
                        do_timing=do_timing,
                    )
                    if return_code == None:
                        # all command line operations have a return code. If this
                        # does not, it is likely there simply wasn't a real Simplicity
                        # Studio available, so burn the .running file.
                        if debug:
                            _localPrint("Removing stale " + str(file))

                        try:
                            os.remove(file)
                        except FileNotFoundError:
                            # not being able to remove the file is fine -- this could legit
                            # happen if another slc process has deleted it.
                            pass
                        # don't return yet. Perhaps another .running file will work
                    else:
                        return return_code

                else:
                    # a non running file, or running file for a different type,
                    # are fine, but a .running file with either incorrect
                    # properties or which is referring to a dead process
                    # should be removed.
                    if debug:
                        _localPrint("Removing stale " + str(file))
                    os.remove(file)

    # If we have not returned yet, nothing currently running qualifies. We
    # will have to spin up our own Daemon.
    return None


def _loadVersionDictionary(version_file):
    """Load the .version file, a property-like file where a key can have multiple values.

    :return map of plugin id to a list of 1 or more Version objects."""
    plugins = _readJavaPropertiesFile(version_file, expect_multiple=True)
    # basic strings need to turn into Version objects for eventual comparison
    # logic to work properly.
    return {
        plugin_id: list(
            map(lambda plugin_version: Version(plugin_version), plugin_versions)
        )
        for plugin_id, plugin_versions in plugins.items()
    }


def _isRunningFile(file, type_prefix):
    """Check if a file is a .running Simplicity Studio file of the given type."""
    import ntpath

    file_name = ntpath.basename(file)
    return (
        ".running" in file_name
        and type_prefix in file_name
        and not ".version" in file_name
    )


# Unlike 'feedback' which is used for handling responses from the server,
# this is specifically intended to allow testing debug calls without
# mocking builtin print functions, which will mess up attempts at using
# pdb.
def _localPrint(string):
    print(string)


def _compareVersion(our_version_dictionary, their_version_dictionary):
    """Determine if the CLI is allowed to connect to this daemon.

    Version comparison requires checking every plugin id (which may appear
    more than once) and all versions we have, and making sure those appear
    in the target file. The target file is allowed to have more stuff, it just
    can't have less or different stuff.

    The value of the maps should be Sets of Version objects.

    :param our_version_dictionary multimap of plugin id to one or more versions.
    the value must be a set to prevent order-dependent checking.
    :param their_version_dictionary multimap of plugin id to one or more versions.
    the value must be a set to prevent order-dependent checking.
    :return true if their versions are compatible with ours, false if otherwise."""
    for our_plugin, our_versions in our_version_dictionary.items():
        if not our_plugin in their_version_dictionary:
            return False
        their_versions = their_version_dictionary.get(our_plugin)
        for our_version in our_versions:
            if not our_version in their_versions:
                return False

    # Made it out of the for loop without getting angry? It's probably fine.
    return True


def _talkToSimplicityStudio(
    args,
    port_number,
    ignore_websockets,
    debug=False,
    do_timing=None,
):
    """Sends CLI commands and listens for them.

    :param uuid the uuid to use for communication.
    :return return code of executing the cli command, or None if talking failed."""
    import asyncio

    _initColourIfNeeded(debug)

    if not ignore_websockets:
        # Some situations apparently do not error out properly if the imports
        # fail in the aysnc method. So, import them now so if they aren't here
        # this can fail immediately.
        import websockets
        import asyncio

        # jump into async coroutines
        if debug:
            _localPrint("Using websocket connections")

        return_code = asyncio.get_event_loop().run_until_complete(
            _connectWebsocket(args, debug, port_number, do_timing=do_timing)
        )

        if debug:
            _localPrint(
                "Return Code from websocket terminal response: " + str(return_code)
            )

        return return_code
    else:
        if debug:
            _localPrint("Sending REST Request without Web Socket")

        if do_timing:
            _printTime(do_timing)

        cmd_response = _sendRest(
            port_number,
            _createCliPayload(args, None),
            True,
            debug=debug,
        )
        _feedback(cmd_response.get("out"))
        _feedback("errors")
        _feedback(cmd_response.get("err"))

        return_code = cmd_response.get("return_code")

        if debug:
            _localPrint("Return Code from REST response: " + str(return_code))
        return return_code


# Only
# prints that would come from the server (websocket, server responses) use this.
# Always flushes output.
def _feedback(str):
    # websocket responses have their own newlines. If we replicated that
    # for each time we end up with double spacing.
    print(str, flush=True, end="")


# When given a non-none do_timing variable, prints out the exeuction time
# of the script so far. This is reserved for right before the script is about to either
# wait for a response or send a blocking communication. In either case, it will represent
# the python side of how long the script takes to initiaite a Simplicity Studio connection.
def _printTime(
    do_timing, intermediate_message="get around to communicating with Simplicity Studio"
):
    import time

    execution_time = time.time() - do_timing
    print(
        "Time taken (in seconds) to "
        + intermediate_message
        + ": "
        + str(execution_time)
    )


async def _connectWebsocket(args, debug, port_number, do_timing=None):
    """Attaches Websocket. Blocks whilst reading until socket closes.

    :return return_code after the termination message has been sent by the server,
    or None if no connection could be made."""
    import websockets
    import asyncio
    from multiprocessing.dummy import Pool

    try:
        uri = "ws://localhost:" + port_number + CLI_WS_URI
        if debug:
            _localPrint("Awaiting socket connection at " + uri)
        async with websockets.connect(uri) as socket:
            if debug:
                _localPrint("Socket Connected!")

            uuidContext = _generateUuid()

            socketWaitingTask = asyncio.get_event_loop().create_task(
                _beginWebsocketReading(debug, socket, uuidContext)
            )
            # make a nonblocking rest request, otherwise we won't even be awaiting
            # socket calls until after the request is finished.
            runner = Pool(1)
            rest_response = runner.apply_async(
                _sendRest,
                [port_number, _createCliPayload(args, uuidContext), True, debug],
            )

            if do_timing:
                _printTime(do_timing)

            await socketWaitingTask
            rest_response.get()
            return socketWaitingTask.result()
    except:
        # TODO MCUDT-24380 allow logging when this happens. Under normal circumstances,
        # this is natural result of a stale file, but it could mean something more.
        if debug:
            _localPrint(
                "Could not establish websocket connection: is .running file stale?"
            )
            _localPrint(sys.exc_info())
        return None


async def _beginWebsocketReading(debug, socket, uuidContext):
    """Listens to attached websocket for responses from context to print.
    :param socket the websocket created from connectWebsocket
    :param uuidContext context of session. Other cli invocations may be running in
    parallel, so only listen to responses from our command session.
    :return after websocket receives a termination call from the server, relays
    the return code back to the caller. If there was no return code, returns None."""
    if debug:
        _localPrint("Listening on websockets...")
    async for message in socket:
        # If a socket is flushed on the server side, it can send an empty
        # byte array. Guard against that in case the server-side implementation
        # begins to use that feature.
        if not message == b"":
            try:
                resp = json.loads(message)
                if debug:
                    _localPrint("Messaged received: " + message)
                if resp.get("websocket_context") == uuidContext:
                    output = resp.get("out")
                    error = resp.get("err")
                    if not output == None:
                        _feedback(output)
                    if not error == None:
                        _feedback(error)
                elif resp.get("done") == uuidContext:
                    await socket.close()
                    return resp.get("return_code")
            except json.decoder.JSONDecodeError:
                _feedback("unexpected message from server: " + str(message))
    return None


def _createCliPayload(args, uuidContext):
    """Creates the general payload for making a command call to Simplicity Studio."""
    width = shutil.get_terminal_size().columns
    payload = {
        "action": "command",
        "working_dir": _currentWorkingDirectory(),
        "output_properties": {"width": width, "colour": not COLOUR_FORCED_OFF},
    }

    # now, build the command_line into the payload
    command_line = []
    command_line.extend(args)
    payload["command_line"] = command_line

    if not uuidContext == None:
        payload["context"] = uuidContext

    return payload


def _readJavaPropertiesFile(file, expect_multiple=False):
    """Read a Java-like properties file and returns a dictionary.
    If the file in question can contains multiple entries for a single key,
    expect_multiple should be set to true, and this will affect the return
    type (the values will be lists of strings instead of strings)
    :param file properties file to parse
    :param expect_multiple if True, return dictionary is not 'Str->Str' but
    'Str->List[Str]'. if False, multiple keys mean that the last key only
    is relevant.
    :return dictionary of 'Str->Str' for non multiple and 'Str->List[Str] for
    multiple."""
    return_dict = {}
    lines = []
    with open(file, "r") as propFile:
        lines = propFile.readlines()
    for line in lines:
        trimmed = line.strip()
        # ignore blank lines and comments
        if not trimmed == "" and not trimmed.startswith("#"):
            key_value = trimmed.split("=")
            if len(key_value) == 2:
                key, value = key_value
                if expect_multiple:
                    if key not in return_dict:
                        return_dict[key] = []
                    values_list = return_dict[key]
                    values_list.append(value)
                else:
                    return_dict[key] = value
            else:
                _localPrint("Not a valid java property file: " + file)
    return return_dict


def _sendRest(port_number, payload, noisey, debug=False):
    """Sends REST request to Simplicity Studio Daemon CLI Handler.
    Client code based on websocket usage or not can make this call blocking (REST only)
    or non-blocking (waiting on websockets instead)
    :param port_number the port as read from the shared file
    :param payload the json payload to send to the server. This is just a
    python object do not convert!
    :param noisy if true, a failed rest call prints to the console.
    :return a map parsed from returned json, or None if the call failed."""
    import requests

    url = "http://localhost:" + port_number + "/rest/uccli/action/commandline"

    try:
        if debug:
            _localPrint("Sending request...")
            _localPrint(payload)
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            # if websockets are requested this may not necessarily be json, as
            # well as other things. Just return an empty map if that happens.
            responseJson = {}
            try:
                responseJson = response.json()
            except json.decoder.JSONDecodeError:
                pass
            return responseJson
        else:
            if noisey:
                _localPrint(
                    "Could not communicate with Simplicity Studio Daemon Server at "
                    + url
                )
                _localPrint(response.reason)
                _localPrint(response.text)
            return None
    except requests.exceptions.ConnectionError as connectError:
        if noisey:
            _localPrint(
                "Could not communicate with Simplicity Studio Daemon Server: Connection Refused at port "
                + str(port_number)
                + ". If you still get results, this could had been a stale .running file that was "
                + "not cleaned up, and this issue should not appear on the next command line run."
            )
            _localPrint(connectError)
        return None


def _currentWorkingDirectory():
    """Returns the current working directory of the script.

    This accounts for running the script within a cygwin environment."""
    cwd = os.getcwd()
    if cwd.startswith("/cygdrive/"):
        cwd = _cygpath(cwd)
    return cwd


def _spawnCliSimplicityStudio(
    folder, java_location, dev_test, daemon_timeout=None, debug=False
):
    """Spawns a new Daemon CLI Simplicity Studio.

    :param folder the path to the actual home of the command line executable
    :param java_location the default java location to use to execute uc. If not
    supplied, the system defaults will just be used (no -vm argument will be provided to script.)
    :param dev_test if True, passes the -Dslc_cli_dev_testing=true argument
    so that the launched Simplicity Studio uses a non-versioned lock file, allowing a non-verisoned
    python launch to then use it.
    :param daemon_timeout timeout value in minutes to send to daemon process as it launches.
    :param debug boolean if 'true' print debugging information, 'false' or not provided
    to not do so.
    :return True if spawning created no issues, False if it could not spawn. Note that 0 doesn't
    mean it's running without any errors -- caller should poll for CLI shared running file to
    truly see if the startup succeeded.
    """
    launch_uc = _getSimplicityStudioLaunchFile(folder, debug)
    return _launchCliSimplicityStudio(
        launch_uc, java_location, dev_test, daemon_timeout, debug
    )


def _getSimplicityStudioLaunchFile(folder, debug):
    """Gets the launchable file based on home folder and current OS.

    :param folder the folder containing the executable"""
    launch_uc = ""
    if "linux" in sys.platform:
        # nothing to do, no file extension
        launch_uc = os.path.join(folder, UC_NAME_BASE)
    elif "win32" in sys.platform or "cygwin" in sys.platform:
        # MCUDT-17417 Use the slc-clic.exe to get output correctly
        launch_uc = os.path.join(folder, UC_NAME_BASE + "c.exe")
    elif "darwin" in sys.platform:
        # go inside app folder for real application.
        launch_uc = os.path.join(
            folder, UC_NAME_BASE + ".app", "Contents", "MacOS", UC_NAME_BASE
        )

    if launch_uc == "":
        _localPrint("Unhandled OS: assuming Linux naming rules. Reported os: ")
        _localPrint(sys.platform)
        _localPrint("+-+-+")
        sys.stdout.flush()
        launch_uc = os.path.join(folder, UC_NAME_BASE)

    if debug:
        _localPrint("Launching " + launch_uc)

    return launch_uc


def _launchCliSimplicityStudio(
    launch_uc, java_location, dev_test, daemon_timeout=None, debug=False
):
    """Launches UC executable with given Java.
    :param launch_uc the launchable program.
    :param java_location JVM used to launch
    :param dev_test set to True to include -Dslc_cli_dev_testing=true variable
    :param daemon_timeout timeout in minutes before daemon should close after last successful request.
    :param debug debugging on or off
    :return True if this was successfully launched, False if otherwise."""

    import platform

    process_args, env = _commonLaunch(None, launch_uc, java_location)
    process_args.append("-Dslc_daemon=true")
    if dev_test:
        process_args.append("-Dslc_cli_dev_testing=true")

    if daemon_timeout:
        process_args.append("-Dslc_cli_servlet_shutdown_minutes=" + daemon_timeout)

    if debug:
        _localPrint("Daemon Launch Arguments: " + str(process_args))
    try:
        # No out/err pipes used. All communication is pure websocket/REST
        # The daemon will have to be detached, which requires some additional work on
        # Windows: MCUDT-24355
        daemonArgs = {}
        if _isWin32() and not _isCygwin():
            # https://docs.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
            if debug:
                _localPrint("Windows process creation detected.")
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            DETACHED_PROCESS = 0x00000008
            daemonArgs.update(creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS)
        else:
            # python 3.3+ is already required.
            if debug:
                _localPrint("Linux/Mac process creation detected.")
            daemonArgs.update(start_new_session=True)
        subprocess.Popen(
            process_args,
            bufsize=1,
            universal_newlines=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=env,
            **daemonArgs
        )

        if debug:
            _localPrint("SLC Daemon has so far appeared to start normally")
        return True
    except FileNotFoundError:
        _localPrint(process_args[0] + " not found -- daemon process cannot start.")
        sys.stdout.flush()
        return False
    except subprocess.CalledProcessError:
        return False


# stubbed as method for easier mocking
def _isWin32():
    return IS_WIN32


def _isCygwin():
    return IS_CYGWIN


def _launchCliNoDaemon(args, launch_uc, java_location, debug, do_timing=None):
    process_args, env = _commonLaunch(args, launch_uc, java_location)
    width = shutil.get_terminal_size().columns
    # Note: Old entry point colour not supported. ANSI needs to be parsed
    # by colorama, but doing that requires getting the output into python
    # instead of directly to the terminal, which both batches output and
    # ruins real-time viewing.
    process_args.append("-Dslc_consolecolour=" + "false")
    process_args.append("-Dslc_consolewidth=" + str(width))
    if debug:
        _localPrint(
            "Direct to Simplicity Studio Launch Arguments: " + str(process_args)
        )

    uc_result = -1
    try:
        # do not connect standard output to pipe. When that happens, the
        # output is buffered and cannot be read in realtime properly.
        # Since we are not doing anything with the output beyond printing it
        # anyway, this should suffice.
        # However, we pipe standard error so it can be routed to standard
        # output. Some configurations otherwise do not see the standard error
        # messages
        cli_process = subprocess.Popen(
            process_args,
            bufsize=1,
            # If removing universal_newlines, see
            # warning below.
            universal_newlines=True,
            # Standard error doesn't print out
            # automatically (such as mac)
            stderr=subprocess.PIPE,
            env=env,
        )

        # ==== Process.communicate method (does not work with Colorama)
        if do_timing:
            _printTime(do_timing)

        uc_output = cli_process.communicate()
        uc_result = cli_process.returncode

        # standard output should have already printed. Run through any
        # standard error and print that now. The only reason this is handled
        # differently for stderr is due to some systems not printing err
        # information by default.
        # -- WARNING WARNING WARNING --
        # If you need to remove universal_newlines, make sure to
        # put this back and decode the line first, or this will hang
        # on python 3 where this becomes a byte string.

        # line = bLine.decode()
        _feedback(uc_output[1])

        # ==== Readline method (works with Colorama)
        # This hangs if there is no stdout and only stderr though, and if
        # doesn't buffer output. Leaving comments for now in case inspiration appears.
        # (If used, add to stdout in Popen a subprocess pipe and make
        # sure to call _initColourIfNeeded)
        # while True:
        #     line = cli_process.stdout.readline() if cli_process.stdout != None else ""

        #     uc_result = cli_process.poll()
        #     # nothing to print AND process is over, stop. Process may finish
        #     # but there is still more to print.
        #     if line == "" and uc_result is not None:
        #         break
        #     if line:
        #         _feedback(line)

        # err = cli_process.stderr.readline()
        # while err != "":
        #     _feedback(err)
        #     err = cli_process.stderr.readline()

        if debug:
            _localPrint("SLC Tool returned status code " + str(uc_result))
        return uc_result
    except FileNotFoundError:
        _localPrint(process_args[0] + " not found -- command line cannot run.")
        sys.stdout.flush()
        return uc_result
    except subprocess.CalledProcessError:
        # This is expected -- the command line returns -1 if it could
        # not service the request, and already makes that clear with
        # its own output.
        return uc_result


def _initColourIfNeeded(debug):
    # we may be printing stuff out. Get Colorama ready.
    try:
        import colorama

        if not COLOUR_FORCED_OFF:
            # Note: https://github.com/tartley/colorama/pull/226 when that request
            # is accepted update colorama version and this will work with git bash
            if not is_msys_cygwin_tty(sys.stdout):
                colorama.init()
    except:
        if debug:
            print("Colorama is not available: no colour output is possible.")


def _commonLaunch(args, launch_uc, java_location):
    """Common setup for both kinds of cli launches.

    Sets and returns process arguments needed for both.
    :param args arguments to add to process call directly, or 'None'
    :return tuple with first process arguments arrays. Mutable. Second is os environment"""
    cwd = _currentWorkingDirectory()

    process_args = [launch_uc]
    # Make UC launch with the specified JVM
    if java_location is not None:
        process_args.append("-vm")
        process_args.append(java_location)

    if args != None:
        process_args.extend(args)

    # sneak in our -Duc.workingdirectory, otherwise on some systems
    # like Mac, Eclipse is going to hijack the working directory and
    # really confuse people. THIS IS ONLY A DEFAULT! Server calls
    # will include working directories specific to the call.
    process_args.append("--launcher.appendVmargs")
    process_args.append("-vmargs")
    process_args.append("-Duc.workingdirectory=" + cwd)

    # Run UC with a copy of the environment where the variable
    # __PYVENV_LAUNCHER__ is unset. This is needed to work around an issue
    # where import statements from JEP code fail when UC is executed from
    # a Python 3 virtualenv. See MCUDT-18822.
    env = os.environ.copy()
    env.pop("__PYVENV_LAUNCHER__", None)

    return [process_args, env]


def _cygpath(path):
    """Convert a cygwin path to a windows path.

    The conversion is done using the cygpath command.

    Parameters:
    path -- The cygwin path to convert

    Returns: the windows path of the input parameter.

    """
    command = ["cygpath", "-m", path]
    output = subprocess.check_output(command)
    winpath = output.splitlines()[0]
    return winpath.decode()


def _handlePythonArgument(arg):
    pass


def _handleJavaLocation(arg=None):
    global JAVA_LOCATION
    if JAVA_LOCATION is not None:
        return

    JAVA_LOCATION = _calculateJavaLocation(arg, DEBUG)


def _handlePythonArgument(arg):
    global DEBUG
    global IGNORE_WEBSOCKETS
    global DO_NOT_LAUNCH_DAEMON
    global COLOUR_FORCED_OFF
    global DEV_TESTING
    global USE_DAEMON
    global USE_SIMPLICITY_STUDIO
    global DAEMON_CUSTOM_TIMEOUT

    handled = True
    if arg == "-debug":
        DEBUG = True
    elif arg == "-ignoreWebsockets":
        IGNORE_WEBSOCKETS = True
    elif arg == "-doNotLaunchDaemon":
        DO_NOT_LAUNCH_DAEMON = True
    elif arg == "-noColour":
        COLOUR_FORCED_OFF = True
    elif arg == "-devTest":
        DEV_TESTING = True
    elif arg == "-daemon":
        USE_DAEMON = True
    elif arg == "-simplicityStudio":
        USE_SIMPLICITY_STUDIO = True
    elif "-daemonTimeout" in arg:
        DAEMON_CUSTOM_TIMEOUT = arg.replace("-daemonTimeout=", "")
    elif arg == "-time":
        # This is handled separately so timing starts earlier, but we still check
        # for it so the handler doesn't return false and properly removes it
        # from the args list.
        pass
    elif "-javaLocation" in arg:
        _handleJavaLocation(arg.replace("-javaLocation=", ""))
    else:
        # Some options, like slc --help, are root level commands and the 'is this
        # a python argument' logic won't always work. Only print out if we are debugging,
        # Remember -debug, if it appears, should appear first.
        if DEBUG:
            _localPrint("Assuming " + arg + " intended for Simplicity Studio")
        handled = False

    return handled


def _slcCliFolder(repo_location):
    return os.path.join(repo_location, "..", "bin", "slc-cli")


def _simpleSlc(args, folder, java_location, debug, do_timing=None):
    launch_uc = _getSimplicityStudioLaunchFile(folder, debug)
    return _launchCliNoDaemon(args, launch_uc, java_location, debug, do_timing)


def _latestVersionFile():
    return os.path.join(REPO_LOCATION, "../changelog")


def _printLatestVersion():
    file = _latestVersionFile()
    try:
        with open(_latestVersionFile(), "r") as handle:
            lines = handle.readlines()
            for line in lines:
                # first line that resolves to a valid semantic version is the latest,
                # as version ordering goes from newest to oldest.
                if _isVersion(line):
                    _localPrint(line.strip())
                    return 0

        # incorrectly formatted changelog file
        _localPrint(
            "Changelog file is incorrectly formatted. Cannot determine version."
        )
        return -1
    except FileNotFoundError:
        _localPrint(
            "No changelog could be found at " + file + ". Cannot determine version."
        )
        return -2


# ------
# Warning: This is currently partially duplicated in download scripts!
# ------
def _handlePythonArgs(args, handler):
    """Removes and handles any python specific arguments.
    :param args the args list from the command line, minus the program name.
    :param handler a function that will be called with each argument up to the first
    non - dashed argument (which would be where the normal cli arguments would start).
    If the handler returns True, the argument is removed. Otherwise, it remains. This is only
    really used
    for download script argument handling that eventually delegates to slc_run argument
    handling.
    Example: slc -debug -ignoreWebsockets generate -someoption ... will attempt to
    handle -debug and -ignoreWebsockets, removing them from the returned list, just
    leaving slc generate -someoption ... whether or not it could do anything with
    -debug or -ignoreWebsockets
    ;
    :return new list with handled python arguments removed"""
    args_to_slc = []
    still_handling_ours = True
    for arg in args:
        # read 'and not' as 'but'
        if still_handling_ours and not arg.startswith("-"):
            # hit the first slc option/command. nothing more to handle.
            still_handling_ours = False
            args_to_slc.append(arg)
        elif still_handling_ours:
            should_remove = handler(arg)
            if not should_remove:
                args_to_slc.append(arg)
        else:
            args_to_slc.append(arg)
    return args_to_slc


def _entryPoint(raw_args_to_slc, folder=None):
    """Runs slc using default settings.

    This is the client-side runner, which assumes no download is needed and that
    there is a synced, hardcoded version in a hardcoded search location that
    should run.
    :param raw_args_to_slc argument list as provided by the user, possibly
    partially handled already if this is called from a higher level script.
    :param folder the folder holding the SLC. By default this will look for it
    in a specific place, but can be overridden by update scripts that take control
    of downloading.
    :return the return code calling the command line. This will never be None, but
    100 is a python wrapper specific return code indicating the command line itself
    didn't have a return code of its own
    """

    # We handle this immediately so we can time the entire script. Handler
    # will still detect it so it is removed properly from args list.
    import time

    do_timing = time.time() if "-pyTime" in raw_args_to_slc else None

    # -debug means before we even parse the args, print how we interpreted
    # them from the shell script
    if "-debug" in raw_args_to_slc:
        _localPrint("Raw Args From Shell: " + str(raw_args_to_slc))

    # -version prempts all other options
    if "-version" in raw_args_to_slc:
        return _printLatestVersion()

    # Grab the first args in case we need to export the logs since there
    # may be a problem booting SLC
    if any("-exportLogs" in arg for arg in raw_args_to_slc):
        _exportLog(raw_args_to_slc)
        exit()

    args_to_slc = _handlePythonArgs(raw_args_to_slc, _handlePythonArgument)
    # Figure out which Java to run now
    _handleJavaLocation()

    # if run directly, we only run whatever is 'current'
    if folder == None:
        folder = _slcCliFolder(REPO_LOCATION)

    global USE_DAEMON

    # Check python version: -pyDaemon is not accepted for 3.5 and
    # below. 3.3 and below won't work at all but that would had already
    # failed before making it here.
    if sys.version_info < (3, 6) and USE_DAEMON:
        USE_DAEMON = False
        print("Daemon functionality is not available for python versions below 3.6")

    if USE_DAEMON:
        if DEBUG:
            print("Using daemonised command line")
        ret = _daemonSlc(
            args_to_slc,
            folder,
            JAVA_LOCATION,
            IGNORE_WEBSOCKETS,
            dev_test=DEV_TESTING,
            debug=DEBUG,
            do_not_launch_daemon=DO_NOT_LAUNCH_DAEMON,
            do_timing=do_timing,
            daemon_timeout=DAEMON_CUSTOM_TIMEOUT,
            use_full_installation=USE_SIMPLICITY_STUDIO,
        )
    else:
        if DEBUG:
            _localPrint("Using old-style entry point (colour not supported")
        if DAEMON_CUSTOM_TIMEOUT != None:
            _localPrint(
                "The daemon timeout option will be ignored unless using the -daemon option."
            )
        ret = _simpleSlc(
            args_to_slc, folder, JAVA_LOCATION, debug=DEBUG, do_timing=do_timing
        )

    if do_timing:
        _printTime(
            do_timing,
            intermediate_message="get return code " + str(ret),
        )

    if ret == None:
        ret = 100
    return ret