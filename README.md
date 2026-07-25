# GitHub Stats

Generates two SVG images of your GitHub statistics — an overview (stars, forks,
contributions, lines changed, repos) and a language breakdown — and refreshes
them daily via GitHub Actions. The images are committed to
[`generated/`](generated).

## Setup

1. Create a personal access token with the `read:user` and `repo` scopes.
2. Add it as a repository secret named `ACCESS_TOKEN`.

The workflow installs dependencies with [uv](https://docs.astral.sh/uv/) (no
pip) and regenerates the images on push, daily, and on manual dispatch.

Optional secrets: `EXCLUDED` (repos to skip), `EXCLUDED_LANGS` (languages to
skip), `EXCLUDE_FORKED_REPOS`.

## Add to your profile README

```md
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/overview.svg#gh-dark-mode-only)
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/overview.svg#gh-light-mode-only)
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/languages.svg#gh-dark-mode-only)
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/languages.svg#gh-light-mode-only)
```

## Run locally

```sh
ACCESS_TOKEN=ghp_xxx GITHUB_ACTOR=your-username \
  uv run --with aiohttp --with requests python -m github_stats
```
