# pylint: disable=missing-module-docstring
import sys
import signal
import logging
import argparse
import configparser
import pdb

import tracemalloc

from taky import __version__
from taky.cot import COTServer
from taky.config import load_config

got_sigterm = False
want_snapshot = False


def handle_term(sig, frame):  # pylint: disable=unused-argument
    """ Signal handler """
    global got_sigterm
    logging.info("Got SIGTERM")
    got_sigterm = True


def handle_pdb(sig, frame):  # pylint: disable=unused-argument
    """ Signal handler """
    pdb.Pdb().set_trace(frame)


def handle_tracemalloc(sig, frame):  # pylint: disable=unused-argument
    """ Signal handler """
    global want_snapshot
    want_snapshot = True


def arg_parse():
    """ Handle arguments """
    argp = argparse.ArgumentParser(description="Start the taky server")
    argp.add_argument(
        "-l",
        action="store",
        dest="log_level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log verbosity",
    )
    argp.add_argument(
        "-c",
        action="store",
        dest="cfg_file",
        default=None,
        help="Path to configuration file",
    )
    argp.add_argument(
        "-d",
        action="store_true",
        dest="debug",
        default=False,
        help="Allow attaching to PDB",
    )
    argp.add_argument(
        "--version", action="version", version="%%(prog)s version %s" % __version__
    )

    args = argp.parse_args()

    return (argp, args)


def main():
    """ taky COT server """
    global got_sigterm
    global want_snapshot
    ret = 0

    (argp, args) = arg_parse()
    logging.basicConfig(level=args.log_level.upper(), stream=sys.stderr)
    logging.info("taky v%s", __version__)

    try:
        load_config(args.cfg_file)
    except (FileNotFoundError, OSError):
        if args.cfg_file:
            argp.error(f"Unable to load config file: '{args.cfg_file}'")
        else:
            argp.error("Unable to load './taky.conf' or '/etc/taky.conf'")
    except configparser.ParsingError as exc:
        argp.error(exc)
        sys.exit(1)

    signal.signal(signal.SIGTERM, handle_term)

    # TODO: Check for ipv6 support
    if args.debug:
        signal.signal(signal.SIGUSR1, handle_pdb)
        signal.signal(signal.SIGUSR2, handle_tracemalloc)
        tracemalloc.start(5)

    cot_srv = COTServer()
    try:
        cot_srv.sock_setup()
    except Exception as exc:  # pylint: disable=broad-except
        logging.error("Unable to start COTServer: %s", exc)
        logging.debug("", exc_info=exc)
        cot_srv.shutdown()
        sys.exit(1)

    try:
        while not got_sigterm:
            cot_srv.loop()

            if want_snapshot:
                want_snapshot = False
                snapshot = tracemalloc.take_snapshot()
                stats = snapshot.statistics("lineno")

                logging.info("----- [ SNIP HERE ] -----")
                logging.info("COT Server: %4d clients", len(cot_srv.clients))
                logging.info("Router:     %4d clients", len(cot_srv.router.clients))
                logging.info(
                    "Persist:    %4d events", len(cot_srv.router.persist.events)
                )
                logging.info("Top Memory Usage:")

                for stat in stats[:25]:
                    logging.info(stat)

                logging.info("----- [ END SNIP  ] -----")
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # pylint: disable=broad-except
        logging.critical("Unhandled exception", exc_info=exc)
        ret = 1

    try:
        cot_srv.shutdown()
    except Exception as exc:  # pylint: disable=broad-except
        logging.critical("Exception during shutdown", exc_info=exc)
        ret = 1

    sys.exit(ret)


if __name__ == "__main__":
    main()
