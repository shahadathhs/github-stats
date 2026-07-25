import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import requests


def _decode(raw: bytes) -> Optional[Any]:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None


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
        Make a request to the REST API. Returns an empty dict when GitHub has
        no data ready for the resource (e.g. HTTP 204 or a persistent 202 from
        the statistics endpoints), so one missing stat never aborts the run.
        :param path: API path to query
        :param params: Query parameters to be passed to the API
        :return: deserialized REST JSON output, or {} if no data is available
        """
        if params is None:
            params = dict()
        if path.startswith("/"):
            path = path[1:]
        headers = {
            "Authorization": f"token {self.access_token}",
            "Accept": "application/json",
        }
        url = f"https://api.github.com/{path}"

        max_retries = 5
        for attempt in range(max_retries):
            status, result = await self._rest_get(url, headers, params)
            if status in (401, 403):
                raise RuntimeError(
                    f"GitHub REST API returned HTTP {status} for {path} "
                    "(bad credentials or insufficient scope)."
                )
            if status == 202:
                # Statistics are still being computed in the background.
                backoff = 2 ** attempt
                print(f"Stats not ready (202) for {path}; retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                continue
            if status == 204 or result is None:
                return {}
            return result

        print(
            f"Stats for {path} were not ready after {max_retries} retries; "
            "counting as zero."
        )
        return {}

    async def _rest_get(
        self, url: str, headers: Dict[str, str], params: Dict
    ) -> Tuple[int, Optional[Any]]:
        """
        Perform an authenticated GET and return (status, parsed_json_or_None).
        A 204 or a non-JSON body yields None so the caller can treat it as
        "no data". Falls back to synchronous requests on a transport error.
        """
        try:
            async with self.semaphore:
                r_async = await self.session.get(
                    url, headers=headers, params=tuple(params.items())
                )
                return r_async.status, _decode(await r_async.read())
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            print(f"aiohttp failed for REST query ({url}): {err}")
        async with self.semaphore:
            r_requests = requests.get(
                url, headers=headers, params=tuple(params.items())
            )
            return r_requests.status_code, _decode(r_requests.content)

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
