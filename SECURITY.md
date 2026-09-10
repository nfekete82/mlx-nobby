# Security Policy

MLX nobby is designed primarily for local use on macOS.

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

Generated chats, notes, indexes, images, logs, configuration, and model weights
are local runtime data. Keep them outside version control and inspect staged
files before every public contribution.

## Authentication and network access

The project does not provide authentication for internet-facing deployment.
Keep all supplied listeners bound to localhost unless you have added an
appropriate authentication, TLS, and network-isolation layer.

Model downloads can contact Hugging Face, research actions can contact the
configured SearXNG service and selected web pages, and the current web pages
load several static assets from public CDNs. Review these connections before
using MLX nobby with sensitive material or in an offline environment.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting when it is available for the
repository. Otherwise contact the maintainer privately. Do not open a public
issue containing exploit details, credentials, or personal data.
