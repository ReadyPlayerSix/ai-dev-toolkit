# Claude PM Pro - Project Structure

## 📁 Directory Organization

```
ai-dev-toolkit/
├── claude-pm-pro/                 # 🆕 Claude PM Pro Development
│   ├── src/                       # Artifact source code
│   │   ├── components/            # React components
│   │   ├── hooks/                 # Custom React hooks
│   │   ├── utils/                 # Utility functions
│   │   ├── types/                 # TypeScript definitions
│   │   └── main.tsx               # Main artifact entry point
│   ├── docs/                      # PM Pro documentation
│   │   ├── DEVELOPMENT_ROADMAP.md # Development plan
│   │   ├── API.md                 # API documentation
│   │   ├── USER_GUIDE.md          # User instructions
│   │   └── ARCHITECTURE.md        # Technical architecture
│   └── examples/                  # Usage examples
│       ├── basic-usage.md         # Basic use cases
│       ├── advanced-features.md   # Advanced examples
│       └── integration-examples/  # Integration samples
│
├── aitoolkit/                     # ✅ Stable MCP Server (Preserved)
│   ├── librarian/                 # AI Librarian core
│   │   ├── server.py              # Main MCP server
│   │   ├── enhanced_indexer.py    # Project indexing
│   │   ├── todos.py               # Task management
│   │   └── ...                    # Other core modules
│   ├── gui/                       # Settings panel GUI
│   │   ├── configurator.py        # Main GUI application
│   │   ├── modern/                # Modern UI components
│   │   └── legacy/                # Legacy UI fallbacks
│   └── utils/                     # Shared utilities
│
├── development/                   # 🔧 Development Tools
│   ├── claude-pm-pro/             # PM Pro development scripts
│   │   ├── build_artifact.py      # Artifact build script
│   │   ├── test_integration.py    # Integration testing
│   │   └── deploy.py              # Deployment automation
│   ├── install_to_claude.py       # Claude Desktop installer
│   └── launch.py                  # Development launcher
│
├── docs/                          # 📚 General Documentation
│   ├── ai_librarian_guide.md      # AI Librarian usage
│   ├── installation.md            # Installation guide
│   └── ...                        # Other documentation
│
├── scripts/                       # 🔧 Utility Scripts
├── tests/                         # 🧪 Test Suite
├── README.md                      # Project overview
├── requirements.txt               # Python dependencies
└── LICENSE                        # MIT License
```

## 🎯 Claude PM Pro Development Focus

### `/claude-pm-pro/src/` - Artifact Source
This is where the main Claude PM Pro artifact will be developed:

- **`main.tsx`**: Entry point for the React artifact
- **`components/`**: Reusable UI components for the chat interface
- **`hooks/`**: Custom hooks for context management and API calls
- **`utils/`**: Helper functions for data processing and formatting
- **`types/`**: TypeScript definitions for better development experience

### `/claude-pm-pro/docs/` - PM Pro Documentation
Dedicated documentation for the new Claude PM Pro features:

- **`DEVELOPMENT_ROADMAP.md`**: Detailed development plan and timeline
- **`API.md`**: API documentation for integration
- **`USER_GUIDE.md`**: End-user instructions and tutorials
- **`ARCHITECTURE.md`**: Technical architecture documentation

### `/development/claude-pm-pro/` - Development Tools
Scripts and tools specifically for Claude PM Pro development:

- **`build_artifact.py`**: Builds and packages the artifact
- **`test_integration.py`**: Tests artifact-MCP server integration
- **`deploy.py`**: Deployment and publishing automation

## 🔄 Integration Points

### Artifact ↔ MCP Server
- **Communication**: Via `window.claude.complete` and direct MCP calls
- **Data Flow**: Artifact requests context → MCP server provides data
- **State Sync**: Real-time synchronization of project state

### Settings Panel ↔ Artifact
- **Integration**: GUI embedded within artifact interface
- **Control**: Toggle settings panel visibility from chat
- **Data Sharing**: Shared project configuration and preferences

### File System ↔ Context
- **Monitoring**: Real-time file change detection
- **Indexing**: Automatic `.ai_reference` updates
- **Context Loading**: Smart context injection based on conversation

## 🚀 Development Workflow

### 1. Backend Development (Stable)
```bash
cd aitoolkit/librarian/
python server.py /path/to/test/project
```

### 2. Artifact Development (New)
```bash
cd claude-pm-pro/src/
# Development within Claude Desktop artifacts system
# No separate build process - develops directly in Claude
```

### 3. Integration Testing
```bash
cd development/claude-pm-pro/
python test_integration.py
```

### 4. Documentation Updates
```bash
# Update relevant docs in claude-pm-pro/docs/
# Keep existing docs in docs/ for backward compatibility
```

## 📋 Development Priorities

### Phase 2 (Current) - File Structure Needs:
1. **`/claude-pm-pro/src/main.tsx`** - Main artifact component
2. **`/claude-pm-pro/src/components/ChatInterface.tsx`** - Chat UI
3. **`/claude-pm-pro/src/components/ProjectSelector.tsx`** - Project switcher
4. **`/claude-pm-pro/src/components/SettingsPanel.tsx`** - Embedded GUI
5. **`/claude-pm-pro/src/hooks/useProjectContext.tsx`** - Context management
6. **`/claude-pm-pro/src/utils/contextLoader.ts`** - Context loading logic

### Phase 3 - Additional Structure:
- **`/claude-pm-pro/examples/`** - Usage demonstrations
- **`/development/claude-pm-pro/publish.py`** - Artifact publishing
- **`/docs/claude-pm-pro-migration.md`** - Migration guide

## 🔧 Build and Development

### Artifact Development
Since Claude PM Pro will be developed as an artifact:
- **No traditional build process** - developed directly in Claude Desktop
- **Real-time testing** - immediate feedback during development
- **Integration testing** - via development scripts

### MCP Server (Existing)
- **No changes needed** - existing server remains stable
- **API extensions** - may add new endpoints for artifact integration
- **Performance optimization** - enhance context loading speed

### GUI Integration
- **Embedded approach** - GUI becomes a component within artifact
- **Settings management** - configuration accessible from chat interface
- **State synchronization** - shared state between chat and settings

---

This structure maintains backward compatibility with existing AI Librarian functionality while providing a clear path for Claude PM Pro development. The separation allows for independent development of the artifact while preserving the stable MCP server foundation.