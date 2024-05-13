#!/usr/bin/env python3
from pathlib import Path
import subprocess
import xml.etree.ElementTree
from defusedxml import ElementTree as DET
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('repo', type=Path, default='.', nargs='?')
parser.add_argument('--branch', '-b', default='origin/master')
parser.add_argument('--apply', dest='dry', action='store_false')
parser.add_argument('--manifest', '-m', type=Path)
parser.add_argument('--verbose', '-v', action='store_true')
args = parser.parse_args()

REPO = args.repo.resolve(strict=True)
MASTER_BRANCH = args.branch
# using --reverse wil only show commits up to removing from archive
# this is not desired as removes could happen by mistake and tracking
# file after remove in commit X and added later in Y is impossible
GIT_CMD = ['git', 'log', MASTER_BRANCH, '--full-history', '--format=format:%H %(describe)', '--follow', '--']
VERSION_ATTRIB_KEY = '{http://schemas.android.com/apk/res/android}versionCode'
MARK_EXPECTED = True
DRY_RUN = args.dry
stderr = subprocess.STDOUT if args.verbose else subprocess.DEVNULL

def call_cmd(*args):
    return subprocess.check_output(args,
        stdin=subprocess.DEVNULL,
        stderr=stderr,
        universal_newlines=True,
        timeout=10,
        cwd=REPO,
    )

if DRY_RUN:
    print(
        'Running in dry/test mode. No changes will be made\n'
        'For permanent changes use `--apply` switch.\n'
    )

print(f'Looking for AndroidManifest.xml in {REPO}')

# 1) Find AndroidManifest.xml

manifest = args.manifest
if manifest:
    manifest = manifest.resolve(strict=True)
    manifest = manifest.relative_to(REPO)
    print(f'Using user selected manifest file: {manifest}')
else:
    has_multiple = False
    for m in REPO.glob("**/AndroidManifest.xml"):
        # make it relative
        m = m.relative_to(REPO)
        if not manifest:
            print(f'Selected manifest file: {m}')
            manifest = m
        else:
            has_multiple = True
            print(f'Ignore additional manifest: {m}')

    if has_multiple:
        print('\nMultiple manifests has been found. If selected one is not correct use `--manifest` option\n')

if not manifest:
    print(f'No AndroidManifest in repo: {REPO}')
    exit(0)

# dig in manifest history
#git log --follow --remotes --all --reflog -- AndroidManifest.xml
proc = call_cmd(*GIT_CMD, str(manifest))

last_known_version = ''

def find_commit_with_tag(tag):
    return call_cmd('git', 'rev-list', '--max-count=1', tag, '--').strip()

def branches_with_commit(commit):
    return call_cmd('git', 'branch', '--all', '--contains', commit).splitlines()

for rev_history in proc.splitlines():
    fields = rev_history.split(maxsplit=1)
    commit = fields[0]
    tag = '' if len(fields) == 1 else fields[1]

    asdf = call_cmd('git', 'diff', '--name-status')

    try:
        hist = call_cmd('git', 'show', f'{commit}:{manifest}')
    except subprocess.CalledProcessError:
        continue


    try:
        parsed_xml = DET.fromstring(hist)
    except xml.etree.ElementTree.ParseError:
        print(f'malformed AndroidManifest.xml at {commit}')
        continue
    except:
        print(hist)
        raise

    hist_version = parsed_xml.attrib.get(VERSION_ATTRIB_KEY)
    if not hist_version:
        continue

    if hist_version == last_known_version:
        continue

    last_known_version = hist_version
    expected_tag = f'v{hist_version}'

    base_tag = tag.split('-', maxsplit=1)[0]
    if base_tag == expected_tag:
        continue

    try:
        commit_with_tag = find_commit_with_tag(expected_tag)
    except subprocess.CalledProcessError:
        commit_with_tag = ''
        pass

    if commit_with_tag:
        print(f'tag "{expected_tag}" already on {commit_with_tag}')
        if not branches_with_commit(commit_with_tag):
            print(f'It seems {commit_with_tag} is not on any branch! Fix it ASAP')
        continue
    else:
        print(f'there should be tag "{expected_tag}", but got "{tag}" on this commit: {commit}')

    if DRY_RUN:
        continue

    try:
        tag_proc = call_cmd('git', 'tag', '--message', f'Version {hist_version}', expected_tag, commit)
        tag_failed = False
    except subprocess.CalledProcessError:
        tag_failed = True

    if MARK_EXPECTED and tag_failed:
        # create local lightweight tags to mark sus commits
        tag_proc = call_cmd('git', 'tag', 'retrostamp/expected-' + expected_tag, commit)
