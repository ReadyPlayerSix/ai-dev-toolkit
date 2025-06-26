# AI Dev Toolkit - Claude PM Pro Edition

![AI-Assisted](https://img.shields.io/badge/AI--Assisted-Claude%204-yellow?logo=anthropic&logoColor=white)
![Python Version](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10-blue)
![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-Compatible-green)
![MCP](https://img.shields.io/badge/MCP-Enabled-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Development Phase](https://img.shields.io/badge/phase-Alpha%20Rebuild-orange)

> 🚀 **Major Evolution in Progress**: The AI Dev Toolkit is undergoing a revolutionary transformation into **Claude PM Pro** - a project-aware Claude interface with persistent memory and integrated management capabilities.

## 🎯 Vision: Claude PM Pro

We're building the **ultimate project management companion for Claude** that combines:
- **🧠 Persistent Memory**: Claude never forgets your codebase across conversations
- **🎯 Project Awareness**: Automatic context loading from your projects
- **💬 Enhanced Chat Interface**: Artifact-based interface with full project context
- **⚙️ Integrated Management**: Settings and configuration accessible within the chat
- **🔄 Real-time Sync**: Live monitoring of project changes

## 🗺️ Development Roadmap

### Phase 1: Foundation Preservation ✅
- [x] Stable AI Librarian MCP Server
- [x] Persistent context system (`.ai_reference` directories)
- [x] Real-time project monitoring
- [x] Component registry and indexing
- [x] GUI configuration system

### Phase 2: Artifact Integration 🚧 **(CURRENT)**
- [ ] **Claude PM Pro Artifact** - Primary chat interface with project context
- [ ] **Multi-layered Architecture** - Artifact + MCP Server + GUI Settings Panel
- [ ] **Conversation Persistence** - Chat history saved with project context
- [ ] **Project Context Auto-loading** - Seamless integration with `.ai_reference` data
- [ ] **Settings Panel Integration** - Configuration GUI accessible from artifact

### Phase 3: Distribution & Polish
- [ ] **Artifact Publishing** - Available in Claude's artifact sharing system
- [ ] **Setup Flow** - Guided installation with GitHub integration
- [ ] **Documentation Overhaul** - Updated for new architecture
- [ ] **Performance Optimization** - Enhanced caching and context management

### Phase 4: Advanced Features
- [ ] **Multi-project Management** - Switch between project contexts seamlessly
- [ ] **Advanced Memory Systems** - Cross-project learning and insights
- [ ] **Team Collaboration** - Shared project contexts and insights
- [ ] **IDE Extensions** - VS Code and other editor integrations

## 🏗️ Current Architecture

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│                     │    │                     │    │                     │
│  Claude PM Pro      │◄──►│  AI Librarian       │◄──►│  Your Projects      │
│  Artifact           │    │  MCP Server         │    │  (.ai_reference)    │
│  (Chat Interface)   │    │  (Context Engine)   │    │  (Persistent Data)  │
│                     │    │                     │    │                     │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
           │                           │                           │
           │                           │                           │
           ▼                           ▼                           ▼
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│                     │    │                     │    │                     │
│  Settings Panel     │    │  Context Loading    │    │  File Monitoring    │
│  (GUI Integration)  │    │  (Auto-injection)   │    │  (Real-time sync)   │
│                     │    │                     │    │                     │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

## 🚀 Quick Start (Current Stable Version)

> **Note**: While Claude PM Pro is in development, you can use the current stable AI Librarian system:

### Prerequisites
- Python 3.8 or higher
- Claude Desktop (latest version)
- Git

### Installation
```bash
# Clone the repository
git clone https://github.com/isekaizen/ai-dev-toolkit.git
cd ai-dev-toolkit

# Install dependencies
pip install -r requirements.txt
pip install mcp[cli]  # Required for Claude Desktop

# Install to Claude Desktop
python development/install_to_claude.py
```

### Usage
1. **Initialize AI Librarian** for your project:
   ```
   Ask Claude: "Initialize the AI Librarian for my project at /path/to/project"
   ```

2. **Start building** with persistent context:
   ```
   Ask Claude: "Help me understand the structure of my project"
   Ask Claude: "Find all implementations of the login function"
   ```

## 🔮 Claude PM Pro Preview

Once complete, Claude PM Pro will work like this:

### 1. **Discovery & Setup**
- Find Claude PM Pro in Claude's artifact sharing system
- Click setup link → Follow guided installation
- Install MCP server and configure permissions

### 2. **Daily Workflow**
- **Open Claude PM Pro** → Artifact becomes your primary Claude interface
- **Select Project** → Automatic context loading from `.ai_reference`
- **Chat Naturally** → Every message includes relevant project context
- **Access Settings** → Configuration panel available when needed

### 3. **Persistent Memory**
- Conversations saved with project context
- Claude remembers your codebase across sessions
- Context grows smarter over time

## 📁 Development Structure

The new Claude PM Pro development is organized as follows:

### Recommended Directory Structure:
```
ai-dev-toolkit/
├── claude-pm-pro/           # 🆕 New artifact development
│   ├── src/                 # Artifact source code
│   ├── docs/                # PM Pro documentation
│   └── examples/            # Usage examples
├── aitoolkit/               # ✅ Stable MCP server (preserved)
│   ├── librarian/           # AI Librarian core
│   ├── gui/                 # Settings panel GUI
│   └── utils/               # Utilities
└── development/             # 🔧 Development tools
    ├── claude-pm-pro/       # PM Pro development scripts
    └── legacy/              # Previous development tools
```

## 🛠️ For Developers

### Current Development Phase
We're in the **Artifact Integration** phase, building:
- React-based chat interface using `window.claude.complete`
- Automatic context injection from `.ai_reference` files
- Integration layer between artifact and existing MCP server
- Settings panel toggle within the artifact

### Contributing
The project is in active development. Key areas needing work:
- **Frontend Development**: React artifact interface
- **Context Management**: Efficient loading of project data
- **UX Design**: Seamless integration between chat and settings
- **Testing**: Cross-platform compatibility

## 🔄 Migration from Current Version

Current users of AI Dev Toolkit will seamlessly transition:
- **Existing projects**: All `.ai_reference` data preserved
- **MCP Server**: Continues to work as backend
- **GUI**: Becomes integrated settings panel
- **Functionality**: Enhanced, not replaced

## 📚 Documentation Status

> **⚠️ Documentation Update in Progress**: Most existing documentation refers to the previous architecture. Updated documentation for Claude PM Pro will be available as development progresses.

### Current Documentation:
- [AI Librarian Guide](docs/ai_librarian_guide.md) - ✅ Still applicable
- [Installation Guide](docs/installation.md) - 🚧 Being updated
- [Architecture Overview](docs/architecture.md) - 🚧 Being rewritten

### Upcoming Documentation:
- Claude PM Pro User Guide
- Artifact Development Guide
- Migration Guide from Classic to PM Pro

## 🤝 Community & Support

- **GitHub Issues**: Report bugs and request features
- **Discussions**: Share ideas and get help
- **Discord**: Coming soon - Community chat for developers

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

> **💡 Stay Updated**: This project is evolving rapidly. Star the repository and watch for releases to stay informed about Claude PM Pro development progress!