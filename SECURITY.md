# Security policy

## Supported versions

The latest tagged release receives security fixes.

## Reporting a vulnerability

Please do not include private media, credentials, or sensitive absolute paths in a public issue.
Use GitHub's private vulnerability reporting feature for the repository when available. Include a
minimal synthetic reproduction, affected version, and expected safety boundary.

Important security boundaries include path traversal, symbolic links, unsafe report targets,
command execution, HTML injection, network access, and accidental disclosure in generated reports.

RenderVet never needs an API key. A prompt, issue, fork, or package asking for one is not part of
the official project.
