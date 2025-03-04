###
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
###

# -*- coding: utf-8 -*-
""" Certificates Command for rdmc """

from argparse import ArgumentParser, RawDescriptionHelpFormatter
from logging import exception
import time

try:
    from rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        InvalidFileInputError,
        IncompatibleiLOVersionError,
        Encryption,
        IloLicenseError,
        ScepenabledError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        InvalidFileInputError,
        IncompatibleiLOVersionError,
        Encryption,
        IloLicenseError,
        ScepenabledError,
    )


__filename__ = "certificate.txt"

from redfish.ris import IdTokenError


class CertificateCommand:
    """Commands Certificates actions to the server"""

    def __init__(self):
        self.ident = {
            "name": "certificate",
            "usage": None,
            "description": "Generate a certificate signing request (CSR) or import an X509 formatted"
            " TLS or CA certificate.\n Import Scep Certificate  \n Invoke Auto Enroll of certificate generation\n"
            "NOTE: Use quotes to include parameters which contain whitespace when "
            'generating a CSR.\nexample: certificate gen_csr "Hewlett Packard Enterprise"'
            '"iLORest Group" "CName"\n"United States" "False\True" "Texas" "Houston"',
            "summary": "Command for importing both iLO and login authorization "
            "certificates as well as generating iLO certificate signing requests (CSR)",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.view = None
        self.importcert = None
        self.delete = None
        self.gencsr = None
        self.autoenroll = None

    def run(self, line, help_disp=False):
        """Main Certificates Command function

        :param options: list of options
        :type options: list.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            line.append("-h")
            try:
                (_, _) = self.rdmc.rdmc_parse_arglist(self, line)
            except:
                return ReturnCodes.SUCCESS
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

        self.certificatesvalidation(options)

        returnCode = None

        if options.command == "csr":
            returnCode = self.generatecerthelper(options)
        elif options.command == "ca":
            self.importcahelper(options)
        elif options.command == "getcsr":
            returnCode = self.getcerthelper(options)
        elif options.command == "crl":
            self.importcrlhelper(options)
        elif options.command == "tls":
            returnCode = self.importtlshelper(options)
        if "view" in options.command.lower():
            self.view = True
            self.importcert = False
            self.delete = False
            self.gencsr = False
            self.autoenroll = False
        elif "import" in options.command.lower():
            self.view = False
            self.importcert = True
            self.delete = False
            self.gencsr = False
            self.autoenroll = False
        elif "delete" in options.command.lower():
            self.view = False
            self.importcert = False
            self.delete = True
            self.gencsr = False
            self.autoenroll = False
        elif "gen_csr" in options.command.lower():
            self.view = False
            self.importcert = False
            self.delete = False
            self.gencsr = True
            self.autoenroll = False
        elif "auto_enroll" in options.command.lower():
            self.view = False
            self.importcert = False
            self.delete = False
            self.gencsr = False
            self.autoenroll = True

        if self.view:
            returnCode = self.viewfunction(options)
        elif self.importcert:
            returnCode = self.importfunction(options)
        elif self.delete:
            returnCode = self.deletefunction(options)
        elif self.gencsr:
            returnCode = self.gencsrfunction(options)
        elif self.autoenroll:
            if self.rdmc.app.typepath.defs.isgen10:
                returnCode = self.autoenrollfunction(options)
            else:
                self.rdmc.ui.printer("Gen 9 doesnt support this feature\n")
                returnCode = ReturnCodes.SUCCESS

        self.cmdbase.logout_routine(self, options)
        # Return code
        return returnCode

    def autoenrollfunction(self, options):
        """Automatic Scep cert enrollement process

        :param options: list of options
        :type options: list.
        """
        select = self.rdmc.app.typepath.defs.securityservice
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict

        try:
            for item in bodydict["Links"]:
                if "AutomaticCertificateEnrollment" in item:
                    path = bodydict["Links"]["AutomaticCertificateEnrollment"][
                        "@odata.id"
                    ]
                    break
        except:
            path = path + "AutomaticCertificateEnrollment"

        body = {
            "AutomaticCertificateEnrollmentSettings": {
                "ServiceEnabled": eval(options.autoenroll_ScepService.strip('"')),
                "ServerUrl": options.autoenroll_scep_enrollAddress.strip('"'),
                "ChallengePassword": options.autoenroll_challengepassword.strip('"'),
            },
            "HttpsCertCSRSubjectValue": {
                "OrgName": options.autoenroll_orgname.strip('"'),
                "OrgUnit": options.autoenroll_orgunit.strip('"'),
                "CommonName": options.autoenroll_commonname.strip('"'),
                "Country": options.autoenroll_country.strip('"'),
                "State": options.autoenroll_state.strip('"'),
                "City": options.autoenroll_city.strip('"'),
                "IncludeIP": eval(options.autoenroll_includeIP.strip('"')),
            },
        }

        try:

            results = self.rdmc.app.patch_handler(path, body,silent=True)

            i=0
            results1 = self.rdmc.app.get_handler(path, silent=True)
            while i<9 and (results1.dict["AutomaticCertificateEnrollmentSettings"]['CertificateEnrollmentStatus'] == "InProgress"):
                results1 = self.rdmc.app.get_handler(path, silent=True)
                time.sleep(1)
                i=i+1

            if results.status == 200 and (not (results1.dict["AutomaticCertificateEnrollmentSettings"]['CertificateEnrollmentStatus'] == "Failed")):
                return ReturnCodes.SUCCESS
            elif results.status == 400:
                self.rdmc.ui.error(
                    "There was a problem with auto enroll, Please check whether Scep CA cert is imported \t\n")

                return ReturnCodes.SCEP_ENABLED_ERROR
            else:
                self.rdmc.ui.error("There was a problem with auto enroll, Plese Check the Url\Password whether it is correct\n")
                return ReturnCodes.SCEP_ENABLED_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("License Error Occured while auto enroll\n")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IdTokenError:
            self.rdmc.ui.printer(
                "Insufficient Privilege to auto enroll scep certificate process\n"
            )
            return ReturnCodes.RIS_MISSING_ID_TOKEN

    def gencsrfunction(self, options):
        """Main Certificates Command function

        :param options: list of options
        :type options: list.
        """
        try:
            select = self.rdmc.app.typepath.defs.hphttpscerttype
            results = self.rdmc.app.select(selector=select)
            try:
                results = results[0]
            except:
                pass

            if results:
                path = results.resp.request.path
            else:
                raise NoContentsFoundForOperationError("Unable to find %s" % select)

            bodydict = results.resp.dict

            try:
                for item in bodydict["Actions"]:
                    if "GenerateCSR" in item:
                        if self.rdmc.app.typepath.defs.isgen10:
                            action = item.split("#")[-1]
                        else:
                            action = "GenerateCSR"

                        path = bodydict["Actions"][item]["target"]
                        break
            except:
                action = "GenerateCSR"
        except:
            path = "redfish/v1/Managers/1/SecurityService/HttpsCert"
            action = "GenerateCSR"

        body = {
            "Action": action,
            "OrgName": options.gencsr_orgname.strip('"'),
            "OrgUnit": options.gencsr_orgunit.strip('"'),
            "CommonName": options.gencsr_commonname.strip('"'),
            "Country": options.gencsr_country.strip('"'),
            "State": options.gencsr_state.strip('"'),
            "City": options.gencsr_city.strip('"'),
            "IncludeIP": eval(options.gencsr_parser_includeIP.strip('"')),
        }

        try:
            results = self.rdmc.app.post_handler(path, body)
            if results.status == 200:
                return ReturnCodes.SUCCESS
        except ScepenabledError:
            self.rdmc.ui.printer("SCEP is enabled , CSR cant be generated \n")
            return ReturnCodes.SCEP_ENABLED_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("License Error Occured while generating CSR")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to generate CSR\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN

    def deletefunction(self, options):
        """Certificate Delete Function

        :param options: list of options
        :type options: list.
        """

        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        try:
            results = self.rdmc.app.delete_handler(path, silent=True)
            if results.status == 200:
                self.rdmc.ui.printer("Deleted the https certifcate successfully\n")
                return ReturnCodes.SUCCESS
            if results.status == 403:
                self.rdmc.ui.error("Insufficient Privilege to delete certificate\n")
                return ReturnCodes.RIS_MISSING_ID_TOKEN
            if results.status == 400:
                self.rdmc.ui.error("SCEP is enabled , Cant delete the certificate\n")
                return ReturnCodes.SCEP_ENABLED_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("License Error Occured while delete")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error(
                "iLO FW version on this server doesnt support this operation"
            )
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def viewfunction(self, options):
        """View scep certifcates or https certificates

        :param options: list of options
        :type options: list.
        """

        if options.scep_cert:
            if self.rdmc.app.typepath.defs.isgen10:
                self.view_scepcertificate()  # View scep certificates
            else:
                self.rdmc.ui.printer("Feature not supported on Gen 9\n")
                return ReturnCodes.SUCCESS
        if options.https_cert:
            self.view_httpscertificate()  # View https certificates

    def view_scepcertificate(self):
        """
        View Scep certificate
        """
        select = self.rdmc.app.typepath.defs.securityservice
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict

        try:
            for item in bodydict["Links"]:
                if "AutomaticCertificateEnrollment" in item:
                    path = bodydict["Links"]["AutomaticCertificateEnrollment"][
                        "@odata.id"
                    ]
                    break
        except:
            path = path + "AutomaticCertificateEnrollment"

        try:
            results = self.rdmc.app.get_handler(path, silent=True)
            if results.status == 200:
                self.rdmc.ui.printer("Scep Certificate details ...\n")
                results = results.dict
                self.print_cert_info(results)
                return ReturnCodes.SUCESS

        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while Uninstall")
            return ReturnCodes.ILO_LICENSE_ERROR

    def print_cert_info(self, results):
        """
        Prints the cert info
        """
        for key, value in results.items():
            if "@odata" not in key:
                if type(value) is dict:
                    self.print_cert_info(value)
                else:
                    self.rdmc.ui.printer(key + ":" + str(value) + "\n")

    def view_httpscertificate(self):
        """
        View Https certificate
        """
        try:
            select = self.rdmc.app.typepath.defs.hphttpscerttype
            results = self.rdmc.app.select(selector=select)

            try:
                results = results[0]
            except:
                pass

            if results:
                path = results.resp.request.path
            else:
                raise NoContentsFoundForOperationError("Unable to find %s" % select)
        except:
            path = "redfish/v1/Managers/1/SecurityService/HttpsCert"

        try:
            results = self.rdmc.app.get_handler(path, silent=True)
            if results.status == 200:
                self.rdmc.ui.printer("Https Certificate details ...\n")
                results = results.dict
                self.print_cert_info(results)
                return ReturnCodes.SUCESS
        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while Uninstall")
            return ReturnCodes.ILO_LICENSE_ERROR

    def importfunction(self, options):
        if options.scep:
            if self.rdmc.app.typepath.defs.isgen10:
                return self.importfunctionhelper(options)
            else:
                self.rdmc.ui.printer("Gen 9 doesnt support this feature\n")
                return ReturnCodes.SUCCESS

    def importfunctionhelper(self, options):
        """
        Import Scep certificate
        """
        select = self.rdmc.app.typepath.defs.securityservice
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict

        try:
            for item in bodydict["Links"]:
                if "AutomaticCertificateEnrollment" in item:
                    path = bodydict["Links"]["AutomaticCertificateEnrollment"][
                        "@odata.id"
                    ]
                    break
        except:
            path = path + "AutomaticCertificateEnrollment"

        path = path + "Actions/HpeAutomaticCertEnrollment.ImportCACertificate"

        action = "HpeAutomaticCertEnrollment.ImportCACertificate"

        certdata = None
        scep_CACert = options.scep_certfile

        try:
            with open(scep_CACert) as certfile:
                certdata = certfile.read()
                certfile.close()
        except:
            pass

        body = {"Action": action, "Certificate": certdata}

        try:
            result = self.rdmc.app.post_handler(path, body)
            if result.status == 200:
                self.rdmc.ui.printer("Imported the scep certificate successfully\n")
                return ReturnCodes.SUCCESS
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to import scep CA certificate\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN
        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while importing scep certificate")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error(
                "iLO FW version on this server doesnt support this operation"
            )
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def generatecerthelper(self, options):
        """Main Certificates Command function

        :param options: list of options
        :type options: list.
        """
        self.rdmc.ui.printer(
            "Warning:Command CSR has been replaced with Gen_csr comamnd and CSR command will be deprecated in next release of our tool. Please plan to use gen_csr command instead \n"
        )
        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict

        try:
            for item in bodydict["Actions"]:
                if "GenerateCSR" in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = "GenerateCSR"

                    path = bodydict["Actions"][item]["target"]
                    break
        except:
            action = "GenerateCSR"

        body = {
            "Action": action,
            "OrgName": options.csr_orgname.strip('"'),
            "OrgUnit": options.csr_orgunit.strip('"'),
            "CommonName": options.csr_commonname.strip('"'),
            "Country": options.csr_country.strip('"'),
            "State": options.csr_state.strip('"'),
            "City": options.csr_city.strip('"'),
        }

        self.rdmc.ui.printer(
            "iLO is creating a new certificate signing request. "
            "This process can take up to 10 minutes.\n"
        )

        try:
            self.rdmc.app.post_handler(path, body)
            return ReturnCodes.SUCCESS
        except ScepenabledError:
            self.rdmc.ui.printer("SCEP is enabled , operation not allowed \n")
            return ReturnCodes.SCEP_ENABLED_ERROR

    def getcerthelper(self, options):
        """Helper function for importing CRL certificate

        :param options: list of options
        :type options: list.
        """

        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select, path_refresh=True)

        try:
            results = results[0]
        except:
            pass

        if results:
            try:
                csr = results.resp.dict["CertificateSigningRequest"]
                if not csr:
                    raise ValueError
            except (KeyError, ValueError):
                raise NoContentsFoundForOperationError(
                    "Unable to find a valid certificate. If "
                    "you just generated a new certificate "
                    "signing request the process may take "
                    "up to 10 minutes."
                )

            if not options.filename:
                filename = __filename__
            else:
                filename = options.filename[0]

            outfile = open(filename, "w")
            outfile.write(csr)
            outfile.close()

            self.rdmc.ui.printer("Certificate saved to: %s\n" % filename)
            return ReturnCodes.SUCCESS
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

    def importtlshelper(self, options):
        """Helper function for importing TLS certificate

        :param options: list of options
        :type options: list.
        """
        tlsfile = options.certfile

        try:
            with open(tlsfile) as certfile:
                certdata = certfile.read()
                certfile.close()
        except:
            raise InvalidFileInputError("Error loading the specified file.")

        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict
        try:
            for item in bodydict["Actions"]:
                if "ImportCertificate" in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = "ImportCertificate"
                    path = bodydict["Actions"][item]["target"]
                    break
        except:
            action = "ImportCertificate"

        body = {"Action": action, "Certificate": certdata}

        try:
            self.rdmc.app.post_handler(path, body)
            return ReturnCodes.SUCCESS
        except ScepenabledError:
            self.rdmc.ui.printer("SCEP is enabled , operation not allowed \n")
            return ReturnCodes.SCEP_ENABLED_ERROR

    def importcrlhelper(self, options):
        """Helper function for importing CRL certificate

        :param options: list of options
        :type options: list.
        """
        if not self.rdmc.app.typepath.flagiften:
            raise IncompatibleiLOVersionError(
                "This certificate is not available on this system."
            )

        select = "HpeCertAuth."
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            bodydict = results.resp.dict
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        for item in bodydict["Actions"]:
            if "ImportCRL" in item:
                action = item.split("#")[-1]
                path = bodydict["Actions"][item]["target"]
                break

        body = {"Action": action, "ImportUri": options.certfile_url}

        self.rdmc.app.post_handler(path, body)

    def importcahelper(self, options):
        """Helper function for importing CA certificate

        :param options: list of options
        :type options: list.
        """
        if not self.rdmc.app.typepath.flagiften:
            raise IncompatibleiLOVersionError(
                "This certificate is not available on this system."
            )

        tlsfile = options.certfile

        try:
            with open(tlsfile) as certfile:
                certdata = certfile.read()
                certfile.close()
        except:
            raise InvalidFileInputError("Error loading the specified file.")

        select = "HpeCertAuth."
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            bodydict = results.resp.dict
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        for item in bodydict["Actions"]:
            if "ImportCACertificate" in item:
                action = item.split("#")[-1]
                path = bodydict["Actions"][item]["target"]
                break

        body = {"Action": action, "Certificate": certdata}

        self.rdmc.app.post_handler(path, body)

    def certificatesvalidation(self, options):
        """certificates validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for certificates command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        subcommand_parser = customparser.add_subparsers(dest="command")

        # gen csr sub-parser
        gen_csr_help = (
            "Generate a certificate signing request (CSR) for iLO SSL certificate "
            "authentication.\nNote: iLO will create a Base64 encoded CSR in PKCS "
            "#10 Format."
        )
        gen_csr_parser = subcommand_parser.add_parser(
            "csr",
            help=gen_csr_help,
            description=gen_csr_help + "\nexample: certificate csr [ORG_NAME] [ORG_UNIT]"
            " [COMMON_NAME] [COUNTRY] [STATE] [CITY]\n\nNOTE: please make "
            "certain the order of arguments is correct.",
            formatter_class=RawDescriptionHelpFormatter,
        )
        gen_csr_parser.add_argument(
            "csr_orgname",
            help="Organization name. i.e. Hewlett Packard Enterprise.",
            metavar="ORGNAME",
        )
        gen_csr_parser.add_argument(
            "csr_orgunit",
            help="Organization unit. i.e. Intelligent Provisioning.",
            metavar="ORGUNIT",
        )
        gen_csr_parser.add_argument(
            "csr_commonname",
            help="Organization common name. i.e. Common Organization Name.",
            metavar="ORGNAME",
        )
        gen_csr_parser.add_argument(
            "csr_country",
            help="Organization country. i.e. United States.",
            metavar="ORGCOUNTRY",
        )
        gen_csr_parser.add_argument(
            "csr_state", help="Organization state. i.e. Texas.", metavar="ORGSTATE"
        )
        gen_csr_parser.add_argument(
            "csr_city", help="Organization city. i.e. Houston.", metavar="ORGCITY"
        )
        self.cmdbase.add_login_arguments_group(gen_csr_parser)

        # get csr
        get_csr_help = (
            "Retrieve the generated certificate signing request (CSR) printed to the "
            "console or to a json file."
        )
        get_csr_parser = subcommand_parser.add_parser(
            "getcsr",
            help=get_csr_help,
            description=get_csr_help
            + "\nexample: certificate getcsr\nexample: certificate getcsr "
            "-f mycsrfile.json",
            formatter_class=RawDescriptionHelpFormatter,
        )
        get_csr_parser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag if you wish to use a different"
            " filename for the certificate signing request. The default"
            " filename is %s." % __filename__,
            action="append",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(get_csr_parser)

        # ca certificate
        ca_help = "Upload a X.509 formatted CA certificate to iLO."
        ca_parser = subcommand_parser.add_parser(
            "ca",
            help=ca_help,
            description=ca_help + "\nexample: certificate ca mycertfile.txt\nNote: The "
            "certificate must be in X.509 format",
            formatter_class=RawDescriptionHelpFormatter,
        )
        ca_parser.add_argument(
            "certfile", help="X.509 formatted CA certificate", metavar="CACERTFILE"
        )
        self.cmdbase.add_login_arguments_group(ca_parser)

        # crl certificate
        crl_help = (
            "Provide iLO with a URL to retrieve the X.509 formatted CA certificate."
        )
        crl_parser = subcommand_parser.add_parser(
            "crl",
            help=crl_help,
            description=crl_help
            + "\nexample: certificate crl https://mycertfileurl/mycertfile.txt"
            "\nNote: The certificate must be in X.509 format",
            formatter_class=RawDescriptionHelpFormatter,
        )
        crl_parser.add_argument(
            "certfile_url",
            help="URL pointing to the location of the X.509 CA certificate",
            metavar="CERTFILEURL",
        )
        self.cmdbase.add_login_arguments_group(crl_parser)

        # tls certificate
        tls_help = "Upload a X.509 TLS certificate to iLO."
        tls_parser = subcommand_parser.add_parser(
            "tls",
            help=tls_help,
            description=tls_help + "\nexample: certificate tls mycertfile.txt\nNote: The "
            "certificate must be in TLS X.509 format",
            formatter_class=RawDescriptionHelpFormatter,
        )
        tls_parser.add_argument(
            "certfile", help="X.509 formatted TLS certificate", metavar="TLSCERTFILE"
        )
        self.cmdbase.add_login_arguments_group(tls_parser)

        # view certificate
        view_help = "View Certificates (https or scep)"
        view_parser = subcommand_parser.add_parser(
            "view",
            help=view_help,
            description=view_help
            + "\nexample: certificate view --https_cert  \n or \n certificate view --scep_cert \n  Webserver certificate whether self-signed or manually imported or issued by SCEP server can be viewed",
            formatter_class=RawDescriptionHelpFormatter,
        )
        view_parser.add_argument(
            "--scep_cert",
            dest="scep_cert",
            help="Gets the information of SCEP settings for iLO such as SCEP enable status, URL of the SCEP server, ChallengePassword, SCEP CA certificate name, webserver CSR subject contents, SCEP enrollment status",
            action="store_true",
        )
        view_parser.add_argument(
            "--https_cert",
            dest="https_cert",
            help="Gets the https certificate whether self-signed or manually imported or issued by SCEP server",
            action="store_true",
        )
        self.cmdbase.add_login_arguments_group(view_parser)

        # import certificate
        import_help = "Imports the scep Certificate"
        import_parser = subcommand_parser.add_parser(
            "import",
            help=import_help,
            description=import_help
            + "\nexample: certificate import --scep certificate.txt \n  make sure you are providing a .txt file input",
            formatter_class=RawDescriptionHelpFormatter,
        )
        import_parser.add_argument(
            "--scep",
            dest="scep",
            help="Gets the https certificate whether self-signed or manually imported or issued by SCEP server",
            action="store_true",
        )
        import_parser.add_argument(
            "scep_certfile",
            help="SCEP CA certificate can be imported via POST action",
            metavar="scep_certfile",
        )

        self.cmdbase.add_login_arguments_group(import_parser)

        # delete certificate
        delete_help = "Deletes the https Certificate"
        delete_parser = subcommand_parser.add_parser(
            "delete",
            help=delete_help,
            description=delete_help
            + "\nexample: certificate delete \n  delete the https_cert certificate ",
            formatter_class=RawDescriptionHelpFormatter,
        )

        self.cmdbase.add_login_arguments_group(delete_parser)

        # gen csr sub-parser
        gencsr_help = (
            "Generate a certificate signing request (CSR) for iLO SSL certificate "
            "authentication.\nNote: iLO will create a Base64 encoded CSR in PKCS "
            "#10 Format."
        )
        gencsr_parser = subcommand_parser.add_parser(
            "gen_csr",
            help=gencsr_help,
            description=gen_csr_help
            + "\nexample: certificate gen_csr [ORG_NAME] [ORG_UNIT]"
            " [COMMON_NAME] [COUNTRY] [STATE] [CITY] [INCLUDEIP] \n\nNOTE: please make "
            "certain the order of arguments is correct.",
            formatter_class=RawDescriptionHelpFormatter,
        )
        gencsr_parser.add_argument(
            "gencsr_orgname",
            help="Organization name. i.e. Hewlett Packard Enterprise.",
            metavar="ORGNAME",
        )
        gencsr_parser.add_argument(
            "gencsr_orgunit",
            help="Organization unit. i.e. Intelligent Provisioning.",
            metavar="ORGUNIT",
        )
        gencsr_parser.add_argument(
            "gencsr_commonname",
            help="Organization common name. i.e. Common Organization Name.",
            metavar="ORGNAME",
        )
        gencsr_parser.add_argument(
            "gencsr_country",
            help="Organization country. i.e. United States.",
            metavar="ORGCOUNTRY",
        )
        gencsr_parser.add_argument(
            "gencsr_state", help="Organization state. i.e. Texas.", metavar="ORGSTATE"
        )
        gencsr_parser.add_argument(
            "gencsr_city", help="Organization city. i.e. Houston.", metavar="ORGCITY"
        )
        gencsr_parser.add_argument(
            "gencsr_parser_includeIP",
            help="Include IP. i.e. True\False.",
            metavar="INCLUDEIP",
        )
        self.cmdbase.add_login_arguments_group(gencsr_parser)

        # automatic enrollment sub-parser
        autoenroll_help = (
            "Use this command for invoking the auto enroll the certificate enrollment process"
            "\nMake sure you have imported the scep CA certificate before head using certificate import --scep certifcate.txt"
        )
        autoenroll_parser = subcommand_parser.add_parser(
            "auto_enroll",
            help=autoenroll_help,
            description=autoenroll_help
            + "\nexample: certificate auto_enroll [ORG_NAME] [ORG_UNIT]"
            " [COMMON_NAME] [COUNTRY] [STATE] [CITY] [SCEP_ADDRESS] [CHALLENGEPASSWORD] [SERVICEENABLED] [INCLUDEIP]]\n\nNOTE: please make "
            "certain the order of arguments is correct.",
            formatter_class=RawDescriptionHelpFormatter,
        )
        autoenroll_parser.add_argument(
            "autoenroll_orgname",
            help="Organization name. i.e. Hewlett Packard Enterprise.",
            metavar="ORGNAME",
        )
        autoenroll_parser.add_argument(
            "autoenroll_orgunit",
            help="Organization unit. i.e. Intelligent Provisioning.",
            metavar="ORGUNIT",
        )
        autoenroll_parser.add_argument(
            "autoenroll_commonname",
            help="Organization common name. i.e. Common Organization Name.",
            metavar="ORGNAME",
        )
        autoenroll_parser.add_argument(
            "autoenroll_country",
            help="Organization country. i.e. United States.",
            metavar="ORGCOUNTRY",
        )
        autoenroll_parser.add_argument(
            "autoenroll_state", help="Organization state. i.e. Texas.", metavar="ORGSTATE"
        )
        autoenroll_parser.add_argument(
            "autoenroll_city", help="Organization city. i.e. Houston.", metavar="ORGCITY"
        )
        autoenroll_parser.add_argument(
            "autoenroll_scep_enrollAddress",
            help="Scep-enroll dll address",
            metavar="AEADDRESS",
        )
        autoenroll_parser.add_argument(
            "autoenroll_challengepassword",
            help="challenge password",
            metavar="AECHALLPASS",
        )
        autoenroll_parser.add_argument(
            "autoenroll_ScepService",
            help="Scep service enable\disable",
            metavar="AESECPSERVICE",
        )
        autoenroll_parser.add_argument(
            "autoenroll_includeIP",
            help="Include IP. i.e. True\False.",
            metavar="INCLUDEIP",
        )
        self.cmdbase.add_login_arguments_group(autoenroll_parser)
