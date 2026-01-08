"""Constants for Conductor."""

DEFAULT_EVENT_BUS_MAXSIZE = 1000

# Event bus topics
# I need to add more, but this is good for testing purposes
TOPIC_HA_EVENT_STATE_CHANGED = "ha.event.state_changed"
TOPIC_HA_EVENT_CALL_SERVICE = "ha.event.call_service"
TOPIC_HA_EVENT_RESULT = "ha.event.result"
TOPIC_HA_EVENT_AUTH_OK = "ha.event.auth_ok"
TOPIC_HA_EVENT_AUTH_INVALID = "ha.event.auth_invalid"
