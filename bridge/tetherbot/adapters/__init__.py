# SPDX-License-Identifier: GPL-2.0-or-later
"""Transport adapters. All of them stay off until config enables them."""

from tetherbot.adapters.fake import FakeAdapter
from tetherbot.adapters.github_poller import GitHubPoller
from tetherbot.adapters.official import OfficialAdapter
from tetherbot.adapters.webhook_sender import WebhookSender

__all__ = [
    "FakeAdapter",
    "GitHubPoller",
    "OfficialAdapter",
    "WebhookSender",
]
