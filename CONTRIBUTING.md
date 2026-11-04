# Contributing

Issues and pull requests are welcome.

- Run `make check` before pushing: ruff, `mypy --strict` and pytest must be
  clean, the same gate CI runs. It needs no network.
- `make live` runs `tests/live/`, the contract with the live IdroGEO service
  (about a minute). CI runs it every Monday and opens an issue labelled
  `live-contract` when IdroGEO changes; a fix for one starts there.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
- Contributions are accepted under the project's license, Apache-2.0
  (section 5 of the license: inbound = outbound). No separate CLA.
