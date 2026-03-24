from typing import Any, Dict, List, TypedDict


class Identity(TypedDict, total=False):
    short_name: str
    role: str
    backstory: str
    goals: List[str]


class Behavior(TypedDict, total=False):
    default_style: str
    register: List[str]
    temperature: float
    constraints: List[str]


class Safety(TypedDict, total=False):
    allowed_topics: List[str]
    disallowed_topics: List[str]
    escalation_policy: str


class Personality(TypedDict, total=False):
    schema_version: str
    id: str
    name: str
    kind: str
    tags: List[str]
    identity: Identity
    behavior: Behavior
    safety: Safety
    extensions: Dict[str, Any]


JsonDict = Dict[str, Any]
