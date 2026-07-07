# VaultMind Python SDK

Python client for the [VaultMind](https://github.com/Gekvhm/VaultMind) REST API.

## Install

```bash
pip install vaultmind-client
```

Or install from source:

```bash
cd sdk/
pip install .
```

## Quick Start

```python
from vaultmind import VaultMindClient

# Connect to local VaultMind server
vm = VaultMindClient("http://localhost:8001", api_key="vm-your-key")

# Create a workspace
vm.create_workspace("research")

# Ingest text directly
vm.ingest_text("research", "Content about RAG systems...", filename="rag.md")

# Ingest from URL
vm.ingest_url("research", "https://example.com/article")

# Query with RAG
result = vm.query("research", "How does hybrid search work?")
print(result["response"])

# Browse knowledge graph
graph = vm.get_entities("research", entity_type="Concept")
for entity in graph["entities"]:
    print(f"{entity['name']} ({entity['type']})")

# OpenAI-compatible chat
result = vm.chat("research", [{"role": "user", "content": "Summarize the documents"}])
print(result["choices"][0]["message"]["content"])
```

## API Reference

| Method | Description |
|--------|-------------|
| `list_workspaces()` | List all workspaces |
| `create_workspace(name)` | Create a new workspace |
| `delete_workspace(ws_id)` | Delete a workspace |
| `get_config(ws_id)` | Get workspace configuration |
| `update_settings(ws_id, settings)` | Update workspace settings |
| `get_status(ws_id)` | Get workspace statistics |
| `ingest_text(ws_id, text, filename)` | Ingest text directly |
| `ingest_url(ws_id, url, filename)` | Ingest content from URL |
| `upload_files(ws_id, file_paths)` | Upload files |
| `list_sources(ws_id)` | List indexed sources |
| `delete_source(ws_id, name)` | Delete a source |
| `get_entities(ws_id, type, limit)` | Browse knowledge graph |
| `query(ws_id, question)` | RAG query with citations |
| `chat(ws_id, messages)` | OpenAI-compatible chat |

## License

[MIT](../LICENSE)
