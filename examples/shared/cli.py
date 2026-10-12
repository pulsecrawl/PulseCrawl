"""Argument parsing and resource ownership for the example entry points."""

import argparse
import os
from pathlib import Path

from pulsecrawl import PulseCrawl, Workspace

from .catalog import CASES
from .hosted import HostedCaseProvisioner
from .local import LocalCaseProvisioner
from .safety import operator_user_agent


def _arguments(mode, case_key, argv):
    parser = argparse.ArgumentParser(description=f"Provision {mode} example jobs.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", choices=sorted(CASES), default=case_key)
    selection.add_argument("--all", action="store_true")
    parser.add_argument(
        "--run", action="store_true", help="explicitly start live crawling"
    )
    parser.add_argument(
        "--schedule", metavar="CRON", help="enable future live crawling"
    )
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--user-agent", default=os.environ.get("PULSECRAWL_USER_AGENT"))
    if mode == "local":
        parser.add_argument("--workspace", type=Path, default=Path("./workspace"))
    args = parser.parse_args(argv)
    if not args.all and not args.case:
        parser.error("pass --case or --all")
    if (args.run or args.schedule) and not args.user_agent:
        parser.error("live crawling requires --user-agent with an operator contact")
    if args.user_agent:
        try:
            args.user_agent = operator_user_agent(args.user_agent)
        except ValueError as error:
            parser.error(str(error))
    return parser, args


def _run(provisioner, args):
    selected = list(CASES.values()) if args.all else [CASES[args.case]]
    for case in selected:
        result = provisioner.provision(
            case,
            run=args.run,
            cron=args.schedule,
            timezone=args.timezone,
            user_agent=args.user_agent,
        )
        execution = result["execution"]
        suffix = f", execution={execution['executionId']}" if execution else ""
        print(
            f"{case.key}: job={result['job']['jobId']}, "
            f"dataset={result['dataset']['datasetId']}, "
            f"sources={result['sourceCount']}, seeds={result['seedCount']}, "
            f"templates={result['templateCount']}{suffix}"
        )


def main_local(case_key=None, argv=None):
    _parser, args = _arguments("local", case_key, argv)
    with Workspace.init(args.workspace) as workspace:
        _run(LocalCaseProvisioner(workspace), args)


def main_hosted(case_key=None, argv=None):
    parser, args = _arguments("hosted", case_key, argv)
    api_key = os.environ.get("PULSECRAWL_API_KEY")
    base_url = os.environ.get("PULSECRAWL_BASE_URL")
    if not api_key or not base_url:
        parser.error("set PULSECRAWL_API_KEY and PULSECRAWL_BASE_URL")
    with PulseCrawl(api_key=api_key, base_url=base_url) as client:
        _run(HostedCaseProvisioner(client), args)
