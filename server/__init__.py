"""The friends server: presence, play totals and leaderboards.

Standard library only, so it runs anywhere Python does:

    python -m server --host 0.0.0.0 --port 8765

It stores what launchers upload and shows each user their own data and
their accepted friends' data, and nothing else. There are no messages and
no way to reach a user who has not accepted a request.
"""
