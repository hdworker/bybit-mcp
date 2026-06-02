"""Safety layer: mandate, halt, audit, daily count, mandate gate.

Mirrors the Vibe-Trading native ``agent.src.live`` shape so the MCP server
behaves as a first-class executor under the same runtime conventions.

Variant A from the architectural analysis: this MCP server reads the same
mandate artifact and writes to the same audit ledger as the in-process
LiveOrderGuard, but does **not** modify Vibe-Trading source. The native guard
covers in-repo ``MCPRemoteTool`` calls; this server covers cross-process
MCP tool calls (same artifact, separate enforcement path).
"""
