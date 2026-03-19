# Security Policy

## Reporting

If you find a security issue, data leak, or credential exposure risk in this repository, please report it privately to:

- Liam O'Boyle
- `liamoboyle0@gmail.com`

Do not open a public issue for live credentials, leaked secrets, or private artifact content.

## Scope

This repository is primarily a research release. The main security concerns are:

- accidental credential exposure
- unsafe handling of private artifact bundles
- release scripts that could disclose local environment details

## Handling Secrets

- No API keys should ever be committed.
- Use `.env.example` as the setup template.
- Keep your actual `.env` file local and untracked.
- Do not paste live keys into issues, pull requests, or benchmark artifacts.
