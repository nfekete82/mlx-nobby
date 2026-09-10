# Security Policy

MLX Nobby is designed primarily for local use on macOS.

## Local-only services

Native services bind to loopback interfaces by default and are intended to be accessed only from the local machine.

Do not expose the MLX, agent, embedding, speech, image, router or web services directly to the public internet without adding appropriate authentication, TLS, network isolation and access controls.

## Secrets

Do not commit:

- API keys
- access tokens
- passwords
- SSH private keys
- private environment files
- credentials
- personal configuration files

Use local environment variables or ignored configuration files instead.

## Local files

Some features can access local files and coding workspaces. Review configured paths carefully and use the built-in workspace restrictions.

## Reporting a vulnerability

Please report security issues privately to the repository maintainer rather than opening a public issue containing exploit details or sensitive information.
