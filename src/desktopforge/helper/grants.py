"""One-time, expiring approval grants bound to the caller and the reviewed plan."""
from dataclasses import dataclass
import re
import secrets
import time

TOKEN = re.compile(r'[0-9a-f]{64}')
HASH = re.compile(r'[0-9a-f]{64}')


class GrantRejected(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Caller:
    sender: str
    uid: int


@dataclass(frozen=True)
class Grant:
    token: str
    caller: Caller
    recipe_id: str
    revision: int
    plan_hash: str
    fingerprint: str
    expires: float


class GrantStore:
    def __init__(self, ttl=120.0, limit=16, per_uid=4, clock=time.monotonic,
                 token_factory=lambda: secrets.token_hex(32)):
        self.ttl, self.limit, self.per_uid = ttl, limit, per_uid
        self.clock, self.token_factory = clock, token_factory
        self.grants = {}

    def _purge(self):
        now = self.clock()
        for token in [t for t, g in self.grants.items() if g.expires <= now]:
            del self.grants[token]

    def issue(self, caller, recipe_id, revision, plan_hash, fingerprint):
        if not HASH.fullmatch(plan_hash) or not HASH.fullmatch(fingerprint):
            raise GrantRejected('malformed plan or evidence hash')
        self._purge()
        if len(self.grants) >= self.limit:
            raise GrantRejected('too many outstanding previews')
        if sum(g.caller.uid == caller.uid for g in self.grants.values()) >= self.per_uid:
            raise GrantRejected('too many outstanding previews for this user')
        token = self.token_factory()
        if not TOKEN.fullmatch(token) or token in self.grants:
            raise GrantRejected('token generation failed')
        grant = Grant(token, caller, recipe_id, revision, plan_hash, fingerprint,
                      self.clock() + self.ttl)
        self.grants[token] = grant
        return grant

    def redeem(self, token, caller, plan_hash):
        """Consume the grant before any check, so it can never be presented twice."""
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise GrantRejected('malformed token')
        grant = self.grants.pop(token, None)
        if grant is None:
            raise GrantRejected('unknown or already used token')
        if self.clock() >= grant.expires:
            raise GrantRejected('token expired')
        if grant.caller != caller:
            raise GrantRejected('token belongs to a different caller')
        if not isinstance(plan_hash, str) or not secrets.compare_digest(plan_hash, grant.plan_hash):
            raise GrantRejected('approved plan does not match the previewed plan')
        return grant

    def drop_sender(self, sender):
        """A disconnected client's previews die with its connection."""
        for token in [t for t, g in self.grants.items() if g.caller.sender == sender]:
            del self.grants[token]

    def __len__(self):
        return len(self.grants)
