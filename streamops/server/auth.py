"""Access policy boundary for the node API.

The issue-11 MVP intentionally trusts the local network and performs no request
authentication. Keeping the dependency here makes a later policy change local.
"""


async def require_access() -> None:
    """Allow requests under the MVP trusted-LAN policy."""
