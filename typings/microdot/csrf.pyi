from _typeshed import Incomplete
from microdot import abort as abort

class CSRF:
    SAFE_METHODS: Incomplete
    cors: Incomplete
    protect_all: Incomplete
    allow_subdomains: Incomplete
    exempt_routes: Incomplete
    protected_routes: Incomplete
    def __init__(self, app=None, cors=None, protect_all: bool = True, allow_subdomains: bool = False) -> None: ...
    def initialize(self, app, cors=None) -> None: ...
    def exempt(self, f): ...
    def protect(self, f): ...
