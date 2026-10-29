# Security policy

Task Runner operates on a real Windows desktop with the permissions of the signed-in account. Saved workflows can open programs, type commands, download files, interact with web pages, modify files, and request shutdown. Treat imported workflows like executable scripts.

## Supported version

The current maintained source is the 1.2.1 hardening line. Earlier archived source packages are not promised security updates. Published releases, when available, will be identified by GitHub release tags.

## Responsible vulnerability reporting

**Do not file public issues for potential vulnerabilities, credentials, private task exports, browser session tokens, or sensitive execution logs.** Once the repository is created, the maintainer should enable **Settings → Security → Private vulnerability reporting**. Send the details using GitHub's private vulnerability reporting feature; this policy deliberately does not invent a support address.

Reports should include affected version, impact, precise reproduction steps, and a minimal sanitized demonstration. Do not perform destructive tests against systems you do not own or control. Maintainers will evaluate severity and coordinate disclosure through a GitHub Security Advisory.

## Trust boundaries

- Imported task JSON is **disabled by default**, but enabling or manually executing it can trigger desktop/OS actions with the current user's permissions. Review every action, including launch, delete, overwrite, clipboard, browser navigation, and shutdown.
- Do not run untrusted tasks as administrator. Use a standard account and test unfamiliar jobs on nonproduction data.
- Task exports may embed local paths, URLs, credentials typed by automation, command arguments, and copied content. Do not publish them without inspection.
- The SQLite database and execution histories, runtime settings, failure screenshots, and clipboard output stay in the user's local data directory. They are excluded from source control, not encrypted by Task Runner.
- Native desktop automation requires a logged-in, unlocked session. PyAutoGUI and Windows UI Automation cannot safely interact with a secure desktop or UAC prompt.
- The shared Python dependency installer checks package compatibility and uses user-site installation; package downloads are subject to normal Python packaging supply-chain risks. Revisit dependency updates before public releases.
- No remote telemetry, account service, or network control endpoint is implemented by Task Runner. Network actions inside user-created workflows still connect to their specified destinations.

## Repository protections

Use the optional branch ruleset in `.github/rulesets/main-branch-protection.json` only **after** your first commit and desired collaborator settings are in place; it is a proposal, not activated by committing it. Turn on secret scanning, push protection where offered, Dependabot alerts, and private vulnerability reporting in GitHub Settings. `SECURITY.md` by itself does not turn on these features.
