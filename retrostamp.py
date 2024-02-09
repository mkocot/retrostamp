#!/usr/bin/env python3
from pathlib import Path
import subprocess
from defusedxml import ElementTree as DET
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('repo', type=Path, default='.', nargs='?')
parser.add_argument('--branch', '-b', default='origin/master')
parser.add_argument('--apply', dest='dry', action='store_false')
parser.add_argument('--manifest', type=Path)
args = parser.parse_args()

REPO = args.repo.resolve(strict=True) # Path('/tmp/tv')
MASTER_BRANCH = args.branch # 'origin/master'
GIT_CMD = ['git', 'log', MASTER_BRANCH, '--reverse', '--format=format:%H %(describe)', '--follow', '--']
VERSION_ATTRIB_KEY = '{http://schemas.android.com/apk/res/android}versionCode'
MARK_EXPECTED = True
DRY_RUN = args.dry

def call_cmd(*args):
    return subprocess.run(args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
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
    has_multiple = True
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
proc.check_returncode()

last_known_version = ''

for rev_history in proc.stdout.splitlines():
    fields = rev_history.split(maxsplit=1)
    commit = fields[0]
    tag = '' if len(fields) == 1 else fields[1]

    hist = call_cmd('git', 'show', f'{commit}:{manifest}')
    if hist.check_returncode():
        exit(0)

    parsed_xml = DET.fromstring(hist.stdout)

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

    print(f'there should be tag "{expected_tag}", but got "{tag}" on this commit: {commit}')

    if DRY_RUN:
        continue

    tag_proc = call_cmd('git', 'tag', '--message', f'Version {hist_version}', expected_tag, commit)
    if MARK_EXPECTED and tag_proc.returncode != 0:
        # create local lightweight tags to mark sus commits
        tag_proc = call_cmd('git', 'tag', 'retrostamp:expected-' + expected_tag, commit)