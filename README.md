# GitHub Stats

Generate visualizations of your GitHub user and repository statistics as SVG
images, refreshed automatically by GitHub Actions. Data can include private
repositories and repositories you have contributed to but do not own, because
the analysis runs against your own access token.

Two images are produced in [`generated/`](generated):

- `overview.svg` — stars, forks, all-time contributions, lines changed, views,
  and repository count.
- `languages.svg` — proportional breakdown of languages used.

Both images switch between GitHub's light and dark themes automatically.

## Project structure

```
github_stats/        # Python package (run with: python -m github_stats)
  __init__.py        #   package exports
  __main__.py        #   entry point
  cli.py             #   SVG generation
  stats.py           #   Stats: aggregates user statistics
  queries.py         #   Queries: GitHub GraphQL + REST helpers
templates/           # SVG templates (input)
generated/           # generated SVG images (output)
requirements.txt     # aiohttp, requests
.github/workflows/   # daily Action that regenerates and commits the images
```

There is no package to install — the code runs straight from the repo.

## Setup

1. Create a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
   with the `read:user` and `repo` scopes.
2. Add it as a repository secret named **`ACCESS_TOKEN`** under
   Settings → Secrets and variables → Actions.

### Optional secrets

- `EXCLUDED` — comma-separated repos to skip (e.g. `user/repo1,user/repo2`).
- `EXCLUDED_LANGS` — comma-separated languages to skip (e.g. `html,tex`).
- `EXCLUDE_FORKED_REPOS` — set to `true` to count owned repos only (enabled by
  default in the workflow).

## How it runs

The workflow in [`.github/workflows/main.yml`](.github/workflows/main.yml) runs
on every push to `main`, on a daily schedule, and on manual dispatch. It runs
`python -m github_stats`, then commits the updated images back to the repo.

Trigger it manually from the **Actions** tab → "Generate Stats Images" →
"Run workflow".

## Run locally

```sh
pip install -r requirements.txt
ACCESS_TOKEN=ghp_xxx GITHUB_ACTOR=your-username python -m github_stats
```

## Add to your profile README

```md
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/overview.svg#gh-dark-mode-only)
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/overview.svg#gh-light-mode-only)
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/languages.svg#gh-dark-mode-only)
![](https://raw.githubusercontent.com/shahadathhs/github-stats/main/generated/languages.svg#gh-light-mode-only)
```

## Troubleshooting

If images show all-zero stats or the workflow stops committing, it is almost
always a GitHub API issue rather than the token. The generator **fails loudly**
on API errors instead of silently writing zeros, so open the failed run in the
Actions tab and read the "Generate images" step — the message states which call
failed (HTTP 401 = bad/expired token; a GraphQL/REST error = server-side issue
worth retrying later). See
[community discussion #192970](https://github.com/orgs/community/discussions/192970)
for a known regression in the stats API.

## License

[GNU GPLv3](LICENSE). Forked from [jstrieb/github-stats](https://github.com/jstrieb/github-stats).
