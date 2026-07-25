import asyncio
from typing import Dict, List, Optional

import aiohttp
import requests


class Queries(object):
    """
    Class with functions to query the GitHub GraphQL (v4) API and the REST (v3)
    API. Also includes functions to dynamically generate GraphQL queries.
    """

    def __init__(
        self,
        username: str,
        access_token: str,
        session: aiohttp.ClientSession,
        max_connections: int = 10,
    ):
        self.username = username
        self.access_token = access_token
        self.session = session
        self.semaphore = asyncio.Semaphore(max_connections)

    async def query(self, generated_query: str) -> Dict:
        """
        Make a request to the GraphQL API using the authentication token from
        the environment
        :param generated_query: string query to be sent to the API
        :return: decoded GraphQL JSON output
        """
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }
        result: Optional[Dict] = None
        try:
            async with self.semaphore:
                r_async = await self.session.post(
                    "https://api.github.com/graphql",
                    headers=headers,
                    json={"query": generated_query},
                )
            if r_async.status in (401, 403):
                raise RuntimeError(
                    f"GitHub GraphQL API returned HTTP {r_async.status} "
                    "(bad credentials or insufficient token scope)."
                )
            result = await r_async.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            print(f"aiohttp failed for GraphQL query: {err}")
            # Fall back on non-async requests
            async with self.semaphore:
                r_requests = requests.post(
                    "https://api.github.com/graphql",
                    headers=headers,
                    json={"query": generated_query},
                )
                if r_requests.status_code in (401, 403):
                    raise RuntimeError(
                        f"GitHub GraphQL API returned HTTP "
                        f"{r_requests.status_code} (bad credentials or "
                        "insufficient token scope)."
                    )
                result = r_requests.json()

        if not result:
            raise RuntimeError(
                "GitHub GraphQL API returned an empty response."
            )

        errors = result.get("errors")
        if errors:
            messages = "; ".join(str(e.get("message", e)) for e in errors)
            raise RuntimeError(
                f"GitHub GraphQL API returned errors: {messages}"
            )

        if result.get("data") is None:
            raise RuntimeError(
                "GitHub GraphQL API returned no data. Response: "
                f"{str(result)[:500]}"
            )

        return result

    async def query_rest(self, path: str, params: Optional[Dict] = None) -> Dict:
        """
        Make a request to the REST API
        :param path: API path to query
        :param params: Query parameters to be passed to the API
        :return: deserialized REST JSON output
        """
        if params is None:
            params = dict()
        if path.startswith("/"):
            path = path[1:]
        headers = {
            "Authorization": f"token {self.access_token}",
        }

        for _ in range(60):
            try:
                async with self.semaphore:
                    r_async = await self.session.get(
                        f"https://api.github.com/{path}",
                        headers=headers,
                        params=tuple(params.items()),
                    )
                if r_async.status in (401, 403):
                    raise RuntimeError(
                        f"GitHub REST API returned HTTP {r_async.status} for "
                        f"{path} (bad credentials or insufficient scope)."
                    )
                if r_async.status == 202:
                    print(f"A path returned 202. Retrying...")
                    await asyncio.sleep(2)
                    continue

                result = await r_async.json()
                if result is not None:
                    return result
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                print(f"aiohttp failed for REST query ({path}): {err}")
                # Fall back on non-async requests
                async with self.semaphore:
                    r_requests = requests.get(
                        f"https://api.github.com/{path}",
                        headers=headers,
                        params=tuple(params.items()),
                    )
                    if r_requests.status_code in (401, 403):
                        raise RuntimeError(
                            f"GitHub REST API returned HTTP "
                            f"{r_requests.status_code} for {path} (bad "
                            "credentials or insufficient scope)."
                        )
                    if r_requests.status_code == 202:
                        print(f"A path returned 202. Retrying...")
                        await asyncio.sleep(2)
                        continue
                    elif r_requests.status_code == 200:
                        return r_requests.json()
                    else:
                        raise RuntimeError(
                            f"GitHub REST API returned HTTP "
                            f"{r_requests.status_code} for {path}."
                        )
        raise RuntimeError(
            f"GitHub REST API returned HTTP 202 too many times for {path}; "
            "statistics are not ready yet. Try again later."
        )

    @staticmethod
    def repos_overview(
        contrib_cursor: Optional[str] = None,
        owned_cursor: Optional[str] = None,
        include_contributed: bool = True,
    ) -> str:
        """
        :return: GraphQL query with overview of user repositories
        """
        contributed = ""
        if include_contributed:
            contributed = f"""    repositoriesContributedTo(
        first: 100,
        includeUserRepositories: false,
        orderBy: {{
            field: UPDATED_AT,
            direction: DESC
        }},
        contributionTypes: [
            COMMIT,
            PULL_REQUEST,
            REPOSITORY,
            PULL_REQUEST_REVIEW
        ]
        after: {"null" if contrib_cursor is None else '"' + contrib_cursor + '"'}
    ) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      nodes {{
        nameWithOwner
        stargazers {{
          totalCount
        }}
        forkCount
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{
            size
            node {{
              name
              color
            }}
          }}
        }}
      }}
    }}
"""
        return f"""{{
  viewer {{
    login,
    name,
    repositories(
        first: 100,
        orderBy: {{
            field: UPDATED_AT,
            direction: DESC
        }},
        isFork: false,
        after: {"null" if owned_cursor is None else '"'+ owned_cursor +'"'}
    ) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      nodes {{
        nameWithOwner
        stargazers {{
          totalCount
        }}
        forkCount
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{
            size
            node {{
              name
              color
            }}
          }}
        }}
      }}
    }}
{contributed}
  }}
}}
"""

    @staticmethod
    def contrib_years() -> str:
        """
        :return: GraphQL query to get all years the user has been a contributor
        """
        return """
query {
  viewer {
    contributionsCollection {
      contributionYears
    }
  }
}
"""

    @staticmethod
    def contribs_by_year(year: str) -> str:
        """
        :param year: year to query for
        :return: portion of a GraphQL query with desired info for a given year
        """
        return f"""
    year{year}: contributionsCollection(
        from: "{year}-01-01T00:00:00Z",
        to: "{int(year) + 1}-01-01T00:00:00Z"
    ) {{
      contributionCalendar {{
        totalContributions
      }}
    }}
"""

    @classmethod
    def all_contribs(cls, years: List[str]) -> str:
        """
        :param years: list of years to get contributions for
        :return: query to retrieve contribution information for all user years
        """
        by_years = "\n".join(map(cls.contribs_by_year, years))
        return f"""
query {{
  viewer {{
    {by_years}
  }}
}}
"""
