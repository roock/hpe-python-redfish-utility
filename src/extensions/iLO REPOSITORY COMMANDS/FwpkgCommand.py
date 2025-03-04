# ##
# Copyright 2016-2021 Hewlett Packard Enterprise, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ##

# -*- coding: utf-8 -*-
""" Fwpkg Command for rdmc """

import os
import json
import shutil
import zipfile
import tempfile

import ctypes
from ctypes import c_char_p, c_int, c_bool

from redfish.hpilo.risblobstore2 import BlobStore2

from rdmc_helper import (
    IncompatibleiLOVersionError,
    ReturnCodes,
    Encryption,
    InvalidCommandLineErrorOPTS,
    InvalidCommandLineError,
    InvalidFileInputError,
    UploadError,
    TaskQueueError,
    FirmwareUpdateError,
)


def _get_comp_type(payload):
    """Get's the component type and returns it

    :param payload: json payload of .fwpkg file
    :type payload: dict.
    :returns: returns the type of component. Either A,B,C, or D.
    :rtype: string
    """
    ctype = ""
    if "Uefi" in payload["UpdatableBy"] and "RuntimeAgent" in payload["UpdatableBy"]:
        ctype = "D"
    elif "UEFI" in payload["UpdatableBy"] and "Bmc" in payload["UpdatableBy"]:
        getloc = self.rdmc.app.getidbytype("SoftwareInventoryCollection.")
        for gloc in getloc:
            if "FirmwareInventory" in gloc:
                data = self.rdmc.app.getcollectionmembers(gloc)
        if data is not None:
            type_set = None
            for fw in data:
                for device in payload["Devices"]["Device"]:
                    if fw["Oem"]["Hpe"].get("Targets") is not None:
                        if device["Target"] in fw["Oem"]["Hpe"]["Targets"]:
                            if fw["Updateable"]:
                                ctype = "A"
                                type_set = True
                            else:
                                ctype = "C"
                                type_set = True
            if type_set is None:
                raise IncompatibleiLOVersionError(
                    "Cannot flash the component on this server, server is not VROC enabled"
                )
    else:
        for device in payload["Devices"]["Device"]:
            for image in device["FirmwareImages"]:
                if "DirectFlashOk" not in list(image.keys()):
                    raise InvalidFileInputError("Cannot flash this firmware.")
                if image["DirectFlashOk"]:
                    ctype = "A"
                    if image["ResetRequired"]:
                        ctype = "B"
                        break
                elif image["UefiFlashable"]:
                    ctype = "C"
                    break
                else:
                    ctype = "D"

    return ctype


class FwpkgCommand:
    """Fwpkg command class"""

    def __init__(self):
        self.ident = {
            "name": "flashfwpkg",
            "usage": None,
            "description": "Run to upload and flash "
            "components from fwpkg files.\n\n\tUpload component and flashes it or sets a task"
            "queue to flash.\n\texample: flashfwpkg component.fwpkg.\n\n\t"
            "Skip extra checks before adding taskqueue. (Useful when adding "
            "many flashfwpkg taskqueue items in sequence.)\n\texample: flashfwpkg "
            "component.fwpkg --ignorechecks",
            "summary": "Flashes fwpkg components using the iLO repository.",
            "aliases": ["fwpkg"],
            "auxcommands": [
                "UploadComponentCommand",
                "UpdateTaskQueueCommand",
                "FirmwareUpdateCommand",
                "FwpkgCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main fwpkg worker function

        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
            if not line or line[0] == "help":
                self.parser.print_help()
                return ReturnCodes.SUCCESS
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.fwpkgvalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError(
                "iLO Repository commands are only available on iLO 5."
            )

        if self.rdmc.app.getiloversion() <= 5.120 and options.fwpkg.lower().startswith(
            "iegen10"
        ):
            raise IncompatibleiLOVersionError(
                "Please upgrade to iLO 5 1.20 or "
                "greater to ensure correct flash of this firmware."
            )
        tempdir = ""
        if not options.fwpkg.endswith(".fwpkg"):
            InvalidFileInputError(
                "Invalid file type. Please make sure the file "
                "provided is a valid .fwpkg file type."
            )

        try:
            components, tempdir, comptype = self.preparefwpkg(self, options.fwpkg)
            if comptype == "D":
                raise InvalidFileInputError("Unable to flash this fwpkg file.")
            elif comptype == "C":
                try:
                    self.taskqueuecheck()
                except TaskQueueError as excp:
                    if options.ignore:
                        self.rdmc.ui.warn(str(excp) + "\n")
                    else:
                        raise excp
            self.applyfwpkg(options, tempdir, components, comptype)

            if comptype == "A":
                message = "Firmware has successfully been flashed.\n"
                if "ilo" in options.fwpkg.lower():
                    message += (
                        "iLO will reboot to complete flashing. Session will be"
                        " terminated.\n"
                    )
            elif comptype == "B":
                message = (
                    "Firmware has successfully been flashed and a reboot is required for "
                    "this firmware to take effect.\n"
                )
            elif comptype == "C":
                message = "This firmware is set to flash on reboot.\n"
            self.rdmc.ui.printer(message)

        except (FirmwareUpdateError, UploadError) as excp:
            raise excp

        finally:
            if tempdir:
                shutil.rmtree(tempdir)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def taskqueuecheck(self):
        """Check taskqueue for potential issues before starting"""

        select = "ComputerSystem."
        results = self.rdmc.app.select(selector=select, path_refresh=True)

        try:
            results = results[0]
        except:
            pass

        powerstate = results.resp.dict["PowerState"]
        tasks = self.rdmc.app.getcollectionmembers(
            "/redfish/v1/UpdateService/UpdateTaskQueue/"
        )

        for task in tasks:
            if task["State"] == "Exception":
                raise TaskQueueError(
                    "Exception found in taskqueue which will "
                    "prevent firmware from flashing. Please run "
                    "iLOrest command: taskqueue --cleanqueue to clear"
                    " any errors before continuing."
                )
            if (
                task["UpdatableBy"] == "Uefi"
                and not powerstate == "Off"
                or task["Command"] == "Wait"
            ):
                raise TaskQueueError(
                    "Taskqueue item found that will "
                    "prevent firmware from flashing immediately. Please "
                    "run iLOrest command: taskqueue --resetqueue to "
                    "reset the queue if you wish to flash immediately "
                    "or include --ignorechecks to add this firmware "
                    "into the task queue anyway."
                )
        if tasks:
            self.rdmc.ui.warn(
                "Items are in the taskqueue that may delay the flash until they "
                "are finished processing. Use the taskqueue command to monitor updates.\n"
            )

    @staticmethod
    def preparefwpkg(self, pkgfile):
        """Prepare fwpkg file for flashing

        :param pkgfile: Location of the .fwpkg file
        :type pkgfile: string.
        :returns: returns the files needed to flash, directory they are located
                                                            in, and type of file.
        :rtype: string, string, string
        """
        files = []
        imagefiles = []
        payloaddata = None
        tempdir = tempfile.mkdtemp()

        try:
            zfile = zipfile.ZipFile(pkgfile)
            zfile.extractall(tempdir)
            zfile.close()
        except Exception as excp:
            raise InvalidFileInputError("Unable to unpack file. " + str(excp))

        files = os.listdir(tempdir)

        if "payload.json" in files:
            with open(os.path.join(tempdir, "payload.json"), encoding="utf-8") as pfile:
                data = pfile.read()
            payloaddata = json.loads(data)
        else:
            raise InvalidFileInputError("Unable to find payload.json in fwpkg file.")

        comptype = _get_comp_type(payloaddata)

        if comptype == "C":
            imagefiles = [self.auxcommands["flashfwpkg"].type_c_change(tempdir, pkgfile)]
        else:
            results = self.rdmc.app.getprops(
                selector="UpdateService.", props=["Oem/Hpe/Capabilities"]
            )

            for device in payloaddata["Devices"]["Device"]:
                for firmwareimage in device["FirmwareImages"]:
                    if firmwareimage["FileName"] not in imagefiles:
                        imagefiles.append(firmwareimage["FileName"])

        if (
            "blobstore" in self.rdmc.app.redfishinst.base_url
            and comptype in ["A", "B"]
            and results
            and "UpdateFWPKG" in results[0]["Oem"]["Hpe"]["Capabilities"]
        ):
            dll = BlobStore2.gethprestchifhandle()
            dll.isFwpkg20.argtypes = [c_char_p, c_int]
            dll.isFwpkg20.restype = c_bool

            with open(pkgfile, "rb") as fwpkgfile:
                fwpkgdata = fwpkgfile.read()

            fwpkg_buffer = ctypes.create_string_buffer(fwpkgdata)
            if dll.isFwpkg20(fwpkg_buffer, 2048):
                imagefiles = [pkgfile]
                tempdir = ""

        return imagefiles, tempdir, comptype

    def type_c_change(self, tdir, pkgloc):
        """Special changes for type C

        :param tempdir: path to temp directory
        :type tempdir: string.
        :param components: components to upload
        :type components: list.

        :returns: The location of the type C file to upload
        :rtype: string.
        """

        shutil.copy(pkgloc, tdir)

        fwpkgfile = os.path.split(pkgloc)[1]
        zfile = fwpkgfile[:-6] + ".zip"
        zipfileloc = os.path.join(tdir, zfile)

        os.rename(os.path.join(tdir, fwpkgfile), zipfileloc)

        return zipfileloc

    def applyfwpkg(self, options, tempdir, components, comptype):
        """Apply the component to iLO

        :param options: command line options
        :type options: list.
        :param tempdir: path to temp directory
        :type tempdir: string.
        :param components: components to upload
        :type components: list.
        :param comptype: type of component. Either A,B,C, or D.
        :type comptype: str.
        """

        for component in components:
            taskqueuecommand = " create %s " % os.path.basename(component)
            if options.tover:
                taskqueuecommand = " create %s --tpmover" % os.path.basename(component)
            if component.endswith(".fwpkg") or component.endswith(".zip"):
                uploadcommand = "--component %s" % component
            else:
                uploadcommand = "--component %s" % os.path.join(tempdir, component)

            if options.forceupload:
                uploadcommand += " --forceupload"
            if comptype in ["A", "B"]:
                uploadcommand += " --update_target --update_repository"
            if options.update_srs:
                uploadcommand += " --update_srs"

            self.rdmc.ui.printer("Uploading firmware: %s\n" % os.path.basename(component))
            try:
                ret = self.auxcommands["uploadcomp"].run(uploadcommand)
                if ret != ReturnCodes.SUCCESS:
                    raise UploadError
            except UploadError:
                if comptype in ["A", "B"]:
                    select = self.rdmc.app.typepath.defs.hpilofirmwareupdatetype
                    results = self.rdmc.app.select(selector=select)

                    try:
                        results = results[0]
                    except:
                        pass

                    if results:
                        update_path = results.resp.request.path
                        error = self.rdmc.app.get_handler(update_path, silent=True)
                        self.auxcommands["firmwareupdate"].printerrmsg(error)
                    else:
                        raise FirmwareUpdateError(
                            "Error occurred while updating the firmware."
                        )
                else:
                    raise UploadError("Error uploading component.")

            if comptype == "C":
                self.rdmc.ui.warn(
                    "Setting a taskqueue item to flash UEFI flashable firmware.\n"
                )
                self.auxcommands["taskqueue"].run(taskqueuecommand)

    def fwpkgvalidation(self, options):
        """fwpkg validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument("fwpkg", help="""fwpkg file path""", metavar="[FWPKG]")
        customparser.add_argument(
            "--forceupload",
            dest="forceupload",
            action="store_true",
            help="Add this flag to force upload firmware with the same name "
            "already on the repository.",
            default=False,
        )
        customparser.add_argument(
            "--ignorechecks",
            dest="ignore",
            action="store_true",
            help="Add this flag to ignore all checks to the taskqueue "
            "before attempting to process the .fwpkg file.",
            default=False,
        )
        customparser.add_argument(
            "--tpmover",
            dest="tover",
            action="store_true",
            help="If set then the TPMOverrideFlag is passed in on the "
            "associated flash operations",
            default=False,
        )
        customparser.add_argument(
            "--update_srs",
            dest="update_srs",
            action="store_true",
            help="Add this flag to update the System Recovery Set with the uploaded firmware. "
            "NOTE: This requires an account login with the system recovery set privilege.",
            default=False,
        )
