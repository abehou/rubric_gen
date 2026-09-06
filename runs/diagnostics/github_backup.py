"""Private backup utility: scan locally; upload only explicitly supplied assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

import certifi

REPO = 'abehou/rubric_gen'
TAG = 'aydan-red-team-backup-20260906'
CONTEXT = ssl.create_default_context(cafile=certifi.where())
PATTERNS = {
    'provider_key': re.compile(rb'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}'),
    'google_key': re.compile(rb'\bAIza[A-Za-z0-9_-]{35}'),
    'github_token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}


def credential():
    proc = subprocess.run(['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n', text=True,
        capture_output=True, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}, check=True)
    fields = dict(line.split('=', 1) for line in proc.stdout.splitlines() if '=' in line)
    if not fields.get('password'):
        raise RuntimeError('No existing GitHub credential')
    return fields['password']


def api(path, method='GET', payload=None, asset=None):
    url = path if path.startswith('https://') else f'https://api.github.com/repos/{REPO}/{path}'
    if urllib.parse.urlparse(url).hostname not in ('api.github.com', 'uploads.github.com'):
        raise ValueError('Unexpected API host')
    headers = {'Authorization': 'Bearer ' + credential(),
               'Accept': 'application/vnd.github+json', 'User-Agent': 'rubric-gen-backup'}
    if asset:
        headers.update({'Content-Type': 'application/gzip', 'Content-Length': str(asset.stat().st_size)})
        with asset.open('rb') as body:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, context=CONTEXT, timeout=600) as response:
                return json.load(response)
    body = None if payload is None else json.dumps(payload).encode()
    if body is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, context=CONTEXT, timeout=60) as response:
        return json.load(response)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def scan(paths):
    known = {k: v.encode() for k, v in os.environ.items()
             if any(x in k.upper() for x in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN')) and len(v) > 15}
    findings = []
    files = 0
    def inspect(stream, name):
        nonlocal files
        files += 1
        tail = b''
        found = set()
        while chunk := stream.read(1024 * 1024):
            block = tail + chunk
            found.update(kind for kind, pattern in PATTERNS.items() if pattern.search(block))
            found.update('configured_secret:' + key for key, value in known.items() if value in block)
            tail = block[-8192:]
        if found:
            findings.append({'path': name, 'types': sorted(found)})
    def visit(p):
        if p.is_symlink():
            raise ValueError(f'Symlink requires explicit review: {p}')
        if p.is_dir():
            for child in sorted(p.iterdir()):
                visit(child)
        elif p.is_file():
            if p.name.startswith('.env') or p.name in ('auth.json', 'credentials.json'):
                raise ValueError(f'Secret-bearing filename: {p}')
            if p.name.endswith(('.tar.gz', '.tgz')):
                with tarfile.open(p) as archive:
                    for member in archive:
                        if member.isfile():
                            with archive.extractfile(member) as stream:
                                inspect(stream, str(p) + '::' + member.name)
            else:
                with p.open('rb') as stream:
                    inspect(stream, str(p))
    for path in paths:
        visit(Path(path))
    print(json.dumps({'scanned_files': files, 'findings': findings}, indent=2), flush=True)
    return bool(findings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('scan', 'create-release', 'upload', 'verify'))
    parser.add_argument('paths', nargs='*')
    args = parser.parse_args()
    if args.operation == 'scan':
        return scan(args.paths)
    if args.operation == 'create-release':
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        try:
            release = api('releases/tags/' + TAG)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            release = api('releases', 'POST', {
                'tag_name': TAG, 'target_commitish': sha,
                'name': 'Aydan red-team Results20 backup (2026-09-06)',
                'body': 'Complete experiment backup for branch aydan-red-team. See GITHUB_BACKUP.md on that branch for scope, SHA-256 checksums and restore instructions. Credentials and local environments are excluded.',
                'draft': False, 'prerelease': True, 'make_latest': 'false'})
        print(json.dumps({k: release[k] for k in ('id', 'html_url', 'tag_name')}, indent=2))
        return 0
    release = api('releases/tags/' + TAG)
    for name in args.paths:
        p = Path(name)
        expected = digest(p)
        assets = api(f'releases/{release["id"]}/assets?per_page=100')
        found = [x for x in assets if x['name'] == p.name]
        if not found and args.operation == 'upload':
            print(json.dumps({'uploading': p.name, 'bytes': p.stat().st_size}), flush=True)
            url = release['upload_url'].split('{')[0] + '?name=' + urllib.parse.quote(p.name)
            found = [api(url, 'POST', asset=p)]
        if len(found) != 1:
            raise RuntimeError(f'Missing or ambiguous remote asset: {p.name}')
        a = found[0]
        assert a['size'] == p.stat().st_size and a['state'] == 'uploaded', p.name
        assert a.get('digest') == 'sha256:' + expected, f'Remote digest mismatch/unavailable: {p.name}'
        print(json.dumps({'verified_asset': p.name, 'bytes': a['size'], 'sha256': expected,
                          'url': a['browser_download_url']}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
