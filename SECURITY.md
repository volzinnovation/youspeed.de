# Security policy

## Reporting a vulnerability

Please report security or privacy issues privately to [studios@moonshots.gmbh](mailto:studios@moonshots.gmbh). Include the affected platform or component, reproduction steps, expected impact, and any suggested mitigation. Do not open a public issue for an unpatched vulnerability or attach credentials, private location traces, or other personal data.

We will acknowledge a report, investigate it, and coordinate disclosure and remediation with the reporter. Please allow reasonable time for a fix before public disclosure.

## Supported versions

Security fixes are applied to the current release line. Users should update to the newest version available through the official app stores.

## Repository hygiene

Contributions must not contain credentials, signing material, device identifiers, private release configuration, or non-consensual location and driving traces. Use synthetic fixtures for public tests and keep local diagnostics in ignored paths.

Before committing, run `python3 scripts/check_repository_secrets.py` to check tracked files without printing matched credential values. Run `python3 scripts/check_repository_secrets.py --history` before pushing to also inspect reachable Git history. The repository hygiene workflow runs the tracked-file check on pull requests and pushes.

Keep local credentials under ignored `secret/`, `secrets/`, or `credentials/` directories, or use environment variables and the platform credential store. Ignore rules prevent accidental additions; they do not remove files already tracked or erase earlier commits. If a real credential is found, revoke or rotate it before coordinating any required history cleanup. Pattern-based checks supplement review and cannot prove that every possible secret format is absent.
