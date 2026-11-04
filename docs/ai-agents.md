# AI agents

IdroGEO's data answers questions people actually ask: *is my town in a
flood zone? How many landslides are there in this valley? Is anyone watching
the one above the road?* `idrogeo-mcp` lets an AI agent answer them from the
source, with numbers it can cite, instead of from memory.

## The MCP server

--8<-- "README.md:mcp"

## How an agent uses it

A typical question takes three or four tool calls. The agent turns a name into
an ISTAT code, then reads the figures for that code:

```mermaid
sequenceDiagram
    autonumber
    participant U as You
    participant A as AI agent
    participant M as idrogeo-mcp
    participant I as IdroGEO API

    U->>A: "How many people live in high landslide hazard in Sarno?"
    A->>M: find_area("Sarno")
    M->>I: list of municipalities (once, then kept)
    M-->>A: [{"code": …, "name": "Sarno", "level": "comuni"}]
    A->>M: area_risk("comuni", code)
    M->>I: PIR indicators of that municipality
    M-->>A: residents per hazard class P1–P4, AA
    A->>M: monitoring_sites(municipality=code)
    M-->>A: sites, instruments, landslides watched
    A-->>U: answer, figures, "Source: ISPRA — IdroGEO"
```

## Other clients

The server speaks MCP over stdio, so any MCP client can start it.

=== "Claude Code"

    ```bash
    claude mcp add idrogeo -- idrogeo-mcp
    ```

=== "Claude Desktop"

    ```json
    {
      "mcpServers": {
        "idrogeo": { "command": "idrogeo-mcp" }
      }
    }
    ```

=== "Without installing (uvx)"

    ```json
    {
      "mcpServers": {
        "idrogeo": {
          "command": "uvx",
          "args": ["--from", "ispra-idrogeo[mcp]", "idrogeo-mcp"]
        }
      }
    }
    ```

## Questions to try

- *Which province of Liguria has the largest share of residents in flood hazard P3?*
- *Which landslide monitoring sites are active in the province of Belluno, and with which instruments?*
- *Compare landslide hazard exposure (P3 + P4) of Sarno, Ischia and Casamicciola Terme.*
- *What do the movement codes 1, 2 and 6 mean, in Italian and in English?*
- *Download the Molise landslide points and tell me where the folder is.*

!!! warning "Answers are information, not a safety assessment"
    PAI hazard maps and the IFFI inventory are official, but an agent's
    summary of them is not. For decisions about a building, a site or an
    emergency, refer to the competent basin authority, region or civil
    protection service.

## For coding assistants: `llms.txt`

This site publishes [`llms.txt`](llms.txt), a short plain-text guide to the
library for AI coding assistants: what to call, in which order, and the traps
to avoid. Point your assistant at
`https://agentengineering.it/ispra-idrogeo/llms.txt`.
