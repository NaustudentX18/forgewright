"""Tests for the ToolRegistry allowlist and namespacing."""

from __future__ import annotations

from forgewright.tool.registry import ToolRegistry


def test_namespaced_name_no_namespace() -> None:
    assert ToolRegistry.namespaced_name(None, "bash") == "bash"
    assert ToolRegistry.namespaced_name("", "bash") == "bash"


def test_namespaced_name_with_namespace() -> None:
    assert ToolRegistry.namespaced_name("github", "create_issue") == "github__create_issue"


def test_register_and_unregister() -> None:
    reg = ToolRegistry()
    full = reg.register("bash")
    assert full == "bash"
    assert "bash" in reg
    assert len(reg) == 1

    reg.unregister("bash")
    assert "bash" not in reg
    assert len(reg) == 0


def test_register_with_namespace() -> None:
    reg = ToolRegistry()
    full = reg.register("create_issue", namespace="github")
    assert full == "github__create_issue"
    assert "github__create_issue" in reg
    # The un-namespaced name should NOT be registered.
    assert "create_issue" not in reg


def test_unregister_with_namespace() -> None:
    reg = ToolRegistry()
    reg.register("create_issue", namespace="github")
    reg.unregister("create_issue", namespace="github")
    assert "github__create_issue" not in reg


def test_is_allowed_no_allowlist_allows_everything() -> None:
    reg = ToolRegistry()  # no allowlist
    assert reg.is_allowed("anything") is True
    assert reg.is_allowed("server__tool") is True


def test_is_allowed_with_allowlist_permits_members() -> None:
    reg = ToolRegistry(allowlist=["github__create_issue", "slack__post_message"])
    assert reg.is_allowed("github__create_issue") is True
    assert reg.is_allowed("slack__post_message") is True


def test_is_allowed_with_allowlist_rejects_non_members() -> None:
    reg = ToolRegistry(allowlist=["github__create_issue"])
    assert reg.is_allowed("github__delete_repo") is False
    assert reg.is_allowed("unrelated") is False
    # Even if registered, an unlisted tool is not allowed.
    reg.register("unregistered_tool", namespace="other")
    assert reg.is_allowed("other__unregistered_tool") is False


def test_names_returns_sorted_list() -> None:
    reg = ToolRegistry()
    reg.register("zebra")
    reg.register("alpha")
    reg.register("create_issue", namespace="github")
    assert reg.names() == ["alpha", "github__create_issue", "zebra"]


def test_contains_uses_namespaced_name() -> None:
    reg = ToolRegistry()
    reg.register("foo", namespace="ns")
    assert "ns__foo" in reg
    assert "foo" not in reg
