# Security

Physiscore is a desktop analysis program. It reads local data files, writes results next
to them, and makes network requests only for

- the update check: one HTTPS request a day to the GitHub releases API of this repository
  (disable with Tools → Updates → Off or `PHYSISCORE_NO_UPDATE=1`); a downloaded update is
  installed only if its SHA-256 matches the release's `SHA256SUMS.txt`.

Since 3.4 the interpretation panels are rule-based and offline; no result or data leaves
the computer. Versions up to 3.3 could send result tables to the Gemini API and stored the
key in plain text in `physisfera_config.json`; 3.4 removes that key when the settings are
next saved.

To report a vulnerability, use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability) or e-mail the maintainer listed in `CITATION.cff`.
Please do not open a public issue for it.
