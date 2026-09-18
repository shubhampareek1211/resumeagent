# Security and privacy

Private material belongs only in ignored local paths. Never commit credentials,
real contact/profile information, application history, reference PDFs, generated
PDFs/LaTeX or screenshots. Use reserved example domains and invented candidates
in public examples. Review staged changes even when automated checks pass.

The public-tree scanner enforces a reviewed path inventory, blocks generated/private
paths and binaries, and detects common credential/contact patterns in Git index blobs.
It does not detect all natural-language personal information. CI is a detection layer:
it cannot undo a disclosure already pushed. Run the scanner before pushing and enable
GitHub secret scanning/push protection where available. The initial public tree was
assembled separately from the private workspace rather than initializing Git over it.

If a secret is disclosed, revoke it first, then remove it from files and history.
If reporting a vulnerability, use the repository's private vulnerability-reporting
feature if enabled. Otherwise open an issue requesting a private contact channel
without including exploit data, private documents or secrets. Do not post tokens or
personal resumes in public reports.

Only reviewed TeX should be compiled. `-no-shell-escape` is not full isolation: TeX
may still read accessible local files. Run untrusted source in an isolated environment
without credentials or private documents. The scripts do not automatically execute
commands found in job PDFs, but an AI assistant has its own permissions/data-sharing
behavior; review that configuration separately.

CI runs only fictional fixtures with mocked Notion calls and no Notion secrets.
Release write permissions are limited to the publishing job. Source archives include
only committed public files, never ignored build products or environment files.

Local application data is not encrypted by this project. Use OS account protections
and appropriate backups. Notion receives application metadata only during explicit
live sync or a build without `--local-only`. Keep connection access limited to the
intended database. Sync is not distributed-transactional or bidirectional.
