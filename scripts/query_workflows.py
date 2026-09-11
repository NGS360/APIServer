#!/usr/bin/env python3
"""Query registered workflows on NGS360.

Read-only inventory tool for humans: list workflows, drill into one, list
deployments across the system, and find a workflow by name. Ships alongside
`register_ngs360_workflow.sh` (in WES-Launcher-new) so you can see what
already exists before registering or updating.

Unlike the other scripts in this folder (reindex.py, promote_superuser.py,
etc.) this talks to the API over HTTPS rather than the DB directly. It's
intended for users, so it runs from anywhere and does not require a DB
session or a checkout of the API code.

Environment:
  NGS360_AUTH_TOKEN  Bearer token. Optional — reads are anonymous on
                     ngs.rdcloud.bms.com today; supply a token if the
                     deployment you're pointing at requires auth.
  NGS360_API_URL     API base URL, defaults to https://ngs.rdcloud.bms.com/api/v1

Usage:
  query_workflows.py list-workflows [--name <substring>] [--latest] [--json]
  query_workflows.py show-workflow <workflow-id> [--json]
  query_workflows.py list-deployments [--engine <name>] [--json]
  query_workflows.py find-workflow <substring> [--json]

Examples:
  query_workflows.py list-workflows --latest
  query_workflows.py show-workflow f8a5371c-21ff-49cb-af3c-03e78ba4df09
  query_workflows.py list-deployments --engine "AWSHealthOmics (us-east)"
  query_workflows.py find-workflow WES
"""

import argparse
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API_URL = "https://ngs.rdcloud.bms.com/api/v1"
PER_PAGE = 100


def die(msg):
    sys.exit("error: " + msg)


def api_get(endpoint, path, token, attempts=3):
    """GET a path under the API endpoint and return the decoded JSON body.

    Big pages occasionally come back truncated (http.client.IncompleteRead),
    so transport-level failures are retried. HTTP error statuses are not
    retried — they will just come back the same.
    """
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(endpoint + path)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            hint = (
                " (is NGS360_AUTH_TOKEN set and current?)"
                if exc.code in (401, 403) else ""
            )
            die("GET %s returned HTTP %s%s" % (path, exc.code, hint))
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            ValueError,
        ) as exc:
            if attempt == attempts:
                die("GET %s failed after %d attempts: %s" % (path, attempts, exc))
            time.sleep(attempt)


def fetch_all_workflows(endpoint, token):
    """Walk /workflows until a short page comes back."""
    workflows = []
    page = 1
    while True:
        chunk = api_get(
            endpoint,
            "/workflows?page=%d&per_page=%d&sort_by=name&sort_order=asc"
            % (page, PER_PAGE),
            token,
        )
        workflows.extend(chunk)
        if len(chunk) < PER_PAGE:
            break
        page += 1
    return workflows


# ---- shared formatting helpers ---------------------------------------------

def omics_id(dep):
    """Trim the ARN to the part that identifies the Omics workflow.

    arn:aws:omics:us-east-1:483421617021:workflow/1324105/version/6
        -> 1324105/version/6
    """
    ext = (dep or {}).get("external_id") or ""
    _, sep, tail = ext.partition(":workflow/")
    return tail if sep else ext


def short_definition(uri):
    """Shorten a github blob URL to <repo>@<short-sha>:<path>; pass others through."""
    prefix = "https://github.com/"
    if uri.startswith(prefix) and "/blob/" in uri:
        owner_repo, _, rest = uri[len(prefix):].partition("/blob/")
        sha, _, sub_path = rest.partition("/")
        return "%s@%s:%s" % (owner_repo.split("/")[-1], sha[:7], sub_path)
    return uri


def when(timestamp):
    return (timestamp or "").replace("T", " ")[:16]


def short_commit(commit):
    """Shorten a git_commit value to 7-char SHA, keeping the +dirty suffix
    if present. Empty input becomes '-' for table display."""
    if not commit:
        return "-"
    sha, sep, suffix = commit.partition("+")
    return sha[:7] + (sep + suffix if sep else "")


def print_table(rows, headers):
    """Print rows as a padded text table; last column left unpadded."""
    cells = [tuple(headers)] + [tuple(r) for r in rows]
    widths = [max(len(c[i]) for c in cells) for i in range(len(headers))]
    for cell in cells:
        padded = "  ".join(
            cell[i].ljust(widths[i]) for i in range(len(headers) - 1)
        )
        print("  %s  %s" % (padded, cell[-1]))


def deployment_rows(wf):
    """One row per deployment for a workflow. Versions with no deployment
    still get a row so the version doesn't vanish from the display.

    Also captures git_ref / git_commit off the version's attributes, if
    the caller has enriched the workflow via merge_version_attributes.
    Absent attributes leave those fields as "-".
    """
    aliases_by_version = {}
    for alias in wf.get("aliases") or []:
        aliases_by_version.setdefault(alias.get("version"), []).append(
            alias.get("alias")
        )

    rows = []
    for ver in wf.get("versions") or []:
        num = ver.get("version")
        tags = ",".join(sorted(aliases_by_version.get(num) or [])) or "-"
        attrs = {
            a.get("key"): (a.get("value") or "")
            for a in (ver.get("attributes") or [])
            if a.get("key")
        }
        git_ref = attrs.get("git_ref") or "-"
        git_commit = short_commit(attrs.get("git_commit"))
        for dep in ver.get("deployments") or [None]:
            rows.append({
                "version": str(num),
                "created": when(ver.get("created_at")),
                "engine": (dep or {}).get("engine") or "-",
                "omics": omics_id(dep) if dep else "-",
                "arn": (dep or {}).get("external_id") or "",
                "aliases": tags,
                "definition": ver.get("definition_uri") or "",
                "git_ref": git_ref,
                "git_commit": git_commit,
            })
    return rows


def render_workflow(wf, show_git=False):
    """Print one workflow's block: header + versions/deployments table.

    ``show_git`` adds GIT_REF and GIT_COMMIT columns (in that order) before
    ALIASES. Left off by default because list-workflows doesn't fetch
    version attributes; the columns would just show '-' for every row.
    show-workflow flips it on after enriching via merge_version_attributes.
    """
    print(wf.get("name") or "(unnamed)")
    print("  workflow id  %s" % wf.get("id"))
    print("  created      %s by %s" % (
        when(wf.get("created_at")), wf.get("created_by") or "?",
    ))
    rows = deployment_rows(wf)
    if not rows:
        print("  (no versions)")
        return 0, 0
    print()
    if show_git:
        table = [
            (
                r["version"],
                r["created"],
                r["engine"],
                r["omics"],
                r["git_ref"],
                r["git_commit"],
                r["aliases"],
                short_definition(r["definition"]),
            )
            for r in rows
        ]
        headers = (
            "VER", "CREATED", "ENGINE", "OMICS ID",
            "GIT_REF", "GIT_COMMIT", "ALIASES", "DEFINITION",
        )
    else:
        table = [
            (
                r["version"],
                r["created"],
                r["engine"],
                r["omics"],
                r["aliases"],
                short_definition(r["definition"]),
            )
            for r in rows
        ]
        headers = ("VER", "CREATED", "ENGINE", "OMICS ID", "ALIASES", "DEFINITION")
    print_table(table, headers)
    n_versions = len(wf.get("versions") or [])
    n_deployments = sum(1 for r in rows if r["arn"])
    return n_versions, n_deployments


# ---- subcommands -----------------------------------------------------------

def cmd_list_workflows(args, endpoint, token):
    workflows = fetch_all_workflows(endpoint, token)

    if args.name:
        needle = args.name.lower()
        workflows = [
            w for w in workflows if needle in (w.get("name") or "").lower()
        ]

    if args.latest:
        for wf in workflows:
            vers = sorted(
                wf.get("versions") or [], key=lambda v: v.get("version") or 0
            )
            wf["versions"] = vers[-1:]

    if args.json:
        print(json.dumps(workflows, indent=2))
        return

    if not workflows:
        print("no workflows matched" if args.name else "no workflows registered")
        return

    total_versions = total_deployments = 0
    for index, wf in enumerate(workflows):
        if index:
            print()
        v, d = render_workflow(wf)
        total_versions += v
        total_deployments += d

    print()
    print("%d workflow%s, %d version%s shown, %d deployment%s" % (
        len(workflows), "" if len(workflows) == 1 else "s",
        total_versions, "" if total_versions == 1 else "s",
        total_deployments, "" if total_deployments == 1 else "s",
    ))


def merge_version_attributes(wf, endpoint, token):
    """Enrich a workflow's nested versions with their `attributes` field.

    GET /workflows/{id} returns WorkflowVersionSummary shapes, which drop
    attributes for lightness. Read through /workflows/{id}/versions
    (WorkflowVersionPublic — includes attributes) and merge them back in
    so show-workflow can display git provenance and other version tags.
    """
    versions = api_get(
        endpoint, "/workflows/%s/versions" % wf.get("id"), token
    ) or []
    attrs_by_version = {
        v.get("version"): (v.get("attributes") or [])
        for v in versions
    }
    for ver in wf.get("versions") or []:
        ver["attributes"] = attrs_by_version.get(ver.get("version"), [])


def cmd_show_workflow(args, endpoint, token):
    wf = api_get(endpoint, "/workflows/%s" % args.workflow_id, token)
    merge_version_attributes(wf, endpoint, token)

    if args.json:
        print(json.dumps(wf, indent=2))
        return

    render_workflow(wf, show_git=True)


def cmd_list_deployments(args, endpoint, token):
    """Flatten every (workflow, version, deployment) into one table.

    Uses the /workflows response (which nests versions and deployments) so
    this is one paginated call, not N+1.
    """
    workflows = fetch_all_workflows(endpoint, token)

    entries = []
    for wf in workflows:
        for ver in wf.get("versions") or []:
            for dep in ver.get("deployments") or []:
                if args.engine and dep.get("engine") != args.engine:
                    continue
                entries.append({
                    "workflow_id": wf.get("id"),
                    "workflow_name": wf.get("name"),
                    "version": ver.get("version"),
                    "version_created_at": ver.get("created_at"),
                    "deployment_id": dep.get("id"),
                    "engine": dep.get("engine"),
                    "external_id": dep.get("external_id"),
                    "created_at": dep.get("created_at"),
                })

    if args.json:
        print(json.dumps(entries, indent=2))
        return

    if not entries:
        print(
            "no deployments matched"
            if args.engine
            else "no deployments registered"
        )
        return

    rows = [
        (
            e["workflow_name"] or "",
            str(e["version"]),
            e["engine"] or "-",
            omics_id(e),
            when(e["created_at"]),
            e["workflow_id"] or "",
        )
        for e in entries
    ]
    print_table(
        rows,
        ("WORKFLOW", "VER", "ENGINE", "OMICS ID", "DEPLOYED", "WORKFLOW ID"),
    )
    print()
    print(
        "%d deployment%s"
        % (len(entries), "" if len(entries) == 1 else "s")
    )


def cmd_find_workflow(args, endpoint, token):
    workflows = fetch_all_workflows(endpoint, token)
    needle = args.substring.lower()
    matches = [w for w in workflows if needle in (w.get("name") or "").lower()]

    if args.json:
        print(json.dumps(
            [
                {"id": w.get("id"), "name": w.get("name")}
                for w in matches
            ],
            indent=2,
        ))
        return

    if not matches:
        print("no workflows matched %r" % args.substring)
        return

    rows = [(w.get("id") or "", w.get("name") or "") for w in matches]
    print_table(rows, ("WORKFLOW ID", "NAME"))


# ---- argparse --------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="query_workflows.py",
        description="Read-only inventory of registered NGS360 workflows.",
    )
    sub = parser.add_subparsers(dest="cmd")

    lw = sub.add_parser(
        "list-workflows",
        help="List every registered workflow with versions and deployments.",
    )
    lw.add_argument("--name", help="case-insensitive substring filter on name")
    lw.add_argument(
        "--latest",
        action="store_true",
        help="show only the newest version of each workflow",
    )
    lw.add_argument("--json", action="store_true", help="emit JSON")
    lw.set_defaults(func=cmd_list_workflows)

    sw = sub.add_parser(
        "show-workflow",
        help="Show one workflow's full detail (versions, aliases, deployments).",
    )
    sw.add_argument("workflow_id")
    sw.add_argument("--json", action="store_true", help="emit JSON")
    sw.set_defaults(func=cmd_show_workflow)

    ld = sub.add_parser(
        "list-deployments",
        help="Flat list of every deployment across all workflows.",
    )
    ld.add_argument(
        "--engine",
        help='filter by engine name (e.g. "AWSHealthOmics (us-east)")',
    )
    ld.add_argument("--json", action="store_true", help="emit JSON")
    ld.set_defaults(func=cmd_list_deployments)

    fw = sub.add_parser(
        "find-workflow",
        help="Case-insensitive name lookup — prints matching id + name.",
    )
    fw.add_argument("substring")
    fw.add_argument("--json", action="store_true", help="emit JSON")
    fw.set_defaults(func=cmd_find_workflow)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd is None:
        parser.print_help()
        return
    endpoint = os.environ.get("NGS360_API_URL", DEFAULT_API_URL).rstrip("/")
    token = os.environ.get("NGS360_AUTH_TOKEN") or None
    args.func(args, endpoint, token)


if __name__ == "__main__":
    main()
