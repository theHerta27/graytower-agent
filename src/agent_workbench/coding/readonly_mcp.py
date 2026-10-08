"""The native Runtime MCP connection exposes read-only workspace operations."""
import argparse
import json
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .file_tools import FILE, FileTools
from .candidates import CodingWorkspace
from ..domain import CandidateRepository


def serve(workspace: Path, data: Path, preparation: dict):
    profile = preparation.get('profile')
    if profile in ('shield-damage-python-v1','skill-points-python-v1'):
        from ..code_candidates import runtime_workspace
        candidate = runtime_workspace(data, workspace, preparation)
        reader = candidate
        files = sorted(candidate.artifacts.read_ref(preparation['baseline_tree'], 'code-tree-v1')['files'])
    else:
        candidate = CodingWorkspace(workspace, CandidateRepository(data), preparation)
        reader = FileTools(workspace, data / 'coding-read-control')
        files = [FILE]
    server = MCPServer('coding-readonly', version='v1', log_level='WARNING')

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_workspace() -> dict[str, Any]:
        """List the files in this prepared, bounded Coding workspace."""
        return {'files': files, 'writable_by_child': False, 'scope': profile or 'trusted-combat-numeric-v1'}

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def read_file(path: str) -> dict[str, Any]:
        """Read a prepared game configuration file with its exact content hash."""
        return reader.read_file(path)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def check_workspace() -> dict[str, Any]:
        """Check all file changes and the supported game rules; never modify or freeze a candidate."""
        return candidate.inspect_changes()

    server.run(transport='stdio')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--preparation', type=json.loads, required=True)
    options = parser.parse_args()
    serve(options.workspace, options.data, options.preparation)
