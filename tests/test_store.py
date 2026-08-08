from mdmem.store import resolve_actor


def test_configured_client_is_used_when_caller_names_nothing(monkeypatch):
    monkeypatch.setenv("MDMEM_ACTOR", "cursor")
    assert resolve_actor(None) == "cursor"


def test_caller_role_is_combined_with_the_configured_client(monkeypatch):
    # Letting the role win outright would erase which client ran it -- the very
    # thing the log could not answer before.
    monkeypatch.setenv("MDMEM_ACTOR", "cursor")
    assert resolve_actor("memory-manager") == "cursor/memory-manager"


def test_role_matching_the_client_is_not_doubled(monkeypatch):
    monkeypatch.setenv("MDMEM_ACTOR", "claude")
    assert resolve_actor("claude") == "claude"


def test_role_alone_is_kept_when_no_client_is_configured(monkeypatch):
    monkeypatch.delenv("MDMEM_ACTOR", raising=False)
    assert resolve_actor("memory-manager") == "memory-manager"


def test_unattributable_when_nothing_identifies_the_caller(monkeypatch):
    # Better an honest "unspecified" than the old hardcoded "claude", which labelled
    # every other client's writes as Claude's.
    monkeypatch.delenv("MDMEM_ACTOR", raising=False)
    assert resolve_actor(None) == "unspecified"
    assert resolve_actor("  ") == "unspecified"


def test_surrounding_whitespace_does_not_create_a_new_actor(monkeypatch):
    monkeypatch.setenv("MDMEM_ACTOR", " cursor ")
    assert resolve_actor(" memory-manager ") == "cursor/memory-manager"
