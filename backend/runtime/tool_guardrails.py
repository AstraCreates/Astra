"""Pure tool-loop guardrails adapted from NousResearch/hermes-agent.

The original implementation is MIT licensed. This Astra adaptation keeps only
side-effect-free loop and duplicate-action detection; SafeRun remains the
authority for approvals.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

READ_ONLY_TOOLS = frozenset({
    "web_search", "news_search", "search_and_fetch", "fetch_and_read",
    "batch_search", "obsidian_read", "company_brain_search",
    "company_brain_agent_context", "company_brain_ask", "patent_search",
})
MUTATING_TOOLS = frozenset({
    "vercel_deploy", "vercel_deploy_from_github", "send_email_campaign",
    "composio_gmail_send", "composio_linkedin_post", "github_create_repo",
    "create_stripe_product", "create_stripe_price", "create_stripe_payment_link",
    "create_product_with_payment_link", "cloudflare_setup_vercel_domain",
    "cloudflare_setup_email_dns", "file_llc_live",
})


def canonical_tool_args(args: Mapping[str, Any] | None) -> str:
    return json.dumps(args or {}, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class ToolCallSignature:
    tool_name: str
    args_hash: str

    @classmethod
    def from_call(cls, tool_name: str, args: Mapping[str, Any] | None) -> "ToolCallSignature":
        digest = hashlib.sha256(canonical_tool_args(args).encode("utf-8")).hexdigest()
        return cls(tool_name, digest)


@dataclass(frozen=True)
class GuardrailDecision:
    action: str = "allow"
    code: str = "allow"
    message: str = ""
    count: int = 0
    signature: ToolCallSignature | None = None

    @property
    def allows_execution(self) -> bool:
        return self.action in {"allow", "warn"}


class ToolCallGuardrailController:
    def __init__(
        self,
        *,
        identical_warn: int = 2,
        identical_block: int = 4,
        same_tool_warn: int = 3,
        same_tool_halt: int = 7,
        unchanged_warn: int = 2,
        unchanged_block: int = 5,
    ):
        self.identical_warn = identical_warn
        self.identical_block = identical_block
        self.same_tool_warn = same_tool_warn
        self.same_tool_halt = same_tool_halt
        self.unchanged_warn = unchanged_warn
        self.unchanged_block = unchanged_block
        self._exact_failures: dict[ToolCallSignature, int] = {}
        self._tool_failures: dict[str, int] = {}
        self._unchanged: dict[ToolCallSignature, tuple[str, int]] = {}
        self._successful_mutations: set[ToolCallSignature] = set()

    def before_call(self, tool_name: str, args: Mapping[str, Any] | None) -> GuardrailDecision:
        sig = ToolCallSignature.from_call(tool_name, args)
        if sig in self._successful_mutations:
            return GuardrailDecision("block", "duplicate_mutation", f"Blocked duplicate successful external action: {tool_name}.", 1, sig)
        exact = self._exact_failures.get(sig, 0)
        if exact >= self.identical_block:
            return GuardrailDecision("block", "identical_failure", f"Blocked {tool_name}: identical arguments failed {exact} times.", exact, sig)
        same = self._tool_failures.get(tool_name, 0)
        if same >= self.same_tool_halt:
            return GuardrailDecision("block", "same_tool_failure", f"Blocked {tool_name}: it failed {same} times; change strategy.", same, sig)
        if exact >= self.identical_warn or same >= self.same_tool_warn:
            return GuardrailDecision("warn", "repeated_failure", f"{tool_name} is repeating failures; change arguments or strategy.", max(exact, same), sig)
        unchanged = self._unchanged.get(sig)
        if unchanged and unchanged[1] >= self.unchanged_block:
            return GuardrailDecision("block", "no_progress", f"Blocked {tool_name}: repeated calls returned unchanged results.", unchanged[1], sig)
        if unchanged and unchanged[1] >= self.unchanged_warn:
            return GuardrailDecision("warn", "no_progress", f"{tool_name} is returning unchanged results.", unchanged[1], sig)
        return GuardrailDecision(signature=sig)

    def after_call(self, tool_name: str, args: Mapping[str, Any] | None, result: Any, *, failed: bool) -> GuardrailDecision:
        sig = ToolCallSignature.from_call(tool_name, args)
        if failed:
            self._exact_failures[sig] = self._exact_failures.get(sig, 0) + 1
            self._tool_failures[tool_name] = self._tool_failures.get(tool_name, 0) + 1
            count = self._exact_failures[sig]
            if count >= self.identical_warn:
                return GuardrailDecision("warn", "repeated_failure", f"{tool_name} failed repeatedly with identical arguments.", count, sig)
            return GuardrailDecision(signature=sig)
        self._exact_failures.pop(sig, None)
        self._tool_failures[tool_name] = 0
        if tool_name in MUTATING_TOOLS:
            self._successful_mutations.add(sig)
        if tool_name in READ_ONLY_TOOLS:
            result_hash = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            previous_hash, count = self._unchanged.get(sig, ("", 0))
            count = count + 1 if previous_hash == result_hash else 1
            self._unchanged[sig] = (result_hash, count)
            if count >= self.unchanged_warn:
                return GuardrailDecision("warn", "no_progress", f"{tool_name} returned the same result {count} times.", count, sig)
        return GuardrailDecision(signature=sig)
