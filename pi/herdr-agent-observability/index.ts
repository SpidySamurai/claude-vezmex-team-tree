/**
 * Companion Pi extension for the Herdr Agents Tree plugin.
 *
 * Herdr remains the product, UI, action, and state boundary. This extension
 * only observes the current Pi process's own top-level session — its agent
 * loop, its own tool calls, and its own shutdown — and forwards each event as
 * one JSON object on stdin to a small Python ingestion CLI, which owns schema
 * validation and canonical-state merge semantics (kept in one implementation,
 * see src/runtime_observability/adapters/pi_companion.py).
 *
 * A nested delegation such as AskClaude is visible here only as one top-level
 * tool call; this extension never assumes it can see inside another
 * process's session, and never reads terminal output.
 *
 * No automated test in this repository exercises this file directly: there is
 * no Node/Pi runtime harness here, only the Python test suite (`make test`).
 * Its event names and field shapes are verified against the installed
 * `@earendil-works/pi-coding-agent` type declarations; the ingestion contract
 * itself is covered by `tests/test_runtime_observability_cli.py` and
 * `tests/test_runtime_observability_pi_companion.py` using synthetic events,
 * per the design's own guidance to avoid requiring a real Pi process in unit
 * tests. Treat this file as reviewed-by-type-surface, not test-covered.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

type PiEventKind =
	| "session_start"
	| "agent_start"
	| "agent_end"
	| "agent_settled"
	| "tool_execution_start"
	| "tool_execution_end"
	| "session_shutdown";

interface PiIngestEvent {
	kind: PiEventKind;
	session_id: string;
	tool_call_id?: string;
	tool_name?: string;
	is_error?: boolean;
}

function resolveIngestionCliPath(): string {
	const override = process.env.HERDR_AGENT_OBSERVABILITY_CLI;
	if (override && existsSync(override)) return override;
	// This file ships at pi/herdr-agent-observability/index.ts inside the
	// plugin checkout; the CLI lives at the sibling src/ directory.
	const here = dirname(fileURLToPath(import.meta.url));
	return join(here, "..", "..", "src", "runtime_observability_cli.py");
}

const CLI_PATH = resolveIngestionCliPath();

function ingest(event: PiIngestEvent): void {
	if (!existsSync(CLI_PATH)) return;
	try {
		const child = spawn("python3", [CLI_PATH], { stdio: ["pipe", "ignore", "ignore"] });
		child.on("error", () => {
			/* Observability must never break the caller's own event handling. */
		});
		child.stdin.write(JSON.stringify(event));
		child.stdin.end();
	} catch {
		/* Same: a spawn failure here must not surface to the extension host. */
	}
}

export default function (pi: {
	on: (event: string, handler: (event: unknown, ctx: unknown) => void) => void;
}): void {
	const sessionId = (ctx: unknown): string | undefined => {
		const manager = (ctx as { sessionManager?: { getSessionId?: () => string } })?.sessionManager;
		return typeof manager?.getSessionId === "function" ? manager.getSessionId() : undefined;
	};

	pi.on("session_start", (_event, ctx) => {
		const id = sessionId(ctx);
		if (id) ingest({ kind: "session_start", session_id: id });
	});

	pi.on("agent_start", (_event, ctx) => {
		const id = sessionId(ctx);
		if (id) ingest({ kind: "agent_start", session_id: id });
	});

	pi.on("agent_end", (_event, ctx) => {
		const id = sessionId(ctx);
		if (id) ingest({ kind: "agent_end", session_id: id });
	});

	pi.on("agent_settled", (_event, ctx) => {
		const id = sessionId(ctx);
		if (id) ingest({ kind: "agent_settled", session_id: id });
	});

	pi.on("tool_execution_start", (event, ctx) => {
		const id = sessionId(ctx);
		const toolEvent = event as { toolCallId?: string; toolName?: string };
		if (id && toolEvent.toolCallId && toolEvent.toolName) {
			ingest({ kind: "tool_execution_start", session_id: id, tool_call_id: toolEvent.toolCallId, tool_name: toolEvent.toolName });
		}
	});

	pi.on("tool_execution_end", (event, ctx) => {
		const id = sessionId(ctx);
		const toolEvent = event as { toolCallId?: string; toolName?: string; isError?: boolean };
		if (id && toolEvent.toolCallId && toolEvent.toolName) {
			ingest({
				kind: "tool_execution_end",
				session_id: id,
				tool_call_id: toolEvent.toolCallId,
				tool_name: toolEvent.toolName,
				is_error: Boolean(toolEvent.isError),
			});
		}
	});

	pi.on("session_shutdown", (_event, ctx) => {
		const id = sessionId(ctx);
		if (id) ingest({ kind: "session_shutdown", session_id: id });
	});
}
