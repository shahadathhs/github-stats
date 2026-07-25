import asyncio
from typing import Optional

import aiohttp


class Queries(object):
    """
    Query the GitHub GraphQL (v4) API using aiohttp. Only the fields the
    redesigned cards need: a user's name, their repositories' language
    breakdown, and their contribution calendar.
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

    async def query(self, generated_query: str) -> dict:
        """
        Run a GraphQL query. Raises RuntimeError on auth failures, GraphQL
        errors, or empty responses so problems surface instead of producing
        silently-empty output.
        """
        headers = {"Authorization": f"Bearer {self.access_token}"}
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

    @staticmethod
    def repos_with_languages(cursor: Optional[str] = None) -> str:
        """
        One page of the viewer's own (non-fork) repositories with their
        language breakdown by file size.
        """
        return f"""{{
  viewer {{
    name
    login
    repositories(
        first: 100,
        orderBy: {{ field: UPDATED_AT, direction: DESC }},
        isFork: false,
        after: {"null" if cursor is None else '"' + cursor + '"'}
    ) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        nameWithOwner
        languages(first: 10, orderBy: {{ field: SIZE, direction: DESC }}) {{
          edges {{
            size
            node {{ name color }}
          }}
        }}
      }}
    }}
  }}
}}
"""

    @staticmethod
    def contribution_calendar(date_from: str, date_to: str) -> str:
        """
        Daily contribution counts between two ISO-8601 datetimes, plus the
        month boundaries for labeling the heatmap.
        """
        return f"""
query {{
  viewer {{
    name
    contributionsCollection(from: "{date_from}", to: "{date_to}") {{
      contributionCalendar {{
        totalContributions
        months {{ firstDay name totalWeeks }}
        weeks {{
          contributionDays {{
            date
            weekday
            contributionCount
          }}
        }}
      }}
    }}
  }}
}}
"""
