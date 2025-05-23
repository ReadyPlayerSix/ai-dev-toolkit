"""
AI Dev Toolkit Modern Configurator GUI

This is the modern GUI implementation for the AI Dev Toolkit with a sidebar layout.
It replaces all previous implementations with a more intuitive, side-tabbed version.
"""
import os
import sys
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess
import threading
import time
from pathlib import Path
import webbrowser
import traceback
import re
from typing import List, Tuple, Optional

# Import psutil if available
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

class ModernAIDevToolkitGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Dev Toolkit Control Panel")
        self.root.geometry("950x700")  # Wider to accommodate sidebar
        self.root.minsize(800, 600)    # Set minimum size
        self.root.resizable(True, True)
        
        # Set version
        self.version = "0.7.5"
        
        # Track changes
        self.has_changes = False
        
        # Capture window close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Set theme and styles
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Configure styles
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TButton', font=('Segoe UI', 10))
        self.style.configure('TLabel', font=('Segoe UI', 10), background='#f0f0f0')
        self.style.configure('Header.TLabel', font=('Segoe UI', 16, 'bold'), background='#f0f0f0')
        self.style.configure('Status.TLabel', font=('Segoe UI', 10), padding=5)
        self.style.configure('Running.Status.TLabel', background='#d4edda', foreground='#155724')
        self.style.configure('Stopped.Status.TLabel', background='#f8d7da', foreground='#721c24')
        self.style.configure('Warning.Status.TLabel', background='#fff3cd', foreground='#856404')
        self.style.configure('Disabled.TCheckbutton', foreground='#aaaaaa')
        self.style.configure('Info.TLabel', background='#edf9ff', foreground='#0c5460', padding=10)
        self.style.configure('ComingSoon.TLabel', foreground='#0056b3', font=('Segoe UI', 9, 'italic', 'bold'))
        self.style.map('TCheckbutton', 
                  foreground=[('disabled', '#aaaaaa')])
        
        # Style for server selection
        self.style.configure('Server.TCheckbutton', font=('Segoe UI', 10, 'bold'))
        
        # Style for sidebar
        self.style.configure('Sidebar.TFrame', background='#2c3e50')
        self.style.configure('Sidebar.TButton', 
                            font=('Segoe UI', 11), 
                            background='#2c3e50', 
                            foreground='white',
                            borderwidth=0,
                            focusthickness=0,
                            padding=10)
        self.style.map('Sidebar.TButton',
                     background=[('active', '#34495e'), ('pressed', '#1abc9c')],
                     foreground=[('active', 'white'), ('pressed', 'white')])
        
        # Variables
        self.claude_desktop_path = tk.StringVar()
        self.config_path = tk.StringVar()
        # Server enabled is determined by tool selection
        self.project_dirs = []
        self.project_enabled = {}  # Map of project path to enabled status
        self.server_status = tk.StringVar(value="Stopped")
        self.server_process = None
        self.server_log = tk.StringVar(value="")
        
        # Server configuration type - for official MCP servers
        self.server_config_type = tk.StringVar(value="npm")  # Default to npm package (recommended)
        
        # AI Dev Toolkit Server enabled/disabled
        self.ai_dev_toolkit_server_enabled = tk.BooleanVar(value=True)
        
        # Build UI
        self.create_widgets()
        
        # Initial checks
        self.detect_claude_desktop()
        self.load_config()
        self.check_server_status()
        self.scan_for_projects()
    
    def create_widgets(self):
        # Main container with two panes (sidebar and content)
        self.main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        # Sidebar frame (left side)
        self.sidebar_frame = ttk.Frame(self.main_container, style='Sidebar.TFrame', width=200)
        self.main_container.add(self.sidebar_frame, weight=0)
        
        # Content frame (right side)
        self.content_frame = ttk.Frame(self.main_container, style='TFrame')
        self.main_container.add(self.content_frame, weight=1)
        
        # Make the sidebar not resizable to maintain the same width
        self.main_container.configure(sashwidth=4)
        
        # Create sidebar buttons
        self.create_sidebar()
        
        # Create content frames (but only show the dashboard initially)
        self.create_content_frames()
        
        # Show the dashboard frame initially (or config if first time)
        if self.config_path.get():
            self.show_dashboard()
        else:
            self.show_claude_config()
        
        # Create a static bottom button frame (shared across all tabs)
        self.bottom_button_frame = ttk.Frame(self.root)
        self.bottom_button_frame.pack(fill=tk.X, pady=(10, 10), padx=10)
        
        # Add buttons to the static bottom frame
        ttk.Button(self.bottom_button_frame, text="Apply and Exit", command=self.apply_and_exit).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(self.bottom_button_frame, text="Apply Changes", command=self.apply_claude_config).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(self.bottom_button_frame, text="Discard Changes and Exit", command=self.discard_and_exit).pack(side=tk.RIGHT, padx=(5, 0))
    
    def create_sidebar(self):
        # Logo frame at top of sidebar
        logo_frame = ttk.Frame(self.sidebar_frame, style='Sidebar.TFrame')
        logo_frame.pack(fill=tk.X, padx=10, pady=20)
        
        # App title
        title_label = ttk.Label(logo_frame, 
                              text="AI Dev Toolkit", 
                              font=('Segoe UI', 14, 'bold'),
                              foreground='white',
                              background='#2c3e50')
        title_label.pack(anchor=tk.CENTER)
        
        # Version
        version_label = ttk.Label(logo_frame, 
                              text=f"v{self.version}", 
                              font=('Segoe UI', 9),
                              foreground='#bdc3c7',
                              background='#2c3e50')
        version_label.pack(anchor=tk.CENTER, pady=(5, 0))
        
        # Sidebar buttons - store these as attributes
        self.dashboard_btn = ttk.Button(self.sidebar_frame, 
                                      text="Dashboard", 
                                      command=self.show_dashboard,
                                      style='Sidebar.TButton')
        self.dashboard_btn.pack(fill=tk.X, pady=(30, 2))
        
        self.claude_config_btn = ttk.Button(self.sidebar_frame, 
                                        text="Claude Desktop", 
                                        command=self.show_claude_config,
                                        style='Sidebar.TButton')
        self.claude_config_btn.pack(fill=tk.X, pady=2)
        
        self.projects_btn = ttk.Button(self.sidebar_frame, 
                                    text="Projects", 
                                    command=self.show_projects,
                                    style='Sidebar.TButton')
        self.projects_btn.pack(fill=tk.X, pady=2)
        
        self.about_btn = ttk.Button(self.sidebar_frame, 
                                  text="About", 
                                  command=self.show_about,
                                  style='Sidebar.TButton')
        self.about_btn.pack(fill=tk.X, pady=2)
        
        # Status indicator at bottom of sidebar
        self.status_frame = ttk.Frame(self.sidebar_frame, style='Sidebar.TFrame')
        self.status_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=20)
        
        # Server status indicator
        self.server_status_indicator = ttk.Label(
            self.status_frame, 
            text="MCP Server: Stopped", 
            foreground='#e74c3c',
            background='#2c3e50',
            font=('Segoe UI', 9)
        )
        self.server_status_indicator.pack(anchor=tk.CENTER)
    
    def create_content_frames(self):
        # Create frames for each section but hide them initially
        # Dashboard frame
        self.dashboard_frame = ttk.Frame(self.content_frame, padding="20 20 20 20", style='TFrame')
        
        # Claude Desktop Configuration frame
        self.claude_frame = ttk.Frame(self.content_frame, padding="20 20 20 20", style='TFrame')
        
        # Project Management frame  
        self.project_frame = ttk.Frame(self.content_frame, padding="20 20 20 20", style='TFrame')
        
        # About frame
        self.about_frame = ttk.Frame(self.content_frame, padding="20 20 20 20", style='TFrame')
        
        # Setup each content frame
        self.setup_dashboard()
        self.setup_claude_tab()
        self.setup_project_tab()
        self.setup_about_tab()
    
    def show_dashboard(self):
        self.hide_all_frames()
        self.dashboard_frame.pack(fill=tk.BOTH, expand=True)
        self.highlight_active_tab(self.dashboard_btn)
    
    def show_claude_config(self):
        self.hide_all_frames()
        self.claude_frame.pack(fill=tk.BOTH, expand=True)
        self.highlight_active_tab(self.claude_config_btn)
    
    def show_projects(self):
        self.hide_all_frames()
        self.project_frame.pack(fill=tk.BOTH, expand=True)
        self.highlight_active_tab(self.projects_btn)
    
    def show_about(self):
        self.hide_all_frames()
        self.about_frame.pack(fill=tk.BOTH, expand=True)
        self.highlight_active_tab(self.about_btn)
    
    def hide_all_frames(self):
        for frame in [self.dashboard_frame, self.claude_frame, 
                    self.project_frame, self.about_frame]:
            frame.pack_forget()
    
    def highlight_active_tab(self, active_button):
        # Reset all buttons first
        for btn in [self.dashboard_btn, self.claude_config_btn, 
                  self.projects_btn, self.about_btn]:
            btn.configure(style='Sidebar.TButton')
        
        # Then highlight the active button
        active_button.configure(style='Sidebar.TButton')
        active_button.configure(background='#1abc9c')  # This doesn't actually work with ttk,
                                                    # but we leave it for documentation
        # We use a custom style for the active button
        self.style.configure('Active.Sidebar.TButton', 
                           background='#1abc9c',
                           foreground='white')
        active_button.configure(style='Active.Sidebar.TButton')
    
    #-----------------------------------------------------
    # Dashboard Tab
    #-----------------------------------------------------
    def setup_dashboard(self):
        # Header
        header_label = ttk.Label(self.dashboard_frame, text="AI Dev Toolkit Dashboard", style='Header.TLabel')
        header_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))
        
        # Status section
        status_frame = ttk.LabelFrame(self.dashboard_frame, text="System Status", padding="10 10 10 10")
        status_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        
        # Claude Desktop status
        self.claude_status_label = ttk.Label(status_frame, text="Checking Claude Desktop...", style='Status.TLabel')
        self.claude_status_label.grid(row=0, column=0, sticky="w", pady=2)
        
        # Server status
        self.server_status_label = ttk.Label(status_frame, text="MCP Server: Stopped", 
                                       style='Stopped.Status.TLabel')
        self.server_status_label.grid(row=1, column=0, sticky="w", pady=2)
        
        # Quick actions
        actions_frame = ttk.LabelFrame(self.dashboard_frame, text="Quick Actions", padding="10 10 10 10")
        actions_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 15), padx=(0, 10))
        
        ttk.Button(actions_frame, text="Restart Claude Desktop", command=self.restart_claude_desktop).pack(
            fill=tk.X, pady=5, padx=5)
            
        ttk.Button(actions_frame, text="Restart MCP Server", command=self.restart_server).pack(
            fill=tk.X, pady=5, padx=5)
            
        ttk.Button(actions_frame, text="Clear Request Queue", command=self.clear_request_queue).pack(
            fill=tk.X, pady=5, padx=5)
        
        ttk.Button(actions_frame, text="Filter Server Log", command=self.filter_server_log).pack(
            fill=tk.X, pady=5, padx=5)
        
        ttk.Button(actions_frame, text="Open Claude Config Directory", 
                 command=self.open_claude_directory).pack(
            fill=tk.X, pady=5, padx=5)
            
        ttk.Button(actions_frame, text="Upgrade Toolkit", 
                 command=self.upgrade_toolkit).pack(
            fill=tk.X, pady=5, padx=5)
        
        # Active projects
        projects_frame = ttk.LabelFrame(self.dashboard_frame, text="Active Projects", padding="10 10 10 10")
        projects_frame.grid(row=2, column=1, sticky="nsew", pady=(0, 15), padx=(10, 0))
        
        self.active_projects_listbox = tk.Listbox(projects_frame, height=6)
        self.active_projects_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        projects_scrollbar = ttk.Scrollbar(projects_frame, orient=tk.VERTICAL, command=self.active_projects_listbox.yview)
        projects_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.active_projects_listbox.config(yscrollcommand=projects_scrollbar.set)
        
        # Server log preview
        log_frame = ttk.LabelFrame(self.dashboard_frame, text="Server Log", padding="10 10 10 10")
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 15))
        
        self.log_text = tk.Text(log_frame, height=10, width=80, wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scrollbar.set)
        self.log_text.insert(tk.END, "Server log will appear here when the server is started.")
        self.log_text.config(state=tk.DISABLED)
        
        # Configure grid weights
        self.dashboard_frame.columnconfigure(0, weight=1)
        self.dashboard_frame.columnconfigure(1, weight=1)
        self.dashboard_frame.rowconfigure(3, weight=1)
    
    #-----------------------------------------------------
    # Claude Desktop Tab
    #-----------------------------------------------------
    def setup_claude_tab(self):
        # Header
        header_label = ttk.Label(self.claude_frame, text="Claude Desktop Configuration", style='Header.TLabel')
        header_label.pack(pady=(0, 20), anchor=tk.W)
        
        # Claude Desktop section
        claude_config_frame = ttk.LabelFrame(self.claude_frame, text="Claude Desktop", padding="10 10 10 10")
        claude_config_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Claude Desktop status
        self.claude_config_status_label = ttk.Label(claude_config_frame, text="Checking Claude Desktop installation...", style='TLabel')
        self.claude_config_status_label.pack(anchor=tk.W, pady=(0, 5))
        
        # Claude Desktop path
        path_frame = ttk.Frame(claude_config_frame)
        path_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(path_frame, text="Config Path:", style='TLabel').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Entry(path_frame, textvariable=self.config_path, width=50).pack(side=tk.LEFT, padx=(0, 5), fill=tk.X, expand=True)
        ttk.Button(path_frame, text="Browse...", command=self.browse_config).pack(side=tk.LEFT)
        
        # Safety disclaimer
        safety_frame = ttk.Frame(claude_config_frame, style='TFrame')
        safety_frame.pack(fill=tk.X, pady=(10, 0))
        
        safety_label = ttk.Label(safety_frame, 
                               text="Note: This application edits Claude Desktop's configuration file. Claude itself does not have direct access to edit these files.",
                               wraplength=750, style='Info.TLabel')
        safety_label.pack(fill=tk.X)
        
        # AI Dev Toolkit Servers section
        server_selection_frame = ttk.LabelFrame(self.claude_frame, text="AI Dev Toolkit Servers", padding="10 10 10 10")
        server_selection_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Note about server selection
        server_note = ttk.Label(server_selection_frame, 
                              text="The following MCP server is available for Claude Desktop:",
                              wraplength=750)
        server_note.pack(anchor=tk.W, pady=(0, 10))
        
        # AI Dev Toolkit Integrated Server checkbox
        integrated_server_check = ttk.Checkbutton(server_selection_frame, 
                                               text="AI Dev Toolkit Integrated Server", 
                                               variable=self.ai_dev_toolkit_server_enabled,
                                               style='Server.TCheckbutton',
                                               command=self.update_server_status)
        integrated_server_check.pack(anchor=tk.W, pady=5)
        
        # Description of the integrated server
        integrated_description = ttk.Label(server_selection_frame, 
                                        text="The integrated server combines multiple capabilities:",
                                        wraplength=750)
        integrated_description.pack(anchor=tk.W, padx=(20, 0), pady=(0, 5))
        
        # List the integrated server features
        features_frame = ttk.Frame(server_selection_frame)
        features_frame.pack(fill=tk.X, padx=(30, 0))
        
        ttk.Label(features_frame, text="• File System Tools - Read, write, and navigate the file system", 
                 wraplength=700).pack(anchor=tk.W, pady=2)
        ttk.Label(features_frame, text="• AI Librarian - Code analysis with self-verification and persistent memory", 
                 wraplength=700).pack(anchor=tk.W, pady=2)
        ttk.Label(features_frame, text="• Task Management - Track and organize development tasks", 
                 wraplength=700).pack(anchor=tk.W, pady=2)
        ttk.Label(features_frame, text="• Enhanced Code Analysis - Find related files, references, and component details", 
                 wraplength=700).pack(anchor=tk.W, pady=2)
        ttk.Label(features_frame, text="• Think Tool - Structured reasoning for complex problems", 
                 wraplength=700).pack(anchor=tk.W, pady=2)
        
        # Project Starter Server checkbox (Coming Soon)
        project_starter_frame = ttk.Frame(server_selection_frame)
        project_starter_frame.pack(fill=tk.X, anchor=tk.W, pady=5)
        project_starter_check = ttk.Checkbutton(project_starter_frame, 
                                              text="Project Starter Server - Project generation and scaffolding", 
                                              state='disabled',
                                              style='Server.TCheckbutton')
        project_starter_check.pack(side=tk.LEFT)
        
        # Coming Soon label for Project Starter - with more visible styling
        project_starter_coming_soon = ttk.Label(project_starter_frame, 
                                            text="(Coming Soon)",
                                            style='ComingSoon.TLabel')
        project_starter_coming_soon.pack(side=tk.LEFT, padx=5)
        
        # Note about Claude Desktop compatibility
        claude_compat_note = ttk.Label(server_selection_frame, 
                                    text="Note: These servers are currently compatible with Claude Desktop only.",
                                    wraplength=750, style='Info.TLabel')
        claude_compat_note.pack(fill=tk.X, pady=(10, 0))
        
        # Official MCP Servers section - add a frame to contain both the section and the button
        bottom_frame = ttk.Frame(self.claude_frame)
        bottom_frame.pack(fill=tk.X, pady=(0, 5))
        
        mcp_servers_frame = ttk.LabelFrame(bottom_frame, text="Official MCP Servers", padding="10 10 10 10")
        mcp_servers_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Note about official MCP servers
        mcp_servers_note = ttk.Label(mcp_servers_frame, 
                                   text="There are many official MCP servers available from the Model Context Protocol repository. " +
                                   "Visit the link below to explore them.",
                                   wraplength=750)
        mcp_servers_note.pack(anchor=tk.W, pady=(0, 10))
        
        # Server configuration type
        server_type_frame = ttk.Frame(mcp_servers_frame, style='TFrame')
        server_type_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(server_type_frame, text="Server Configuration Type:", style='TLabel').pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Radiobutton(server_type_frame, text="NPM Package (Recommended)", 
                       variable=self.server_config_type, value="npm",
                       command=self.update_server_config_type).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Radiobutton(server_type_frame, text="Python with uv (For Development)", 
                       variable=self.server_config_type, value="uv",
                       command=self.update_server_config_type).pack(side=tk.LEFT)
        
        # Server status (automatic based on tools)
        self.server_config_status_label = ttk.Label(mcp_servers_frame, text="MCP Server configuration is determined by selected servers", style='TLabel')
        self.server_config_status_label.pack(anchor=tk.W, pady=(5, 5))
        
        # NPM configuration note
        self.npm_config_note = ttk.Label(mcp_servers_frame, 
                                       text="Using NPM Package: This approach is recommended for most users and works with standard Claude Desktop configuration.",
                                       wraplength=750, style='Info.TLabel')
        self.npm_config_note.pack(fill=tk.X, pady=(0, 5))
        
        # uv configuration note - hidden initially
        self.uv_config_note = ttk.Label(mcp_servers_frame, 
                                       text="Using Python with uv: This approach requires uv to be installed and is recommended for development. All paths must be absolute.",
                                       wraplength=750, style='Info.TLabel')
        
        # GitHub link for MCP servers
        mcp_servers_link = ttk.Label(mcp_servers_frame, 
                                   text="Official MCP Servers Repository", 
                                   foreground="blue", cursor="hand2")
        mcp_servers_link.pack(anchor=tk.W, pady=2)
        mcp_servers_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/modelcontextprotocol/servers"))
        
        # Button row that will be placed at the bottom with minimal padding
        button_row = ttk.Frame(bottom_frame)
        button_row.pack(fill=tk.X, pady=2)
        
        # Button for adding project directories - now in a frame with controlled padding
        add_proj_btn = ttk.Button(button_row, text="Add Project Directories", 
                                 command=self.show_projects)
        add_proj_btn.pack(side=tk.LEFT, padx=0, pady=0)
    
    #-----------------------------------------------------
    # Project Management Tab
    #-----------------------------------------------------
    def setup_project_tab(self):
        # Header
        header_label = ttk.Label(self.project_frame, text="Project Management", style='Header.TLabel')
        header_label.pack(pady=(0, 20), anchor=tk.W)
        
        # Main content frame with two columns
        main_content = ttk.Frame(self.project_frame)
        main_content.pack(fill=tk.BOTH, expand=True)
        main_content.columnconfigure(0, weight=3)  # Directory list side
        main_content.columnconfigure(1, weight=2)  # Controls and viewer side
        
        # Left side: Project lists and documents
        left_side = ttk.Frame(main_content)
        left_side.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        # Project Document Viewer (top part of left side)
        doc_viewer_frame = ttk.LabelFrame(left_side, text="Project Documentation", padding="10 10 10 10")
        doc_viewer_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # README/Documentation viewer with scrollbars
        self.doc_text = tk.Text(doc_viewer_frame, height=10, width=60, wrap=tk.WORD)
        doc_scroll_y = ttk.Scrollbar(doc_viewer_frame, orient=tk.VERTICAL, command=self.doc_text.yview)
        
        self.doc_text.configure(yscrollcommand=doc_scroll_y.set)
        self.doc_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        doc_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Initialize with placeholder text
        self.doc_text.insert(tk.END, "Select a project to view its documentation.\n\nThe README.md or other documentation files from the project root will be displayed here.")
        self.doc_text.config(state=tk.DISABLED)
        
        # Project navigation buttons
        doc_nav_frame = ttk.Frame(doc_viewer_frame)
        doc_nav_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.prev_doc_btn = ttk.Button(doc_nav_frame, text="←", width=3, command=self.prev_document, state=tk.DISABLED)
        self.prev_doc_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.current_doc_var = tk.StringVar(value="No document")
        self.current_doc_label = ttk.Label(doc_nav_frame, textvariable=self.current_doc_var)
        self.current_doc_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.next_doc_btn = ttk.Button(doc_nav_frame, text="→", width=3, command=self.next_document, state=tk.DISABLED)
        self.next_doc_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Projects Directory List (bottom part of left side)
        projects_frame = ttk.LabelFrame(left_side, text="Project Directories", padding="10 10 10 10")
        projects_frame.pack(fill=tk.BOTH, expand=True)
        
        # Project list using a Treeview with expanded columns
        self.projects_treeview = ttk.Treeview(
            projects_frame, 
            columns=("Private", "Path", "Status", "LastAccessed", "GitStatus"), 
            selectmode='browse', 
            height=10
        )
        
        # Configure the treeview
        self.projects_treeview.heading('#0', text='Enabled')
        self.projects_treeview.heading('Private', text='Public/Private')
        self.projects_treeview.heading('Path', text='Project Path')
        self.projects_treeview.heading('Status', text='Access')
        self.projects_treeview.heading('LastAccessed', text='Last Accessed')
        self.projects_treeview.heading('GitStatus', text='Git Status')
        
        # Set column widths and icons
        self.projects_treeview.column('#0', width=80, stretch=False, anchor='center')
        self.projects_treeview.column('Private', width=100, stretch=False, anchor='center')
        self.projects_treeview.column('Path', width=300, stretch=True)
        self.projects_treeview.column('Status', width=90, stretch=False)
        self.projects_treeview.column('LastAccessed', width=120, stretch=False)
        self.projects_treeview.column('GitStatus', width=100, stretch=False)
        
        # Add scrollbars
        tree_frame = ttk.Frame(projects_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.projects_treeview.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.projects_treeview.xview)
        
        self.projects_treeview.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        
        # Pack the treeview and scrollbars
        self.projects_treeview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Bind events
        self.projects_treeview.bind('<ButtonRelease-1>', self.on_treeview_click)
        self.projects_treeview.bind('<<TreeviewSelect>>', self.on_project_selected)
        
        # Right side: Controls and logs
        right_side = ttk.Frame(main_content)
        right_side.grid(row=0, column=1, sticky="nsew")
        
        # Project Controls (top part of right side)
        controls_frame = ttk.LabelFrame(right_side, text="Project Controls", padding="10 10 10 10")
        controls_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Button grid for controls - 2 columns
        btn_frame = ttk.Frame(controls_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # Buttons now on the right side
        ttk.Button(btn_frame, text="Add Project", width=20, command=self.add_directory).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(btn_frame, text="Remove Project", width=20, command=self.remove_directory).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(btn_frame, text="Create Project", width=20, command=self.toggle_create_project_area).grid(row=1, column=0, padx=5, pady=5)
        
        # Open Project With... button with default app selection
        open_project_frame = ttk.Frame(btn_frame)
        open_project_frame.grid(row=1, column=1, padx=5, pady=5)
        
        self.open_with_btn = ttk.Button(open_project_frame, text="Open Project With...", width=20, command=self.open_project_with)
        self.open_with_btn.pack(side=tk.TOP, pady=(0, 5))
        
        # Default application selection
        self.default_app_var = tk.StringVar(value="Default Application")
        default_apps = ["VS Code", "Notepad", "Explorer", "Custom..."]
        
        self.default_app_combo = ttk.Combobox(open_project_frame, textvariable=self.default_app_var, values=default_apps, width=18)
        self.default_app_combo.pack(side=tk.TOP)
        self.default_app_combo.bind("<<ComboboxSelected>>", self.set_default_application)
        
        # Project privacy section
        privacy_frame = ttk.Frame(controls_frame)
        privacy_frame.pack(fill=tk.X, pady=10)
        
        self.privacy_var = tk.StringVar(value="Public")
        ttk.Label(privacy_frame, text="Selected Project Privacy:").pack(side=tk.LEFT, padx=(0, 10))
        
        self.public_radio = ttk.Radiobutton(
            privacy_frame, text="Public", variable=self.privacy_var, 
            value="Public", command=self.update_project_privacy
        )
        self.public_radio.pack(side=tk.LEFT, padx=(0, 10))
        
        self.private_radio = ttk.Radiobutton(
            privacy_frame, text="Private", variable=self.privacy_var, 
            value="Private", command=self.update_project_privacy
        )
        self.private_radio.pack(side=tk.LEFT)
        
        # Message area for project updates
        self.project_message_var = tk.StringVar()
        self.project_message_label = ttk.Label(self.project_frame, textvariable=self.project_message_var, 
                                            style='Info.TLabel', wraplength=750)
        self.project_message_label.pack(fill=tk.X, pady=(10, 0))
        
        # Initially set a default message
        self.project_message_var.set("Add project directories that Claude should have access to.")
        
        # Log frame now at the bottom of the entire tab, not in the right side
        log_frame = ttk.LabelFrame(self.project_frame, text="Server Log", padding="10 10 10 10")
        log_frame.pack(fill=tk.X, expand=False, pady=(10, 0))
        
        self.project_log_text = tk.Text(log_frame, height=8, width=100, wrap=tk.WORD)
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.project_log_text.yview)
        
        self.project_log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.project_log_text.config(yscrollcommand=log_scrollbar.set)
        
        self.project_log_text.insert(tk.END, "Server log will appear here when the server is started.")
        self.project_log_text.config(state=tk.DISABLED)
        
        # Create project section (hidden initially)
        self.create_project_frame = ttk.LabelFrame(self.project_frame, text="Create New Project", padding="10 10 10 10")
        
        # Project name
        name_frame = ttk.Frame(self.create_project_frame)
        name_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(name_frame, text="Project Name:", width=15).pack(side=tk.LEFT)
        self.new_project_name = tk.StringVar()
        ttk.Entry(name_frame, textvariable=self.new_project_name).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Project type
        type_frame = ttk.Frame(self.create_project_frame)
        type_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(type_frame, text="Project Type:", width=15).pack(side=tk.LEFT)
        self.new_project_type = tk.StringVar(value="web")
        type_combo = ttk.Combobox(type_frame, textvariable=self.new_project_type, 
                                values=["web", "cli", "library", "api"])
        type_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Project location
        location_frame = ttk.Frame(self.create_project_frame)
        location_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(location_frame, text="Location:", width=15).pack(side=tk.LEFT)
        self.new_project_location = tk.StringVar()
        ttk.Entry(location_frame, textvariable=self.new_project_location).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(location_frame, text="Browse...", command=self.browse_project_location).pack(side=tk.LEFT)
        
        # Create button row
        button_row = ttk.Frame(self.create_project_frame)
        button_row.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(button_row, text="Cancel", 
                command=lambda: self.create_project_frame.pack_forget()).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_row, text="Create Project", 
                command=self.create_new_project).pack(side=tk.RIGHT)
        
        # Add data structures for new features
        self.project_privacy = {}  # Dictionary to store privacy settings
        self.project_last_accessed = {}  # Dictionary to store last accessed times
        self.project_git_status = {}  # Dictionary to store git status
        self.project_documents = {}  # Dictionary to store project documents
        self.current_project = None  # Currently selected project
        self.current_doc_index = 0  # Index of currently displayed document
        
        # Create custom style for larger checkboxes
        self.style.configure('Large.Treeview', rowheight=30)  # Make rows taller
        self.projects_treeview.configure(style='Large.Treeview')  # Apply the style

    #-----------------------------------------------------
    # About Tab  
    #-----------------------------------------------------
    def setup_about_tab(self):
        # Header
        header_label = ttk.Label(self.about_frame, text="About AI Dev Toolkit", style='Header.TLabel')
        header_label.pack(pady=(0, 20), anchor=tk.W)
        
        # Version info
        version_frame = ttk.Frame(self.about_frame)
        version_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(version_frame, text=f"Version: {self.version}", font=('Segoe UI', 12)).pack(anchor=tk.W)
        
        # Description
        desc_frame = ttk.LabelFrame(self.about_frame, text="Description", padding="10 10 10 10")
        desc_frame.pack(fill=tk.X, pady=(0, 20))
        
        description = """The AI Dev Toolkit enhances Claude with powerful capabilities through its integrated MCP server:

1. File System Tools: Read, write, and navigate the file system securely
2. AI Librarian: Helps Claude understand your codebase with self-checks to ensure proper functionality
3. Task Management: Track development tasks across conversations
4. Enhanced Code Analysis: Find related files, references, and detailed component information
5. Project Starter: Project generation and scaffolding (Coming Soon)
6. Think Tool: Structured reasoning for complex problems (Coming Soon)"""
        
        ttk.Label(desc_frame, text=description, wraplength=800, justify=tk.LEFT).pack(anchor=tk.W)
        
        # Safety information
        safety_frame = ttk.LabelFrame(self.about_frame, text="Important Safety Information", padding="10 10 10 10")
        safety_frame.pack(fill=tk.X, pady=(0, 20))
        
        safety_text = """The AI Dev Toolkit provides an MCP (Model Context Protocol) server that Claude can use to access your files and execute tools on your computer.

IMPORTANT: The AI Dev Toolkit application edits Claude Desktop's configuration to enable these tools. Claude itself does not have direct access to edit configuration files. All file operations and tool executions happen in your local environment and with your explicit permission.

When you enable project directories, you are granting Claude permission to read from and write to those directories. Choose directories carefully."""
        
        ttk.Label(safety_frame, text=safety_text, wraplength=800, justify=tk.LEFT).pack(anchor=tk.W)
        
        # Links
        links_frame = ttk.Frame(self.about_frame)
        links_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(links_frame, text="Resources:", font=('Segoe UI', 12, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        # Documentation link
        doc_link = ttk.Label(links_frame, text="Model Context Protocol Documentation", 
                           foreground="blue", cursor="hand2")
        doc_link.pack(anchor=tk.W, pady=2)
        doc_link.bind("<Button-1>", lambda e: webbrowser.open("https://modelcontextprotocol.io"))
        
        # GitHub link
        github_link = ttk.Label(links_frame, text="AI Dev Toolkit on GitHub", 
                              foreground="blue", cursor="hand2")
        github_link.pack(anchor=tk.W, pady=2)
        github_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/isekaizen/ai-dev-toolkit"))
        
        # MCP Servers link 
        servers_link = ttk.Label(links_frame, text="Official MCP Servers Repository", 
                               foreground="blue", cursor="hand2")
        servers_link.pack(anchor=tk.W, pady=2)
        servers_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/modelcontextprotocol/servers"))

    # The rest of the methods remain the same as in configurator_unified.py
    # I'll include just a few key methods that need to be updated for the new UI
    
    def update_server_status(self):
        """Update server status based on selected tools"""
        # Update server status based on selections
        if self.ai_dev_toolkit_server_enabled.get():
            self.server_status_label.config(text="MCP Server: Ready to Configure", style='Status.TLabel')
            self.server_status_indicator.config(text="MCP Server: Ready", foreground='#2ecc71')
        else:
            self.server_status_label.config(text="MCP Server: Disabled", style='Stopped.Status.TLabel')
            self.server_status_indicator.config(text="MCP Server: Disabled", foreground='#e74c3c')
        
        self.has_changes = True
    
    def check_server_status(self):
        """Check if the server is running"""
        if hasattr(self, 'server_process') and self.server_process and self.server_process.poll() is None:
            self.server_status_label.config(text="MCP Server: Running", style='Running.Status.TLabel')
            self.server_status_indicator.config(text="MCP Server: Running", foreground='#2ecc71')
        else:
            self.server_status_label.config(text="MCP Server: Stopped", style='Stopped.Status.TLabel')
            self.server_status_indicator.config(text="MCP Server: Stopped", foreground='#e74c3c')
    
    # All other methods from configurator_unified.py should be copied here
    # ...

    # -----------------------------------------------------
    # Required method implementations (partial list)
    # -----------------------------------------------------
    def on_project_selected(self, event):
        """Handle project selection in the treeview"""
        selected_item = self.projects_treeview.selection()
        if selected_item:
            # Get the directory path from the selected item values
            values = self.projects_treeview.item(selected_item[0], 'values')
            if values:
                dir_path = values[0]  # Path is in the first column
                self.current_project = dir_path
                self.load_project_documentation(dir_path)
                
                # Update UI elements based on project selection
                # For example, enable the Open Project With... button
                if hasattr(self, 'open_with_btn'):
                    self.open_with_btn.config(state=tk.NORMAL)
    
    def open_project_with(self):
        """Open the selected project with the specified application"""
        if not self.current_project:
            messagebox.showinfo("No Project Selected", "Please select a project first.")
            return
            
        # Get the application to use
        app = self.default_app_var.get()
        
        try:
            if app == "VS Code":
                # Open with VS Code
                subprocess.Popen(["code", self.current_project])
            elif app == "Notepad":
                # Open with Notepad (just opens the first file it finds)
                subprocess.Popen(["notepad", os.path.join(self.current_project, "README.md")])
            elif app == "Explorer":
                # Open with File Explorer
                os.startfile(self.current_project)
            elif app == "Custom...":
                # Ask for a custom command
                from tkinter import simpledialog
                custom_cmd = simpledialog.askstring("Custom Command", 
                                                  "Enter the command to open the project:",
                                                  initialvalue="")
                if custom_cmd:
                    subprocess.Popen([custom_cmd, self.current_project])
            else:
                # Just use default application
                os.startfile(self.current_project)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open project: {str(e)}")
    
    def set_default_application(self, event):
        """Set the default application for opening projects"""
        # This is called when a selection is made in the combobox
        # Nothing special needed here since we read the combobox value when opening
        pass
    
    def update_project_privacy(self):
        """Update the privacy setting for the selected project"""
        if not self.current_project:
            return
            
        # Update the privacy setting
        privacy = self.privacy_var.get()
        self.project_privacy[self.current_project] = privacy
        
        # Update the treeview with the new privacy setting
        selected_item = self.projects_treeview.selection()
        if selected_item:
            # Update the Private column (column 0)
            self.projects_treeview.set(selected_item[0], "Private", privacy)
    
    def on_treeview_click(self, event):
        """Handle click on treeview - toggle checkbox if clicked in the checkbox column"""
        # Get the item that was clicked
        region = self.projects_treeview.identify_region(event.x, event.y)
        item_id = self.projects_treeview.identify_row(event.y)
        
        if item_id and (region == 'tree' or region == 'cell'):
            # Get the column and check if it's the checkbox column
            column = self.projects_treeview.identify_column(event.x)
            
            if column == '#0' or int(event.x) < 70:  # Checkbox column
                # Toggle checkbox state
                current_text = self.projects_treeview.item(item_id, 'text')
                new_text = "◻" if current_text == "✓" else "✓"
                self.projects_treeview.item(item_id, text=new_text)
                
                # Update state in project_enabled dictionary
                dir_path = self.projects_treeview.item(item_id, 'values')[0]
                self.project_enabled[dir_path] = (new_text == "✓")
                
                # Update active projects list on dashboard
                self.update_active_projects_list()
                
                # Mark changes
                self.has_changes = True
    
    def update_active_projects_list(self):
        """Update the list of active projects on the dashboard"""
        self.active_projects_listbox.delete(0, tk.END)
        
        for dir_path in self.project_dirs:
            if self.project_enabled.get(dir_path, False):
                has_ai_ref = os.path.exists(os.path.join(dir_path, ".ai_reference"))
                status = "AI Librarian" if has_ai_ref else "Regular"
                self.active_projects_listbox.insert(tk.END, f"{dir_path} [{status}]")
    
    def load_project_documentation(self, project_path):
        """Load documentation from the project directory"""
        if not os.path.exists(project_path):
            return
            
        # Reset document navigation
        self.project_documents[project_path] = []
        self.current_doc_index = 0
        
        # Look for documentation files
        doc_files = []
        
        # First, check for README.md
        readme_path = os.path.join(project_path, "README.md")
        if os.path.exists(readme_path):
            doc_files.append(("README", readme_path))
            
        # Check for other common documentation files
        doc_patterns = ["CHANGELOG.md", "CONTRIBUTING.md", "LICENSE", "docs/*.md"]
        for pattern in doc_patterns:
            if "*" in pattern:
                # Handle wildcards
                import glob
                base_dir, pat = pattern.split("/", 1)
                search_dir = os.path.join(project_path, base_dir)
                if os.path.exists(search_dir):
                    for file_path in glob.glob(os.path.join(search_dir, pat)):
                        name = os.path.basename(file_path)
                        doc_files.append((name, file_path))
            else:
                # Direct file
                file_path = os.path.join(project_path, pattern)
                if os.path.exists(file_path):
                    name = os.path.basename(file_path)
                    doc_files.append((name, file_path))
        
        # Store documents
        self.project_documents[project_path] = doc_files
        
        # Display the first document if available
        if doc_files:
            self.display_current_document()
            
            # Enable navigation buttons if more than one document
            self.prev_doc_btn.config(state=tk.NORMAL if len(doc_files) > 1 else tk.DISABLED)
            self.next_doc_btn.config(state=tk.NORMAL if len(doc_files) > 1 else tk.DISABLED)
        else:
            # No documentation found
            self.doc_text.config(state=tk.NORMAL)
            self.doc_text.delete(1.0, tk.END)
            self.doc_text.insert(tk.END, "No documentation found for this project.")
            self.doc_text.config(state=tk.DISABLED)
            
            # Disable navigation buttons
            self.prev_doc_btn.config(state=tk.DISABLED)
            self.next_doc_btn.config(state=tk.DISABLED)
            
            # Update label
            self.current_doc_var.set("No documentation")
    
    def display_current_document(self):
        """Display the current document"""
        if not self.current_project or self.current_project not in self.project_documents:
            return
            
        doc_files = self.project_documents[self.current_project]
        if not doc_files:
            return
            
        # Ensure current_doc_index is in range
        if self.current_doc_index < 0:
            self.current_doc_index = len(doc_files) - 1
        elif self.current_doc_index >= len(doc_files):
            self.current_doc_index = 0
            
        # Get the current document
        doc_name, doc_path = doc_files[self.current_doc_index]
        
        # Read the file content
        try:
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Display in the text widget
            self.doc_text.config(state=tk.NORMAL)
            self.doc_text.delete(1.0, tk.END)
            self.doc_text.insert(tk.END, content)
            self.doc_text.config(state=tk.DISABLED)
            
            # Update the label
            self.current_doc_var.set(doc_name)
        except Exception as e:
            self.doc_text.config(state=tk.NORMAL)
            self.doc_text.delete(1.0, tk.END)
            self.doc_text.insert(tk.END, f"Error loading document: {str(e)}")
            self.doc_text.config(state=tk.DISABLED)
    
    def next_document(self):
        """Navigate to the next document"""
        self.current_doc_index += 1
        self.display_current_document()
        
    def prev_document(self):
        """Navigate to the previous document"""
        self.current_doc_index -= 1
        self.display_current_document()
    
    def add_directory(self):
        """Add a directory to the project list"""
        dir_path = filedialog.askdirectory(title="Select Project Directory")
        if dir_path:
            if dir_path not in self.project_dirs:
                self.project_dirs.append(dir_path)
                self.project_enabled[dir_path] = True
                self.has_changes = True
                self.update_projects_list()
                self.project_message_var.set(f"Added project directory: {dir_path}")
            else:
                messagebox.showinfo("Already Added", "This directory is already in the project list.")
    
    def remove_directory(self):
        """Remove the selected directory from the treeview"""
        selected_item = self.projects_treeview.selection()
        if selected_item:
            # Get the directory path from the selected item
            dir_path = self.projects_treeview.item(selected_item[0], 'values')[0]
            
            # Remove directory from project_dirs list
            if dir_path in self.project_dirs:
                self.project_dirs.remove(dir_path)
                if dir_path in self.project_enabled:
                    del self.project_enabled[dir_path]
                
                # Update displays
                self.update_projects_list()
                self.update_active_projects_list()
                
                # Mark as changed
                self.has_changes = True
                
                # Show message
                self.project_message_var.set(f"Removed project directory: {dir_path}")
        else:
            messagebox.showinfo("No Selection", "Please select a project to remove.")
    
    def update_projects_list(self):
        """Update the projects list display using the treeview"""
        # Clear the treeview
        for item in self.projects_treeview.get_children():
            self.projects_treeview.delete(item)
        
        # Clear active projects listbox
        self.active_projects_listbox.delete(0, tk.END)
        
        # Remove any duplicate entries from project_dirs
        unique_dirs = []
        for dir_path in self.project_dirs:
            if dir_path not in unique_dirs:
                unique_dirs.append(dir_path)
        
        # Update project_dirs with the deduplicated list
        self.project_dirs = unique_dirs
        
        # Repopulate with current projects
        for i, dir_path in enumerate(self.project_dirs):
            enabled = self.project_enabled.get(dir_path, True)
            
            # Check if path has AI Librarian
            has_ai_ref = os.path.exists(os.path.join(dir_path, ".ai_reference"))
            status = "AI Librarian" if has_ai_ref else "Regular"
            
            # Add to treeview with checkbox state
            item_id = self.projects_treeview.insert('', 'end', 
                                                  text="✓" if enabled else "◻", 
                                                  values=(dir_path, status))
            
            # Add to active projects listbox if enabled
            if enabled:
                self.active_projects_listbox.insert(tk.END, f"{dir_path} [{status}]")
    
    def toggle_create_project_area(self):
        """Show or hide the create project area"""
        if self.create_project_frame.winfo_ismapped():
            self.create_project_frame.pack_forget()
        else:
            self.create_project_frame.pack(fill=tk.X, pady=(0, 15))
    
    def browse_config(self):
        """Browse for Claude Desktop config file"""
        config_file = filedialog.askopenfilename(
            title="Select Claude Desktop Configuration File",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if config_file:
            self.config_path.set(config_file)
    
    def browse_project_location(self):
        """Browse for project location directory"""
        dir_path = filedialog.askdirectory(title="Select Project Location")
        if dir_path:
            self.new_project_location.set(dir_path)
    
    def create_new_project(self):
        """Create a new project with template files"""
        # Implement project creation logic here
        pass
    
    def detect_claude_desktop(self):
        """Detect Claude Desktop installation and config location"""
        self.claude_status_label.config(text="Checking Claude Desktop installation...")
        self.claude_config_status_label.config(text="Checking Claude Desktop installation...")
        
        # Detect platform and find config path
        import platform
        system = platform.system()
        
        config_path = None
        if system == "Windows":
            appdata = os.environ.get("APPDATA")
            if appdata:
                config_path = os.path.join(appdata, "Claude", "claude_desktop_config.json")
        elif system == "Darwin":  # macOS
            home = os.path.expanduser("~")
            config_path = os.path.join(home, "Library", "Application Support", "Claude", "claude_desktop_config.json")
        elif system == "Linux":
            home = os.path.expanduser("~")
            config_path = os.path.join(home, ".config", "Claude", "claude_desktop_config.json")
        
        if config_path and os.path.exists(config_path):
            self.config_path.set(config_path)
            self.claude_status_label.config(text=f"Claude Desktop detected. Config: {config_path}")
            self.claude_config_status_label.config(text=f"Claude Desktop detected. Config: {config_path}")
        else:
            self.claude_status_label.config(text="Claude Desktop not found. Please specify the config path manually.")
            self.claude_config_status_label.config(text="Claude Desktop not found. Please specify the config path manually.")
    
    def load_config(self):
        """Load configuration from Claude Desktop config file"""
        config_path = self.config_path.get()
        if not config_path or not os.path.exists(config_path):
            return
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Check if AI Dev Toolkit is in the mcpServers section
            if "mcpServers" in config:
                has_integrated = "integrated-server" in config["mcpServers"]
                has_legacy_ai_librarian = "ai-librarian" in config["mcpServers"]
                has_legacy_file_system = "file-system-tools" in config["mcpServers"]
                
                self.ai_dev_toolkit_server_enabled.set(has_integrated or has_legacy_ai_librarian or has_legacy_file_system)
                
                # Load allowed directories from args
                # Clear existing project dirs to avoid duplication
                self.project_dirs = []
                
                # Load from AI Librarian server if present
                if has_legacy_ai_librarian and "args" in config["mcpServers"]["ai-librarian"]:
                    args = config["mcpServers"]["ai-librarian"]["args"]
                    # Skip the first item which is the script path
                    dir_paths = args[1:] if len(args) > 1 else []
                    
                    # Filter existing directories and add to project list
                    for dir_path in dir_paths:
                        if os.path.exists(dir_path) and dir_path not in self.project_dirs:
                            self.project_dirs.append(dir_path)
                            self.project_enabled[dir_path] = True
                
                # Load from integrated server if present
                elif has_integrated and "args" in config["mcpServers"]["integrated-server"]:
                    args = config["mcpServers"]["integrated-server"]["args"]
                    # Skip the first item which is the script path
                    dir_paths = args[1:] if len(args) > 1 else []
                    
                    # Filter existing directories and add to project list
                    for dir_path in dir_paths:
                        if os.path.exists(dir_path) and dir_path not in self.project_dirs:
                            self.project_dirs.append(dir_path)
                            self.project_enabled[dir_path] = True
                            
                # Update project displays
                self.update_projects_list()
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load configuration: {str(e)}")
            print(f"Error loading config: {str(e)}")
    
    def scan_for_projects(self):
        """Scan authorized directories for .ai_reference folders to find existing projects"""
        # Implement scan for projects logic here
        pass
    
    def update_server_config_type(self):
        """Update server configuration type information"""
        if self.server_config_type.get() == "npm":
            self.npm_config_note.pack(fill=tk.X, pady=(0, 5))
            if hasattr(self, 'uv_config_note'):
                self.uv_config_note.pack_forget()
        else:
            if hasattr(self, 'npm_config_note'):
                self.npm_config_note.pack_forget()
            self.uv_config_note.pack(fill=tk.X, pady=(0, 5))
    
    def restart_server(self):
        """Restart the MCP server process"""
        # Implement server restart logic here
        pass
    
    def clear_request_queue(self):
        """Clear the request queue for the MCP server"""
        # Implement request queue clearing logic here
        pass
    
    def filter_server_log(self):
        """Filter server log to show only relevant entries"""
        # Implement log filtering logic here
        pass
    
    def restart_claude_desktop(self):
        """Restart the Claude Desktop application"""
        # Implement Claude Desktop restart logic here
        pass
    
    def open_claude_directory(self):
        """Open Claude Desktop directory in file explorer"""
        # Implement directory opening logic here
        pass
    
    def generate_integrated_server_config(self):
        """Generate the configuration for the integrated server that matches the working ai-librarian pattern"""
        # Get the project root directory
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Get enabled directories
        enabled_dirs = [d for d in self.project_dirs if self.project_enabled.get(d, True)]
        
        # Use the EXACT working pattern from ai-librarian:
        server_config = {
            "command": "python",
            "args": [
                os.path.join(project_root, "aitoolkit", "librarian", "server.py")
            ] + enabled_dirs
        }
        
        return server_config
    
    def apply_claude_config(self):
        """Apply changes to Claude Desktop configuration file"""
        config_path = self.config_path.get()
        if not config_path:
            messagebox.showinfo("No Config", "No Claude Desktop configuration file specified.")
            return
        
        try:
            # Read existing config
            config = {}
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            # Ensure mcpServers section exists
            if "mcpServers" not in config:
                config["mcpServers"] = {}
            
            # Remove previous servers if they exist
            for old_server in ["integrated-server", "ai-librarian", "file-system-tools"]:
                if old_server in config["mcpServers"]:
                    del config["mcpServers"][old_server]
            
            # Add our server using the EXACT working pattern from ai-librarian
            if self.ai_dev_toolkit_server_enabled.get():
                server_config = self.generate_integrated_server_config()
                config["mcpServers"]["ai-librarian"] = server_config
            
            # Save the config
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            self.project_message_var.set("Configuration saved successfully! You may need to restart Claude Desktop.")
            self.has_changes = False
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
            print(f"Error saving config: {str(e)}")
    
    def apply_and_exit(self):
        """Apply changes and exit the application"""
        self.apply_claude_config()
        self.root.quit()
    
    def discard_and_exit(self):
        """Discard changes and exit the application"""
        if self.has_changes:
            if not messagebox.askyesno("Confirm", "You have unsaved changes. Are you sure you want to exit without saving?"):
                return
        self.root.quit()
    
    def on_closing(self):
        """Handle window close event"""
        if self.has_changes:
            response = messagebox.askyesnocancel("Unsaved Changes", 
                "You have unsaved changes. Would you like to save them before exiting?")
            
            if response is None:  # Cancel was clicked
                return
            elif response:  # Yes was clicked
                self.apply_claude_config()
        
        # Stop the server if it's running
        if hasattr(self, 'server_process') and self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except:
                pass
        
        self.root.destroy()