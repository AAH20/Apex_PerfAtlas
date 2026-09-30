"""No network calls or execution of private benchmark specifications."""
import argparse
import json
from importlib.resources import files
from pathlib import Path
from .evidence import validate
from .compare import compare
from .economics import evaluate


def load(path):
    return json.loads(Path(path).read_text())


def main(argv=None):
    parser=argparse.ArgumentParser(prog="apex-atlas")
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("catalog")
    v=commands.add_parser("validate");v.add_argument("record")
    c=commands.add_parser("compare");c.add_argument("baseline");c.add_argument("candidate");c.add_argument("--allow-platform-change",action="store_true")
    e=commands.add_parser("economics");e.add_argument("scenario")
    s=commands.add_parser("suggest");s.add_argument("family")
    args=parser.parse_args(argv)
    try:
        if args.command=="catalog":
            result=json.loads(files("apex_perfatlas").joinpath("data/catalog.json").read_text())
        elif args.command=="validate":
            errors=validate(load(args.record),Path(args.record).parent)
            result={"structurally_and_semantically_valid":not errors,"errors":errors,"validation_scope":"Local artifacts and consistency; claimed independent receipts are not authenticated."}
        elif args.command=="compare":
            result=compare(load(args.baseline),load(args.candidate),Path(args.baseline).parent,Path(args.candidate).parent,args.allow_platform_change)
        elif args.command=="economics": result=evaluate(load(args.scenario))
        else:
            catalog=json.loads(files("apex_perfatlas").joinpath("data/catalog.json").read_text())
            matches=[b for b in catalog["benchmark_families"] if b["id"].lower()==args.family.lower()]
            if not matches: raise ValueError("unknown family; inspect apex-atlas catalog")
            result={"family":matches[0],"proposal_status":"hypotheses requiring authorized specification and experiments","ranking":"No cross-family composite score or predicted record win."}
        print(json.dumps(result,indent=2,allow_nan=False))
        if args.command=="validate" and result["errors"]: return 2
        if args.command=="compare" and not result["eligible"]: return 2
        return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(json.dumps({"error":str(error)}));return 2


if __name__=="__main__": raise SystemExit(main())
