# Security

Physiscore is a desktop analysis program. It reads local data files, writes results next
to them, and makes network requests only for

- the update check: one HTTPS request a day to the GitHub releases API of this repository
  (disable with Tools → Updates → Off or `PHYSISCORE_NO_UPDATE=1`); a downloaded update is
  installed only if its SHA-256 matches the release's `SHA256SUMS.txt`;
- the optional interpretation panels, which send result tables (not raw data files) to the
  Gemini API when an API key is configured.

The API key is stored in plain text in `physisfera_config.json` on your computer; do not
commit that file (it is in `.gitignore`).

To report a vulnerability, use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability) or e-mail the maintainer listed in `CITATION.cff`.
Please do not open a public issue for it.
