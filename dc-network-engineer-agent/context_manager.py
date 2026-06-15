"""Conversation Compaction — Context Window Manager.

Implements intelligent conversation compaction inspired by Claude Code's
auto-compact and Gemini CLI's /compress approach. Instead of naively
trimming old messages (which loses context), this module:

1. Monitors token usage approaching the model's context limit.
2. Summarizes older conversation history into a concise recap.
3. Keeps recent messages verbatim for full detail.
4. Optionally persists the summary to long-term memory.

This ensures the agent retains awareness of past device states,
configuration changes, decisions, and findings even across very
long sessions.
"""

import logging
from typing import Optional, Any

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — adjust these based on the target model's context window.
# ---------------------------------------------------------------------------
MAX_CONTEXT_TOKENS = 131_072     # Model hard limit (gemma-4-31b-it)
COMPACTION_THRESHOLD = 90_000    # ~70% — trigger compaction earlier to prevent overflow
RECENT_TOKENS_BUDGET = 30_000    # Keep this many tokens of recent messages raw
SUMMARY_MAX_TOKENS = 4_000       # Max tokens allocated for the summary itself

# ---------------------------------------------------------------------------
# Compaction Summary Prompt — specialised for network engineering context
# ---------------------------------------------------------------------------
COMPACTION_PROMPT = """\
You are summarizing a conversation between a user and a Network Engineer AI agent.
Your goal is to create a concise but **comprehensive working memory** that will replace the older messages.
The AI will use ONLY this summary (plus the recent messages that follow) to continue the conversation.

## Instructions
Produce a structured summary covering these sections (omit empty sections):

### Device States
- Any device operational states discovered (interface up/down, BGP sessions, alarms, optic levels, etc.)
- Include device names, interface names, and specific values.

### Configuration Changes
- Any configuration changes that were applied or proposed (device, config hierarchy, exact set/delete commands).
- Whether changes were committed or are pending.

### Key Findings
- Root causes identified, error patterns observed, anomalies detected.
- Include specific error messages, log entries, or metric values.

### Decisions & Reasoning
- Important decisions made by the user or agent and the reasoning behind them.
- Trade-offs considered.

### Pending Tasks
- Any incomplete tasks, planned next steps, or open issues.
- Include the user's original request if it is still being worked on.

### User Context
- User preferences, constraints, or requirements mentioned.
- Names, roles, or organizational context shared by the user.

## Rules
- Be factual and specific — preserve device names, IP addresses, VLAN IDs, interface names, exact CLI commands, metric values.
- Do NOT include conversational filler, greetings, or tool call mechanics.
- Keep the summary under {max_tokens} tokens.
- Write in the same language the user has been using (Vietnamese or English).

## Conversation to summarize
{conversation}
"""


class ConversationCompactor:
    """Manages conversation context window via intelligent compaction.

    Usage:
        compactor = ConversationCompactor(llm=llm)
        # As a message_modifier callable (compatible with create_agent):
        agent = create_agent(..., message_modifier=compactor)
    """

    def __init__(
        self,
        llm,
        *,
        max_context_tokens: int = MAX_CONTEXT_TOKENS,
        compaction_threshold: int = COMPACTION_THRESHOLD,
        recent_tokens_budget: int = RECENT_TOKENS_BUDGET,
        summary_max_tokens: int = SUMMARY_MAX_TOKENS,
        memory_client=None,
        memory_id: Optional[str] = None,
    ):
        self.llm = llm
        self.max_context_tokens = max_context_tokens
        self.compaction_threshold = compaction_threshold
        self.recent_tokens_budget = recent_tokens_budget
        self.summary_max_tokens = summary_max_tokens
        self.memory_client = memory_client
        self.memory_id = memory_id

    # ------------------------------------------------------------------
    # Token counting
    # ------------------------------------------------------------------
    def _estimate_tokens(self, messages: list[BaseMessage]) -> int:
        """Estimate total token count for a list of messages.

        Tries the LLM's native token counter first; falls back to a
        character-based heuristic (1 token ≈ 2 chars) if that fails.
        Also enforces a conservative minimum estimate based on characters
        to prevent underestimation of Vietnamese text and logs.
        """
        total_chars = sum(len(self._get_message_text(m)) for m in messages)
        # Conservative minimum estimate: 1 token per 2 characters (logs/Vietnamese)
        min_estimate = total_chars // 2

        try:
            native_estimate = self.llm.get_num_tokens_from_messages(
                [self._msg_to_dict(m) for m in messages]
            )
            return max(native_estimate, min_estimate)
        except Exception:
            return min_estimate

    @staticmethod
    def _msg_to_dict(msg: BaseMessage) -> dict:
        """Convert a BaseMessage to a dict for token counting."""
        role_map = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
            "tool": "tool",
        }
        d = {
            "role": role_map.get(msg.type, msg.type),
            "content": msg.content or "",
        }
        if msg.type == "tool" and hasattr(msg, "tool_call_id"):
            d["tool_call_id"] = msg.tool_call_id
        return d

    @staticmethod
    def _get_message_text(msg: BaseMessage) -> str:
        """Extract text content from a message (handles str and list content)."""
        if isinstance(msg.content, str):
            return msg.content
        if isinstance(msg.content, list):
            return " ".join(
                part.get("text", str(part)) if isinstance(part, dict) else str(part)
                for part in msg.content
            )
        return str(msg.content)

    # ------------------------------------------------------------------
    # Compaction decision
    # ------------------------------------------------------------------
    def should_compact(self, messages: list[BaseMessage]) -> bool:
        """Return True if total tokens exceed the compaction threshold."""
        token_count = self._estimate_tokens(messages)
        logger.info(
            f"Context window usage: ~{token_count:,} / {self.max_context_tokens:,} tokens "
            f"({token_count * 100 // self.max_context_tokens}%) | Threshold: {self.compaction_threshold:,}"
        )
        return token_count > self.compaction_threshold

    # ------------------------------------------------------------------
    # Core compaction
    # ------------------------------------------------------------------
    def compact(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Compact conversation by summarizing old messages.

        Returns a new message list:
            [SystemMessage(summary)] + recent_messages

        The system prompt (if any) is always preserved.
        """
        # 1. Separate system message(s) from conversation messages
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        conv_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

        if not conv_msgs:
            return messages

        # 2. Find the split point: keep recent_tokens_budget of recent messages
        recent_start = self._find_split_point(conv_msgs)
        old_msgs = conv_msgs[:recent_start]
        recent_msgs = conv_msgs[recent_start:]

        if not old_msgs:
            # Nothing old enough to compact — return as-is
            logger.info("No old messages to compact, skipping.")
            return messages

        logger.info(
            f"Compacting: {len(old_msgs)} old messages → summary, "
            f"keeping {len(recent_msgs)} recent messages verbatim"
        )

        # 3. Generate summary of old messages
        summary_text = self._generate_summary(old_msgs)

        # 4. Persist summary to long-term memory (if configured)
        self._persist_summary(summary_text)

        # 5. Build new message list
        summary_msg = HumanMessage(
            content=(
                f"[CONVERSATION SUMMARY — earlier messages have been compacted]\n\n"
                f"{summary_text}\n\n"
                f"[END OF SUMMARY — conversation continues below]"
            )
        )

        return system_msgs + [summary_msg] + recent_msgs

    def _find_split_point(self, conv_msgs: list[BaseMessage]) -> int:
        """Find the index where recent messages start.

        Walks backward from the end, accumulating tokens until
        recent_tokens_budget is reached. Also ensures we don't split
        in the middle of a tool call sequence (AI → Tool messages).
        """
        cumulative = 0
        split_idx = len(conv_msgs)

        for i in range(len(conv_msgs) - 1, -1, -1):
            msg_tokens = self._estimate_tokens([conv_msgs[i]])
            if cumulative + msg_tokens > self.recent_tokens_budget:
                split_idx = i + 1
                break
            cumulative += msg_tokens
        else:
            # All messages fit within budget — nothing to compact
            return len(conv_msgs)

        # Adjust split point to avoid orphaned ToolMessages
        # (ToolMessages must follow their corresponding AI message with tool_calls)
        while split_idx < len(conv_msgs) and isinstance(
            conv_msgs[split_idx], ToolMessage
        ):
            split_idx -= 1

        # Ensure we start on a HumanMessage for clean context
        while split_idx < len(conv_msgs) and not isinstance(
            conv_msgs[split_idx], HumanMessage
        ):
            split_idx += 1

        # Safety: don't compact if split point leaves too few old messages
        if split_idx <= 2:
            return len(conv_msgs)

        return split_idx

    def _generate_summary(self, old_msgs: list[BaseMessage]) -> str:
        """Use the LLM to generate a structured summary of old messages."""
        # Format old messages as readable text for the summarizer
        conversation_text = self._format_messages_for_summary(old_msgs)

        prompt = COMPACTION_PROMPT.format(
            max_tokens=self.summary_max_tokens,
            conversation=conversation_text,
        )

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            summary = response.content
            logger.info(
                f"Compaction summary generated: "
                f"~{len(summary)} chars from {len(old_msgs)} messages"
            )
            return summary
        except Exception as e:
            logger.error(f"Failed to generate compaction summary: {e}")
            # Fallback: create a basic mechanical summary
            return self._fallback_summary(old_msgs)

    async def _generate_summary_async(self, old_msgs: list[BaseMessage]) -> str:
        """Use the LLM to generate a structured summary of old messages asynchronously."""
        # Format old messages as readable text for the summarizer
        conversation_text = self._format_messages_for_summary(old_msgs)

        prompt = COMPACTION_PROMPT.format(
            max_tokens=self.summary_max_tokens,
            conversation=conversation_text,
        )

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            summary = response.content
            logger.info(
                f"Compaction summary generated: "
                f"~{len(summary)} chars from {len(old_msgs)} messages"
            )
            return summary
        except Exception as e:
            logger.error(f"Failed to generate compaction summary: {e}")
            # Fallback: create a basic mechanical summary
            return self._fallback_summary(old_msgs)

    def _format_messages_for_summary(self, messages: list[BaseMessage]) -> str:
        """Format messages into readable text for the summarizer."""
        lines = []
        for msg in messages:
            role_label = {
                "human": "USER",
                "ai": "ASSISTANT",
                "tool": "TOOL_RESULT",
                "system": "SYSTEM",
            }.get(msg.type, msg.type.upper())

            content = self._get_message_text(msg)

            # Truncate very long tool results to avoid blowing up the summary prompt
            if msg.type == "tool" and len(content) > 2000:
                content = content[:1000] + "\n... [truncated] ...\n" + content[-500:]

            # Include tool call info for AI messages
            if msg.type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_names = [tc.get("name", "?") for tc in msg.tool_calls]
                lines.append(f"[{role_label}] (called tools: {', '.join(tool_names)})")
                if content:
                    lines.append(content)
            else:
                lines.append(f"[{role_label}] {content}")

        return "\n\n".join(lines)

    @staticmethod
    def _fallback_summary(old_msgs: list[BaseMessage]) -> str:
        """Create a basic summary when LLM summarization fails."""
        human_msgs = [m for m in old_msgs if isinstance(m, HumanMessage)]
        tool_names = set()
        for m in old_msgs:
            if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls:
                for tc in m.tool_calls:
                    tool_names.add(tc.get("name", "unknown"))

        summary_parts = [
            "**Fallback Summary** (LLM summarization failed)\n",
            f"- Total messages compacted: {len(old_msgs)}",
            f"- User messages: {len(human_msgs)}",
        ]

        if tool_names:
            summary_parts.append(f"- Tools used: {', '.join(sorted(tool_names))}")

        if human_msgs:
            summary_parts.append("\n**User topics discussed:**")
            for hm in human_msgs[-5:]:  # Last 5 user messages
                text = hm.content[:150] if isinstance(hm.content, str) else str(hm.content)[:150]
                summary_parts.append(f"  - {text}")

        return "\n".join(summary_parts)

    def _persist_summary(self, summary: str) -> None:
        """Store compaction summary in long-term memory for persistence."""
        if not self.memory_client or not self.memory_id:
            return
        try:
            self.memory_client.insert_memory_records_directly(
                id=self.memory_id,
                namespace="/compaction-summaries",
                request=[f"CONVERSATION_COMPACTION: {summary[:2000]}"],
            )
            logger.info("Compaction summary persisted to long-term memory")
        except Exception as e:
            logger.warning(f"Failed to persist compaction summary: {e}")

    # ------------------------------------------------------------------
    # Callable interface — used as message_modifier for create_agent
    # ------------------------------------------------------------------
    def __call__(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Make this class callable so it can be used as message_modifier.

        Usage:
            compactor = ConversationCompactor(llm=llm)
            agent = create_agent(..., message_modifier=compactor)
        """
        if self.should_compact(messages):
            logger.info(
                "🔄 Context window approaching limit — compacting conversation..."
            )
            return self.compact(messages)
        return messages


# ---------------------------------------------------------------------------
# Agent Middleware Integration (compatible with create_agent)
# ---------------------------------------------------------------------------
import copy
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import RemoveMessage

class ConversationCompactorMiddleware(AgentMiddleware):
    """LangGraph/AgentBase middleware that manages conversation length using before_model hook.

    This ensures old messages are compacted and physically removed from the
    agent's graph state, preventing context window limits and reducing checkpointer state size.
    """
    def __init__(self, compactor: ConversationCompactor):
        super().__init__()
        self.compactor = compactor
        logger.info("ConversationCompactorMiddleware initialized!")

    def before_model(self, state, runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if self.compactor.should_compact(messages):
            logger.info("🔄 (Sync) Context window approaching limit — compacting conversation via Middleware before_model...")
            
            system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
            conv_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
            
            recent_start = self.compactor._find_split_point(conv_msgs)
            old_msgs = conv_msgs[:recent_start]
            recent_msgs = conv_msgs[recent_start:]
            
            if not old_msgs:
                return None
                
            summary_text = self.compactor._generate_summary(old_msgs)
            self.compactor._persist_summary(summary_text)
            
            summary_msg = HumanMessage(
                content=(
                    f"[CONVERSATION SUMMARY — earlier messages have been compacted]\n\n"
                    f"{summary_text}\n\n"
                    f"[END OF SUMMARY — conversation continues below]"
                )
            )
            
            # Helper to copy message and strip ID to ensure correct append order in graph state
            def clean_msg(msg):
                msg_copy = copy.copy(msg)
                msg_copy.id = None
                return msg_copy
                
            clean_sys = [clean_msg(m) for m in system_msgs]
            clean_recent = [clean_msg(m) for m in recent_msgs]
            
            # Remove all and rebuild to ensure exact order
            all_removals = [RemoveMessage(id=m.id) for m in messages if getattr(m, "id", None)]
            
            return {"messages": all_removals + clean_sys + [summary_msg] + clean_recent}
        return None

    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if self.compactor.should_compact(messages):
            logger.info("🔄 (Async) Context window approaching limit — compacting conversation via Middleware abefore_model...")
            
            system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
            conv_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
            
            recent_start = self.compactor._find_split_point(conv_msgs)
            old_msgs = conv_msgs[:recent_start]
            recent_msgs = conv_msgs[recent_start:]
            
            if not old_msgs:
                return None
                
            summary_text = await self.compactor._generate_summary_async(old_msgs)
            self.compactor._persist_summary(summary_text)
            
            summary_msg = HumanMessage(
                content=(
                    f"[CONVERSATION SUMMARY — earlier messages have been compacted]\n\n"
                    f"{summary_text}\n\n"
                    f"[END OF SUMMARY — conversation continues below]"
                )
            )
            
            # Helper to copy message and strip ID to ensure correct append order in graph state
            def clean_msg(msg):
                msg_copy = copy.copy(msg)
                msg_copy.id = None
                return msg_copy
                
            clean_sys = [clean_msg(m) for m in system_msgs]
            clean_recent = [clean_msg(m) for m in recent_msgs]
            
            # Remove all and rebuild to ensure exact order
            all_removals = [RemoveMessage(id=m.id) for m in messages if getattr(m, "id", None)]
            
            return {"messages": all_removals + clean_sys + [summary_msg] + clean_recent}
        return None
