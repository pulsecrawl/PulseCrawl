"""Legacy domain imports and v1 intent construction compatibility."""

from pulsecrawl.domain.crawling.model import *  # noqa: F403


def _from_message_intent(cls, **kwargs):
    from pulsecrawl.adapters.inbound.python.intent import IntentMapper

    return IntentMapper.from_message_intent(**kwargs)


# Kept only at the legacy boundary. Canonical domain models have no wire mapper.
ExecutionIntent.from_message_intent = classmethod(_from_message_intent)
