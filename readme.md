# SLC-CLI

slc-cli is Silicon Labs' command line alternative to using Simplicity Studio 5 to generate projects from example applications packaged with a Silicon Labs SDK. slc-cli is a Python wrapper that accesses Simplicity Studio's internal project configuration tools framework.

slc-cli is provided as a downloadable .zip file for three operating systems:

- Windows® OS
- MacOS® X
- Linux® OS

slc-cli may be used with the following SDKs:

- Bluetooth SDK
- Bluetooth Mesh SDK
- OpenThread SDK
- 32-bit MCU SDK
- Proprietary (Flex) SDK

Example projects are installed with the SDK in a directory under the Gecko SDK Suite (GSDK) installed directory. The location varies depending on the SDK.

- Bluetooth and Bluetooth Mesh SDKs: `<GSDKpath>\app\bluetooth\example`
- OpenThread SDK: `<GSDKpath>\protocol\openthread\sample-apps`
- 32-Bit MCU SDK: `<GSDKpath>\app\mcu_example`
- Proprietary(Flex) SDK: `<GSDKpath>\app\flex\example\<Connect or RAIL>`
- GSDK Platform: `<GSDKpath>\app\common\example`

## Requirements

As well as the slc-cli .zip file and a Silicon Labs SDK, you will need:

- Python 3.3 or higher.
- pip (download option with Python)
- Java 64 bit JVM version 11 or higher, available through [Amazon Correto](https://docs.aws.amazon.com/corretto/latest/corretto-11-ug/downloads-list.html). Note that some files, such as the Windows .msi files, can be found on the [releases page](https://github.com/corretto/corretto-11/releases).

## Installation

1. Unpack the slc-cli zip file.
2. Run `pip install -r requirements.txt`

   If you get an `EnvironmentError`, run `pip install --user -r requirements.txt`

   If you are running `slc` with a Python version other than your system default, add the Python path to the command, for example: `your/python/path -m pip install -r requirements.txt`
3. (Optional) To call slc-cli from anywhere in your system, add the path to the downloaded slc-cli command line to your PATH.
4. Configure slc-cli to find the GSDK location, for example (assuming the SDK was installed through Simplicity Studio 5):

    `slc configuration --sdk <SSv5 installation>\developer\sdks\gecko_sdk_suite\v3.1\`

    Then all commands that use an SDK will use this configured location. If you do not do this, you must specify the SDK path with the --sdk option each time you issue a command, such as `generate` discussed below.

`slc --help` provides details on usage and a list of available commands. `slc <command> -h` shows all options for the command.

Run `slc <command> <command options>` to use the default Python installation, or `your\python\path slc ...` to use a different version of Python.

## Generating a Project

This section assumes you have configured the GSDK location as described above.

`slc generate <source.slcp>` generates a project from an existing .slcp file, such as an SDK example. The path to the example is either the fully defined path, or the path relative to the calling location.

Key options are:

  `-d <destination>` (optional) specifies the destination for the generated project. If not specified, the project is generated to the source.slcp location.

  `-np` generates a new project by copying the .slcp file and all files defined in it into the destination location. All file references in the .slcp are updated to point to the destination location. Any sources that should be highlighted are shown in the slc-cli output.

  `-name=<generated-name>` specifies a different generated project name. Otherwise the name of the source .slcp file is used.
  
  `--with <OPN>` customizes the generated project for the part specified by the full OPN, for example `EFR32MG12P232F512GM68`.

To generate a new project with a new name customized for a specific part number:

`slc generate <path to example.slcp> -np -d <project destination> -name=<new name> --with <device_that_supports_project>`

`slc generate C:\SiliconLabs\SimplicityStudio\v5\developer\sdks\gecko_sdk_suite\v3.1\app\bluetooth\example\soc_empty\soc_empty.slcp -np -d c:\test-soc-empty\ -name=test-soc-empty --with EFR32MG12P232F512GM68`

A number of files are generated that can be used with different tools. For example, to build the project with Make (if Make is in your path):

`make -f <project>.Makefile`
