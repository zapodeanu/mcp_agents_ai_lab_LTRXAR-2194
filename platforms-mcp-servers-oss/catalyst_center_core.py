#!/usr/bin/env python3
"""
Catalyst Center FastMCP core: self-contained declarative Catalyst logic and FastMCP builder.

Supported wrapper integration path: `build_catalyst_center_fastmcp()` (used by
`catalyst_center_stdio.py` and `catalyst_center_remote.py`).
"""

import asyncio
import json
import os
import yaml
import httpx
import logging
import sys
import base64
import pickle
import numpy as np

from datetime import datetime, timedelta
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, Tool, TextContent
from pathlib import Path
import keyword
import re
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from logging_config import configure_server_logging


# Repository root for loading local resources and env.
PATH = os.path.dirname(os.path.abspath(__file__))

# Embedding assets root (model + vector cache).
EMBEDDINGS_ASSETS_DIR = Path(PATH) / "embeddings_assets"

# Local embedding model directory used to avoid repeated remote downloads.
MODEL_DIR = EMBEDDINGS_ASSETS_DIR / "model" / "all-MiniLM-L6-v2"

# Load the lab-wide environment file. Existing process variables take
# precedence because python-dotenv does not override them by default.
LAB_ENV_PATH = Path(os.environ.get("LAB_ENV", Path.home() / "lab.env"))
load_dotenv(LAB_ENV_PATH)

# Catalyst Center access
CC_USER = os.getenv('CC_USER')
CC_PASS = os.getenv('CC_PASS')
USER_AGENT = "gz-mcp"

configure_server_logging("catalyst", "catalyst_center_core")

logging.info("=" * 80)
logging.info("Catalyst Center MCP Server with Complete API Explorer Started")
logging.info("Process ID: %s", os.getpid())
logging.info("=" * 80)


class CatalystCenterTokenManager:
    """Manages authentication tokens for Catalyst Center"""

    def __init__(self, base_url: str, username: str, password: str):
        """Store credentials and initialize token cache state."""
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None
        self.token_expires = None

    async def get_valid_token(self) -> str:
        """Get a valid token, refreshing if necessary"""
        if self.token and self.token_expires and datetime.now() < self.token_expires:
            return self.token
        return await self._get_new_token()

    async def _get_new_token(self) -> str:
        """Get a new authentication token from Catalyst Center"""
        try:
            url = f"{self.base_url}/dna/system/api/v1/auth/token"
            credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()

            headers = {
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT
            }

            # SECURITY NOTE: TLS verification is disabled here for lab/self-signed
            # Catalyst deployments. Use trusted certificates in production.
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                response = await client.post(url, headers=headers)

                if response.status_code == 200:
                    result = response.json()
                    self.token = result.get('Token')
                    if self.token:
                        self.token_expires = datetime.now() + timedelta(hours=1)
                        return self.token
                    else:
                        raise Exception("No token found in authentication response")
                else:
                    raise Exception(f"Authentication failed: {response.status_code} - {response.text}")

        except Exception as e:
            error_msg = f"Token generation failed: {str(e)}"
            logging.error(error_msg)
            raise Exception(error_msg)


class CatalystAPIExplorer:
    """Cosine similarity-based API exploration using sentence transformers"""

    def __init__(self, swagger_file_path: str, cache_dir: str = None):
        """Initialize explorer state and warm embeddings from cache or OpenAPI data."""
        self.swagger_file_path = swagger_file_path
        self.cache_dir = cache_dir or str(EMBEDDINGS_ASSETS_DIR)
        self.model = None
        self.embeddings_data = []
        self._initialize()

    def _initialize(self):
        """Initialize the sentence transformer model and load/build embeddings"""
        logging.info("Initializing cosine similarity API explorer...")

        # Load sentence transformer model from the local model directory.
        try:
            self.model = SentenceTransformer(
                str(MODEL_DIR),
                local_files_only=True,
            )
            logging.info(f"Sentence transformer model loaded from local path: {MODEL_DIR}")
        except Exception as e:
            logging.error(f"Failed to load sentence transformer from local path: {e}")
            return

        # Load or build embeddings
        self._load_or_build_embeddings()

    def _load_or_build_embeddings(self):
        """Load cached embeddings or build new ones"""
        os.makedirs(self.cache_dir, exist_ok=True)

        # Check if swagger file exists
        if not os.path.exists(self.swagger_file_path):
            logging.error(f"Swagger file not found: {self.swagger_file_path}")
            return

        # Create cache filename based on swagger file modification time
        swagger_mtime = os.path.getmtime(self.swagger_file_path)
        cache_file = f"{self.cache_dir}/catalyst_embeddings_{int(swagger_mtime)}.pkl"

        if os.path.exists(cache_file):
            logging.info(f"Loading cached embeddings from: {cache_file}")
            try:
                with open(cache_file, 'rb') as f:
                    self.embeddings_data = pickle.load(f)
                logging.info(f"Loaded {len(self.embeddings_data)} cached embeddings")
                return
            except Exception as e:
                logging.warning(f"Failed to load cached embeddings: {e}")

        # Build new embeddings
        logging.info("Building new embeddings from swagger file...")
        self._build_embeddings(cache_file)

    def _build_embeddings(self, cache_file: str):
        """Build embeddings from swagger specification"""
        try:
            with open(self.swagger_file_path, 'r') as f:
                swagger_spec = json.load(f)
            paths = swagger_spec.get('paths', {})
            self.embeddings_data = []

            for path, path_spec in paths.items():
                for method, operation_spec in path_spec.items():
                    if method.lower() in ['get', 'post', 'put', 'delete', 'patch']:
                        # Create rich text for embedding
                        summary = operation_spec.get('summary', '')
                        description = operation_spec.get('description', '')
                        tags = ' '.join(operation_spec.get('tags', []))

                        # Combine multiple text sources for richer embeddings
                        embedding_text = f"{summary} {description} {path} {tags}"

                        # Generate embedding
                        embedding = self.model.encode(embedding_text)

                        # Store with metadata
                        self.embeddings_data.append({
                            'embedding': embedding,
                            'metadata': {
                                'path': path,
                                'method': method.upper(),
                                'endpoint_id': f"{method.upper()}:{path}",
                                'summary': summary,
                                'description': description,
                                'tags': operation_spec.get('tags', []),
                                'operation_id': operation_spec.get('operationId', ''),
                                'parameters': operation_spec.get('parameters', []),
                                'category': self._categorize_endpoint(path, operation_spec),
                                'embedding_text': embedding_text
                            }
                        })

            # Cache the embeddings
            try:
                with open(cache_file, 'wb') as f:
                    pickle.dump(self.embeddings_data, f)
                logging.info(f"Cached {len(self.embeddings_data)} embeddings to: {cache_file}")
            except Exception as e:
                logging.warning(f"Failed to cache embeddings: {e}")

            logging.info(f"Built {len(self.embeddings_data)} embeddings")

        except Exception as e:
            logging.error(f"Failed to build embeddings: {e}")

    def _categorize_endpoint(self, path: str, operation_spec: dict):
        """Categorize API endpoint based on path and operation"""
        path_lower = path.lower()

        if any(keyword in path_lower for keyword in ['site', 'device', 'topology', 'compliance', 'inventory']):
            return 'inventory'
        elif any(keyword in path_lower for keyword in ['issue', 'client', 'interface', 'health', 'assurance']):
            return 'assurance'
        elif any(keyword in path_lower for keyword in ['task', 'command', 'execute', 'job', 'file']):
            return 'operations'
        elif any(keyword in path_lower for keyword in ['system', 'auth', 'user', 'setting']):
            return 'administration'
        else:
            return 'general'

    def search_endpoints(self, query: str, category: str = None, method: str = None, limit: int = 20):
        """Search for API endpoints using cosine similarity"""
        if not self.model or not self.embeddings_data:
            logging.error("Embeddings not initialized")
            return []

        try:
            # Generate query embedding
            query_embedding = self.model.encode(query)

            # Calculate similarities
            similarities = []
            for item in self.embeddings_data:
                # Apply filters
                metadata = item['metadata']
                if category and metadata['category'] != category.lower():
                    continue
                if method and metadata['method'] != method.upper():
                    continue

                # Calculate cosine similarity
                similarity = cosine_similarity(
                    query_embedding.reshape(1, -1),
                    item['embedding'].reshape(1, -1)
                )[0][0]

                similarities.append({
                    'similarity_score': float(similarity),
                    'metadata': metadata
                })

            # Sort by similarity and return top results
            similarities.sort(key=lambda x: x['similarity_score'], reverse=True)
            return similarities[:limit]

        except Exception as e:
            logging.error(f"Search failed: {e}")
            return []

    def get_endpoint_info(self, path: str, method: str = 'GET'):
        """Get detailed information about a specific endpoint"""
        endpoint_id = f"{method.upper()}:{path}"

        for item in self.embeddings_data:
            if item['metadata']['endpoint_id'] == endpoint_id:
                return item['metadata']

        return None


class ExplorerAnalytics:
    """Analytics manager for API explorer tracking"""

    def __init__(self, analytics_file_path: str):
        """Initialize analytics storage and load persisted call history."""
        self.analytics_file = analytics_file_path
        self.explorer_analytics = {
            "successful_calls": [],
            "failed_calls": [],
            "call_count": 0,
            "success_rate": 0.0
        }
        self._load_analytics()

    def _load_analytics(self):
        """Load existing analytics data from file"""
        try:
            if os.path.exists(self.analytics_file):
                with open(self.analytics_file, 'r') as f:
                    self.explorer_analytics = json.load(f)
                logging.info(
                    f"Loaded existing explorer analytics: {len(self.explorer_analytics.get('successful_calls', []))} successful calls")
        except Exception as e:
            logging.warning(f"Could not load explorer analytics file: {e}")

    def _save_analytics(self):
        """Save analytics data to file"""
        try:
            # Calculate success rate
            total_calls = len(self.explorer_analytics['successful_calls']) + len(
                self.explorer_analytics['failed_calls'])
            if total_calls > 0:
                self.explorer_analytics['success_rate'] = len(
                    self.explorer_analytics['successful_calls']) / total_calls

            self.explorer_analytics['call_count'] = total_calls

            with open(self.analytics_file, 'w') as f:
                json.dump(self.explorer_analytics, f, indent=2, default=str)
        except Exception as e:
            logging.error(f"Could not save explorer analytics: {e}")

    def _record_explorer_call(self, path: str, method: str, parameters: dict, success: bool, response_data=None,
                              error_message=None):
        """Record an explorer API call for analytics"""
        timestamp = datetime.now().isoformat()

        call_record = {
            "timestamp": timestamp,
            "path": path,
            "method": method,
            "parameters": parameters,
            "endpoint_id": f"{method}:{path}"
        }

        if success:
            call_record.update({
                "status": "success",
                "response_size": len(json.dumps(response_data)) if response_data else 0,
                "data_returned": bool(response_data)
            })
            self.explorer_analytics['successful_calls'].append(call_record)
            logging.info(f"Explorer analytics: {method} {path} - SUCCESS")
        else:
            call_record.update({
                "status": "failed",
                "error": error_message
            })
            self.explorer_analytics['failed_calls'].append(call_record)
            logging.info(f"Explorer analytics: {method} {path} - FAILED: {error_message}")

        # Save analytics after each call
        self._save_analytics()

    def _get_catalyst_explorer_analytics(self):
        """Get analytics summary for popular endpoints"""
        successful_calls = self.explorer_analytics.get('successful_calls', [])

        # Count calls by endpoint
        endpoint_stats = {}
        for call in successful_calls:
            endpoint_id = call.get('endpoint_id')
            if endpoint_id not in endpoint_stats:
                endpoint_stats[endpoint_id] = {
                    "path": call.get('path'),
                    "method": call.get('method'),
                    "call_count": 0,
                    "last_used": call.get('timestamp'),
                    "avg_response_size": 0
                }

            endpoint_stats[endpoint_id]["call_count"] += 1
            endpoint_stats[endpoint_id]["last_used"] = max(endpoint_stats[endpoint_id]["last_used"],
                                                           call.get('timestamp'))

        # Sort by popularity
        popular_endpoints = sorted(endpoint_stats.items(), key=lambda x: x[1]["call_count"], reverse=True)

        return {
            "total_successful_calls": len(successful_calls),
            "total_failed_calls": len(self.explorer_analytics.get('failed_calls', [])),
            "success_rate": self.explorer_analytics.get('success_rate', 0.0),
            "unique_successful_endpoints": len(endpoint_stats),
            "most_popular_endpoints": popular_endpoints[:10],
            "candidates_for_yaml_promotion": [ep for ep in popular_endpoints[:5] if ep[1]["call_count"] >= 3]
        }


class CatalystClusterManager:
    """Simple manager for reading Catalyst Center clusters"""

    def __init__(self, clusters_config_path: str, username: str, password: str):
        """Initialize cluster config paths, credentials, and token managers."""
        self.clusters_config_path = clusters_config_path
        self.username = username
        self.password = password
        self.clusters = {}
        self.token_managers = {}
        self._load_clusters()

    def _load_clusters(self):
        """Load cluster configuration from YAML file"""
        logging.info("Loading Catalyst Center clusters configuration...")

        if not os.path.exists(self.clusters_config_path):
            raise FileNotFoundError(f"Clusters config file not found: {self.clusters_config_path}")

        try:
            with open(self.clusters_config_path, 'r') as f:
                config = yaml.safe_load(f)

            if 'catalyst_centers' not in config:
                raise ValueError("Clusters config must include 'catalyst_centers' section")

            for cluster_config in config['catalyst_centers']:
                cluster_name = cluster_config.get('name')
                cluster_host = cluster_config.get('host')
                cluster_enabled = cluster_config.get('enabled', True)

                if not cluster_name or not cluster_host or not cluster_enabled:
                    continue

                self.clusters[cluster_name] = {
                    'name': cluster_name,
                    'host': cluster_host,
                    'base_url': f"https://{cluster_host}",
                    'enabled': cluster_enabled
                }

                self.token_managers[cluster_name] = CatalystCenterTokenManager(
                    f"https://{cluster_host}",
                    self.username,
                    self.password
                )

            if not self.clusters:
                raise ValueError(
                    "No enabled Catalyst Center clusters found in catalyst_center_clusters.yaml"
                )

            logging.info(f"Successfully loaded {len(self.clusters)} clusters")

        except Exception as e:
            logging.error(f"Failed to load clusters config: {e}")
            raise

    def get_clusters(self) -> dict:
        """Return enabled cluster metadata loaded from YAML configuration."""
        return self.clusters

    def get_cluster_names(self) -> list:
        """Return all enabled cluster names."""
        return list(self.clusters.keys())

    def get_token_manager(self, cluster_name: str) -> CatalystCenterTokenManager:
        """Return token manager for a cluster, or None when cluster is unknown."""
        return self.token_managers.get(cluster_name)


class CatalystCenterMcpServer:
    """Catalyst Center MCP server core that loads config, tools, and explorer services."""

    def __init__(self):
        """Initialize server dependencies, validate startup config, and register tools."""
        logging.info("Initializing Catalyst Center MCP Server...")

        self.server = Server("catalyst-center-mcp")

        # Initialize credentials
        self.username = CC_USER
        self.password = CC_PASS

        self.clusters_config_path = os.path.join(PATH, "Resources/catalyst_center_clusters.yaml")
        self.tools_config_path = os.path.join(PATH, "Resources/catalyst_center_tools.yaml")
        self.swagger_file_path = os.path.join(PATH, "Resources/catalyst_center_openapi.json")
        self.validate_startup_config()

        # Initialize analytics tracking with new naming
        self.analytics_file = f"{PATH}/logs/catalyst_center_mcp_explorer_analytics.json"
        self.analytics_manager = ExplorerAnalytics(self.analytics_file)

        # Initialize managers
        self.cluster_manager = CatalystClusterManager(self.clusters_config_path, self.username, self.password)
        if not self.cluster_manager.get_clusters():
            raise ValueError("No Catalyst Center clusters configured. Check Resources/catalyst_center_clusters.yaml")
        first_cluster = next(iter(self.cluster_manager.get_clusters().values()))
        self.cc_url = first_cluster["base_url"]
        self.token_manager = CatalystCenterTokenManager(
            self.cc_url, self.username, self.password
        )

        # Load configuration
        self.config = self._load_config()

        # Initialize API explorer at startup so failures are visible immediately in logs.
        self.api_explorer = CatalystAPIExplorer(self.swagger_file_path)

        # Build YAML endpoint lookup for filtering
        self.yaml_endpoints = self._build_yaml_endpoint_lookup()

        # Organize tools by category
        self.tool_categories = self._organize_tools_by_category()

        self._setup()
        logging.info("Catalyst Center MCP Server ready!")

    def validate_startup_config(self):
        """Validate startup configuration before initializing server dependencies."""
        errors = []

        # Validate required env vars.
        missing_env = [
            env_name
            for env_name, env_value in (
                ("CC_USER", self.username),
                ("CC_PASS", self.password),
            )
            if not env_value
        ]
        if missing_env:
            errors.append(f"Missing required environment variable(s): {', '.join(missing_env)}")

        # Validate cluster YAML exists and has at least one enabled valid cluster.
        if not os.path.exists(self.clusters_config_path):
            errors.append(f"Missing required file: {self.clusters_config_path}")
        else:
            try:
                with open(self.clusters_config_path, "r", encoding="utf-8") as f:
                    clusters_config = yaml.safe_load(f) or {}
                if not isinstance(clusters_config, dict):
                    errors.append("Clusters config must be a YAML mapping")
                else:
                    clusters = clusters_config.get("catalyst_centers")
                    if not isinstance(clusters, list):
                        errors.append("Clusters config must include 'catalyst_centers' as a list")
                    else:
                        enabled_valid_clusters = [
                            c for c in clusters
                            if isinstance(c, dict)
                            and c.get("enabled", True)
                            and c.get("name")
                            and c.get("host")
                        ]
                        if not enabled_valid_clusters:
                            errors.append(
                                "Clusters config has no enabled valid entries (each requires name + host)"
                            )
            except Exception as exc:
                errors.append(f"Failed to parse clusters config: {exc}")

        # Validate tools YAML exists and has expected structure.
        if not os.path.exists(self.tools_config_path):
            errors.append(f"Missing required file: {self.tools_config_path}")
        else:
            try:
                with open(self.tools_config_path, "r", encoding="utf-8") as f:
                    tools_config = yaml.safe_load(f) or {}
                if not isinstance(tools_config, dict):
                    errors.append("Tools config must be a YAML mapping")
                elif not isinstance(tools_config.get("tools"), list):
                    errors.append("Tools config must include 'tools' as a list")
            except Exception as exc:
                errors.append(f"Failed to parse tools config: {exc}")

        if errors:
            error_report = "Catalyst Center startup config validation failed:\n- " + "\n- ".join(errors)
            logging.error(error_report)
            raise ValueError(error_report)

        logging.info("Catalyst Center startup config validation passed")

    def _ensure_api_explorer(self):
        """Initialize API explorer on demand and verify readiness."""
        if self.api_explorer is None:
            logging.info("Lazy-initializing Catalyst API explorer...")
            self.api_explorer = CatalystAPIExplorer(self.swagger_file_path)

        if not self.api_explorer or not self.api_explorer.model or not self.api_explorer.embeddings_data:
            return False, (
                "Error: Catalyst API explorer is unavailable. "
                "Verify embedding model files and OpenAPI resources, then retry."
            )

        return True, None

    def _load_config(self):
        """Load YAML config"""
        config_path = self.tools_config_path

        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logging.info(f"Loaded config with {len(config.get('tools', []))} declarative tools")
            return config
        else:
            logging.warning("YAML config not found, using minimal default")
            return {
                "base_url": self.cc_url,
                "tools": []
            }

    def _build_yaml_endpoint_lookup(self):
        """Build lookup of endpoints covered by YAML tools"""
        yaml_endpoints = set()
        for tool in self.config.get("tools", []):
            endpoint = tool.get("endpoint", "")
            method = tool.get("method", "GET").upper()
            # Normalize endpoint path
            normalized_path = f"/{endpoint.strip('/')}"
            yaml_endpoints.add(f"{method}:{normalized_path}")
        return yaml_endpoints

    def _organize_tools_by_category(self):
        """Organize tools by category"""
        categories = {}
        for tool in self.config.get("tools", []):
            category = tool.get("category", "uncategorized")
            if category not in categories:
                categories[category] = []
            categories[category].append(tool)
        return categories

    def _setup(self):
        """Setup MCP server handlers"""
        logging.info("Setting up Catalyst Center MCP server handlers...")

        @self.server.list_tools()
        async def list_tools():
            """Generate tools from YAML config plus explorer tools"""
            tools = []

            # Add declarative tools from YAML config
            for tool_config in self.config.get("tools", []):
                try:
                    category = tool_config.get("category", "uncategorized")
                    emoji = {"inventory": "📊", "assurance": "🚨", "operations": "⚙️", "administration": "🔧"}.get(
                        category, "🔧")

                    # Build schema from parameters
                    properties = {}
                    required = []

                    for param_name, param_info in tool_config.get("parameters", {}).items():
                        properties[param_name] = {
                            "type": param_info["type"],
                            "description": param_info["description"]
                        }
                        if param_info.get("required", False):
                            required.append(param_name)

                    tool_description = f"{emoji} [{category.title()}] {tool_config['description']}"

                    tool = Tool(
                        name=tool_config["name"],
                        description=tool_description,
                        inputSchema={
                            "type": "object",
                            "properties": properties,
                            "required": required
                        }
                    )
                    tools.append(tool)

                except Exception as e:
                    logging.error(f"Failed to create tool {tool_config.get('name', 'unknown')}: {e}")

            # Add explorer tools
            explorer_tools = [
                Tool(
                    name="explore_catalyst_api_endpoints",
                    description="🔍 [Explorer] Search Catalyst Center API endpoints using natural language queries",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language description of what you want to do (e.g., 'get network devices', 'site information', 'client status')"
                            },
                            "category": {
                                "type": "string",
                                "description": "Optional category filter: inventory, assurance, operations, administration",
                                "enum": ["inventory", "assurance", "operations", "administration"]
                            },
                            "method": {
                                "type": "string",
                                "description": "Optional HTTP method filter (GET only in OSS mode)",
                                "enum": ["GET"]
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results (default: 10)",
                                "default": 10,
                                "minimum": 1,
                                "maximum": 50
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="execute_catalyst_api_endpoint",
                    description="⚡ [Execute] Execute any Catalyst Center API endpoint dynamically",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "API endpoint path (e.g., '/dna/intent/api/v1/network-device')"
                            },
                            "method": {
                                "type": "string",
                                "description": "HTTP method (GET only in OSS mode)",
                                "enum": ["GET"],
                                "default": "GET"
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Query parameters, path parameters, or request body",
                                "additionalProperties": True
                            },
                            "cluster": {
                                "type": "string",
                                "description": "Cluster name or 'all' for network-wide results (optional)"
                            }
                        },
                        "required": ["path"]
                    }
                ),
                Tool(
                    name="get_catalyst_endpoint_info",
                    description="📋 [Info] Get detailed information about an API endpoint including parameters and usage",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "API endpoint path"
                            },
                            "method": {
                                "type": "string",
                                "description": "HTTP method (GET only in OSS mode)",
                                "enum": ["GET"],
                                "default": "GET"
                            }
                        },
                        "required": ["path"]
                    }
                ),
                Tool(
                    name="get_catalyst_explorer_analytics",
                    description="📈 [Analytics] Get Catalyst explorer analytics data for explored Catalyst API endpoints showing usage patterns and success rates",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "detailed": {
                                "type": "boolean",
                                "description": "Include detailed call history (default: false)",
                                "default": False
                            }
                        },
                        "required": []
                    }
                )
            ]

            tools.extend(explorer_tools)

            logging.info(
                f"Created {len(tools)} total tools ({len(self.config.get('tools', []))} declarative + {len(explorer_tools)} explorer)")
            return tools

        @self.server.list_resources()
        async def list_resources():
            return []

        @self.server.list_prompts()
        async def list_prompts():
            return []

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            """Handle tool calls for both declarative and explorer tools"""
            logging.info(f"Executing tool: {name}")

            try:
                # Handle explorer tools
                if name == "explore_catalyst_api_endpoints":
                    return await self._handle_cosine_search(arguments)
                elif name == "execute_catalyst_api_endpoint":
                    return await self._handle_execute_explored_endpoint(arguments)
                elif name == "get_catalyst_endpoint_info":
                    return await self._handle_get_endpoint_info(arguments)
                elif name == "get_catalyst_explorer_analytics":
                    return await self._handle_get_analytics(arguments)

                # Handle declarative tools
                return await self._handle_declarative_tool(name, arguments)

            except Exception as e:
                logging.error(f"Error executing {name}: {e}")
                return {'content': [{'type': 'text', 'text': f'Error: {str(e)}'}]}

        logging.info("Catalyst Center MCP server handlers registered")

    async def _handle_cosine_search(self, arguments: dict):
        """API explorer search for complete API coverage - endpoints not already exposed as YAML tools"""
        explorer_ready, explorer_error = self._ensure_api_explorer()
        if not explorer_ready:
            return {'content': [{'type': 'text', 'text': explorer_error}]}

        query = arguments.get('query', '')
        category = arguments.get('category')
        method = arguments.get('method')
        limit = arguments.get('limit', 10)
        min_similarity = arguments.get('min_similarity', 0.45)

        logging.info(f"API explorer search for complete endpoints: '{query}' (min_similarity: {min_similarity})")

        # Get all cosine similarity results
        all_explored_results = self.api_explorer.search_endpoints(query, category, method, limit * 2)

        # Filter OUT endpoints already covered by YAML tools AND below similarity threshold
        complete_endpoints = []
        yaml_covered_endpoints = []

        for result in all_explored_results:
            metadata = result['metadata']

            # Apply minimum similarity filter
            if result['similarity_score'] < min_similarity:
                continue

            # Check if this endpoint is already covered by a YAML tool
            yaml_equivalent = self._find_yaml_equivalent(metadata['path'], metadata['method'])

            if yaml_equivalent:
                yaml_covered_endpoints.append({
                    "explored_path": metadata['path'],
                    "explored_method": metadata['method'],
                    "yaml_tool": yaml_equivalent['tool_name'],
                    "similarity_score": round(result['similarity_score'], 3),
                    "note": f"Already available as tool: {yaml_equivalent['tool_name']}"
                })
            else:
                complete_endpoints.append({
                    "path": metadata['path'],
                    "method": metadata['method'],
                    "summary": metadata['summary'],
                    "description": metadata['description'],
                    "similarity_score": round(result['similarity_score'], 3),
                    "category": metadata['category'],
                    "tags": metadata['tags'],
                    "status": "explored",
                    "usage": f"execute_catalyst_api_endpoint with path: {metadata['path']}"
                })

        # Limit complete endpoints to requested limit
        complete_endpoints = complete_endpoints[:limit]

        search_results = {
            "query": query,
            "search_purpose": "explore_complete_api_coverage",
            "note": "YAML tools are already available to client via list_tools()",
            "filters_applied": {
                "category": category,
                "method": method,
                "limit": limit,
                "min_similarity": min_similarity
            },
            "summary": {
                "complete_endpoints_found": len(complete_endpoints),
                "yaml_covered_endpoints": len(yaml_covered_endpoints),
                "total_searched": len(all_explored_results)
            },
            "explored_endpoints": complete_endpoints,
            "already_available": {
                "description": "These endpoints are already exposed as YAML tools",
                "count": len(yaml_covered_endpoints),
                "examples": yaml_covered_endpoints[:5]  # Show first 5 as examples
            },
            "recommendations": self._generate_explorer_recommendations(complete_endpoints, yaml_covered_endpoints)
        }

        return {'content': [{'type': 'text', 'text': json.dumps(search_results, indent=2)}]}

    def _find_yaml_equivalent(self, path: str, method: str):
        """Find if an explored endpoint has a YAML tool equivalent"""
        normalized_path = f"/{path.strip('/')}"

        for tool in self.config.get("tools", []):
            tool_path = f"/{tool.get('endpoint', '').strip('/')}"
            tool_method = tool.get('method', 'GET').upper()

            if tool_path == normalized_path and tool_method == method.upper():
                return {
                    "tool_name": tool["name"],
                    "description": tool["description"]
                }

        return None

    def _generate_explorer_recommendations(self, complete_endpoints, yaml_covered):
        """Generate recommendations focused on exploration value"""
        recommendations = []

        if complete_endpoints:
            high_value_endpoints = [ep for ep in complete_endpoints if ep['similarity_score'] > 0.8]

            if high_value_endpoints:
                recommendations.append({
                    "type": "high_value_exploration",
                    "message": f"Found {len(high_value_endpoints)} highly relevant endpoints for complete coverage",
                    "suggestion": "These might be valuable additions to your YAML tool configuration",
                    "candidates": [ep['path'] for ep in high_value_endpoints[:3]]
                })

            if len(complete_endpoints) > 5:
                recommendations.append({
                    "type": "extensive_exploration",
                    "message": f"Explored {len(complete_endpoints)} endpoints for complete API coverage",
                    "suggestion": "Consider exploring these with execute_catalyst_api_endpoint to evaluate their utility"
                })

        if yaml_covered:
            recommendations.append({
                "type": "existing_coverage",
                "message": f"{len(yaml_covered)} relevant endpoints are already available as tools",
                "suggestion": "Use the existing YAML tools which have proper parameter validation and error handling"
            })

        if not complete_endpoints and not yaml_covered:
            recommendations.append({
                "type": "no_exploration",
                "message": "No matching endpoints found",
                "suggestion": "Try broader search terms or explore related functionality"
            })

        return recommendations

    async def _handle_get_endpoint_info(self, arguments: dict):
        """Handle endpoint info requests"""
        explorer_ready, explorer_error = self._ensure_api_explorer()
        if not explorer_ready:
            return {'content': [{'type': 'text', 'text': explorer_error}]}

        path = arguments.get('path', '')
        method = arguments.get('method', 'GET').upper()
        if method != "GET":
            return {'content': [{'type': 'text', 'text': "Only GET method is allowed in OSS API explorer mode."}]}

        endpoint_info = self.api_explorer.get_endpoint_info(path, method)

        if not endpoint_info:
            return {'content': [{'type': 'text', 'text': f'Endpoint not found: {method} {path}'}]}

        return {'content': [{'type': 'text', 'text': json.dumps(endpoint_info, indent=2)}]}

    async def _handle_get_analytics(self, arguments: dict):
        """Handle explorer analytics reporting requests"""
        detailed = arguments.get('detailed', False)

        analytics_summary = self.analytics_manager._get_catalyst_explorer_analytics()

        if detailed:
            # Include full call history
            analytics_summary["recent_successful_calls"] = self.analytics_manager.explorer_analytics.get(
                'successful_calls', [])[-20:]  # Last 20
            analytics_summary["recent_failed_calls"] = self.analytics_manager.explorer_analytics.get('failed_calls',
                                                                                                     [])[
                                                       -10:]  # Last 10

        return {'content': [{'type': 'text', 'text': json.dumps(analytics_summary, indent=2)}]}

    async def _handle_execute_explored_endpoint(self, arguments: dict):
        """Execute an explored API endpoint with analytics tracking"""
        explorer_ready, explorer_error = self._ensure_api_explorer()
        if not explorer_ready:
            return {'content': [{'type': 'text', 'text': explorer_error}]}

        path = arguments.get('path', '')
        method = arguments.get('method', 'GET').upper()
        if method != "GET":
            return {'content': [{'type': 'text', 'text': "Only GET method is allowed in OSS API explorer mode."}]}
        parameters = arguments.get('parameters', {})
        cluster = arguments.get('cluster')

        logging.info(f"Executing explored endpoint: {method} {path}")

        # Check if this endpoint is covered by an existing YAML tool
        yaml_equivalent = self._find_yaml_equivalent(path, method)

        if yaml_equivalent:
            warning_message = {
                "warning": "Endpoint covered by existing YAML tool",
                "recommendation": f"Use existing tool: {yaml_equivalent['tool_name']}",
                "yaml_tool_info": yaml_equivalent,
                "execution_result": "Proceeding with dynamic execution, but consider using the YAML tool instead"
            }

            # Still execute but include the warning
            execution_result = await self._execute_on_clusters_with_analytics(path, method, parameters, cluster)

            # Merge warning with execution result
            if isinstance(execution_result.get('content', [{}])[0].get('text'), str):
                result_data = json.loads(execution_result['content'][0]['text'])
                result_data['yaml_tool_warning'] = warning_message
                execution_result['content'][0]['text'] = json.dumps(result_data, indent=2)

            return execution_result

        # Proceed with normal dynamic execution with analytics
        return await self._execute_on_clusters_with_analytics(path, method, parameters, cluster)

    async def _execute_on_clusters_with_analytics(self, path: str, method: str, parameters: dict, cluster_param: str):
        """Execute API call on specified clusters with analytics tracking"""
        # Handle cluster selection
        available_clusters = self.cluster_manager.get_clusters()

        if not available_clusters:
            return {
                'content': [{
                    'type': 'text',
                    'text': 'Error: No Catalyst Center clusters configured. Check Resources/catalyst_center_clusters.yaml'
                }]
            }
        elif cluster_param and cluster_param.lower() == 'all':
            target_clusters = list(available_clusters.values())
        elif cluster_param and cluster_param.lower() in [c.lower() for c in available_clusters.keys()]:
            cluster_name = next(c for c in available_clusters.keys() if c.lower() == cluster_param.lower())
            target_clusters = [available_clusters[cluster_name]]
        else:
            target_clusters = [list(available_clusters.values())[0]]

        all_results = []
        analytics_success = False
        analytics_error = None
        analytics_response_data = None

        for cluster in target_clusters:
            cluster_name = cluster['name']

            try:
                # Get authentication token
                if cluster_name in self.cluster_manager.token_managers:
                    token_manager = self.cluster_manager.get_token_manager(cluster_name)
                    token = await token_manager.get_valid_token()
                else:
                    token = await self.token_manager.get_valid_token()

                # Build URL
                url = f"{cluster['base_url']}/{path.lstrip('/')}"

                # Handle path parameters
                for param_name, param_value in parameters.items():
                    if f"{{{param_name}}}" in url:
                        url = url.replace(f"{{{param_name}}}", str(param_value))

                # Separate query and body parameters
                query_params = {k: v for k, v in parameters.items() if f"{{{k}}}" not in path}

                headers = {
                    "X-Auth-Token": token,
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT
                }

                # SECURITY NOTE: TLS verification is disabled here for lab/self-signed
                # Catalyst deployments. Use trusted certificates in production.
                async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                    response = await client.get(url, headers=headers, params=query_params)

                    if response.status_code in [200, 201, 202]:
                        result = response.json() if response.text else {"status": "success"}
                        cluster_result = {
                            "cluster_info": {
                                "name": cluster_name,
                                "host": cluster.get('host', 'localhost')
                            },
                            "data": result
                        }
                        all_results.append(cluster_result)

                        # Mark as successful for analytics
                        analytics_success = True
                        analytics_response_data = result
                    else:
                        error_msg = f"API request failed: {response.status_code} - {response.text}"
                        error_result = {
                            "cluster_info": {"name": cluster_name},
                            "error": error_msg
                        }
                        all_results.append(error_result)

                        # Record error for analytics
                        if not analytics_error:  # Only record first error
                            analytics_error = error_msg

            except Exception as e:
                error_msg = f"Execution error: {str(e)}"
                error_result = {
                    "cluster_info": {"name": cluster_name},
                    "error": error_msg
                }
                all_results.append(error_result)

                # Record error for analytics
                if not analytics_error:  # Only record first error
                    analytics_error = error_msg

        # Record analytics for this explorer call
        self.analytics_manager._record_explorer_call(
            path=path,
            method=method,
            parameters=parameters,
            success=analytics_success,
            response_data=analytics_response_data,
            error_message=analytics_error
        )

        # Format response
        if len(target_clusters) == 1:
            final_result = all_results[0] if all_results else {"error": "No results"}
        else:
            final_result = {
                "network_wide_query": True,
                "total_clusters_queried": len(target_clusters),
                "results": all_results
            }

        return {'content': [{'type': 'text', 'text': json.dumps(final_result, indent=2)}]}

    async def _handle_declarative_tool(self, name: str, arguments: dict):
        """Handle declarative tools from YAML config"""
        # Find tool config
        tool_config = None
        for tool in self.config.get("tools", []):
            if tool["name"] == name:
                tool_config = tool
                break

        if not tool_config:
            return {'content': [{'type': 'text', 'text': f'Unknown declarative tool: {name}'}]}

        # Handle static response tools
        if tool_config.get("static_response"):
            logging.info(f"Returning static response for tool: {name}")
            static_data = tool_config["static_response"]
            return {'content': [{'type': 'text', 'text': json.dumps(static_data, indent=2)}]}

        # Handle special dynamic tools
        if name == "get_clusters":
            logging.info("Returning dynamic cluster information")
            clusters_info = {
                "clusters": self.cluster_manager.get_clusters(),
                "total_clusters": len(self.cluster_manager.get_clusters()),
                "cluster_names": self.cluster_manager.get_cluster_names()
            }
            return {'content': [{'type': 'text', 'text': json.dumps(clusters_info, indent=2)}]}

        # Handle delegator tools (like get_config_changes)
        if tool_config.get("parameters", {}).get("delegate_to"):
            delegate_to_param = tool_config["parameters"]["delegate_to"]
            delegate_target = delegate_to_param.get("value")

            if delegate_target:
                logging.info(f"Delegating {name} to {delegate_target}")

                # Build arguments for the delegate tool
                delegate_args = {"cluster": arguments.get("cluster", "")}

                # Add predefined parameter values from the tool config
                for param_name, param_info in tool_config.get("parameters", {}).items():
                    if "value" in param_info and param_name != "delegate_to":
                        delegate_args[param_name] = param_info["value"]
                        logging.info(f"Using predefined parameter: {param_name}={param_info['value']}")

                # Only add user arguments that don't have predefined values
                predefined_params = {param_name for param_name, param_info in
                                     tool_config.get("parameters", {}).items()
                                     if "value" in param_info}

                for key, value in arguments.items():
                    if key not in ["cluster", "delegate_to"] and key not in predefined_params:
                        delegate_args[key] = value
                        logging.info(f"User parameter: {key}={value}")
                    elif key in predefined_params:
                        logging.info(f"Ignoring user override for: {key} (using predefined value)")

                logging.info(f"Calling {delegate_target} with args: {delegate_args}")
                return await self._handle_declarative_tool(delegate_target, delegate_args)

        # Handle cluster selection
        cluster_param = arguments.get('cluster', '').lower() if arguments.get('cluster') else None
        available_clusters = self.cluster_manager.get_clusters()

        if not available_clusters:
            return {
                'content': [{
                    'type': 'text',
                    'text': 'Error: No Catalyst Center clusters configured. Check Resources/catalyst_center_clusters.yaml'
                }]
            }
        elif cluster_param == 'all':
            target_clusters = list(available_clusters.values())
        elif cluster_param and cluster_param in [c.lower() for c in available_clusters.keys()]:
            cluster_name = next(c for c in available_clusters.keys() if c.lower() == cluster_param)
            target_clusters = [available_clusters[cluster_name]]
        else:
            target_clusters = [list(available_clusters.values())[0]]

        # Remove special parameters from API arguments
        api_arguments = {k: v for k, v in arguments.items()
                         if k not in ['cluster'] and
                         tool_config.get("parameters", {}).get(k, {}).get("location") != "special"}

        # Execute on target clusters
        all_results = []

        for cluster in target_clusters:
            cluster_name = cluster['name']

            try:
                # Get authentication token
                if cluster_name in self.cluster_manager.token_managers:
                    token_manager = self.cluster_manager.get_token_manager(cluster_name)
                    token = await token_manager.get_valid_token()
                else:
                    token = await self.token_manager.get_valid_token()

                # Build URL
                url = f"{cluster['base_url']}/{tool_config['endpoint']}"

                # Replace path parameters
                for param_name, param_info in tool_config.get("parameters", {}).items():
                    if param_info.get("location") == "path" and param_name in api_arguments:
                        url = url.replace(f"{{{param_name}}}", str(api_arguments[param_name]))

                # Build query parameters, body parameters, and header parameters
                query_params = {}
                body_params = {}
                header_params = {}

                for param_name, param_info in tool_config.get("parameters", {}).items():
                    if param_info.get("location") == "query" and param_name in api_arguments:
                        query_params[param_name] = api_arguments[param_name]
                    elif param_info.get("location") == "body" and param_name in api_arguments:
                        body_params[param_name] = api_arguments[param_name]
                    elif param_info.get("location") == "header" and param_name in api_arguments:
                        header_params[param_name] = api_arguments[param_name]

                # Make API call
                headers = {
                    "X-Auth-Token": token,
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT
                }

                # Add custom header parameters
                headers.update(header_params)

                http_method = tool_config.get("method", "GET").upper()

                # SECURITY NOTE: TLS verification is disabled here for lab/self-signed
                # Catalyst deployments. Use trusted certificates in production.
                async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                    if http_method == "POST":
                        if body_params:
                            response = await client.post(url, headers=headers, json=body_params, params=query_params)
                        else:
                            response = await client.post(url, headers=headers, json=query_params)
                    else:
                        response = await client.get(url, headers=headers, params=query_params)

                    if response.status_code in [200, 202]:
                        result = response.json()
                        cluster_result = {
                            "cluster_info": {
                                "name": cluster_name,
                                "host": cluster.get('host', 'localhost')
                            },
                            "data": result
                        }
                        all_results.append(cluster_result)
                    else:
                        raise Exception(f"API request failed: {response.status_code} - {response.text}")

            except Exception as e:
                error_result = {
                    "cluster_info": {"name": cluster_name},
                    "error": f"Error executing {name} on {cluster_name}: {str(e)}"
                }
                all_results.append(error_result)

        # Return results
        if len(target_clusters) == 1:
            final_result = all_results[0] if all_results else {"error": "No results"}
        else:
            final_result = {
                "network_wide_query": True,
                "total_clusters_queried": len(target_clusters),
                "results": all_results
            }

        return {'content': [{'type': 'text', 'text': json.dumps(final_result, indent=2)}]}

    async def run(self):
        """Run the Catalyst Center MCP server"""
        logging.info("Starting Catalyst Center MCP server...")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="catalyst-center-mcp",
                    server_version="2.1.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={}
                    )
                )
            )



def _normalize_param_name(name: str) -> str:
    normalized = re.sub(r"\W+", "_", name).strip("_")
    if not normalized:
        normalized = "param"
    if normalized[0].isdigit():
        normalized = f"p_{normalized}"
    if keyword.iskeyword(normalized):
        normalized = f"{normalized}_arg"
    return normalized


def _extract_result_payload(result: Any) -> Any:
    if not isinstance(result, dict):
        return result

    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and isinstance(first.get("text"), str):
            text = first["text"]
            try:
                return json.loads(text)
            except Exception:
                return text
    return result


def _build_declarative_tool_fn(core: CatalystCenterMcpServer, tool_name: str, params: dict[str, dict[str, Any]]):
    """Build a FastMCP async tool callable from declarative YAML metadata.

    Args:
        core: Catalyst core server instance that executes the tool handler.
        tool_name: Declarative tool name from `Resources/catalyst_center_tools.yaml`.
        params: Parameter schema map used to build runtime type hints and defaults.

    Returns:
        Async callable registered as an MCP tool.

    Side effects:
        Dynamically compiles the callable with `exec` using repository-controlled
        tool metadata and normalized parameter names.
    """
    param_map: list[tuple[str, str]] = []
    for original_name in params.keys():
        safe_name = _normalize_param_name(original_name)
        while any(safe_name == existing for _, existing in param_map):
            safe_name = f"{safe_name}_arg"
        param_map.append((original_name, safe_name))

    def _type_expr(param_info: dict[str, Any]) -> str:
        param_type = str(param_info.get("type", "string")).lower()
        enum_values = param_info.get("enum")
        if isinstance(enum_values, list) and enum_values:
            literal_values = ", ".join(repr(v) for v in enum_values)
            return f"Literal[{literal_values}]"
        return {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "object": "dict[str, Any]",
            "array": "list[Any]",
        }.get(param_type, "Any")

    required_parts: list[str] = []
    optional_parts: list[str] = []
    for original_name, safe_name in param_map:
        param_info = params.get(original_name, {})
        required = bool(param_info.get("required", False))
        type_expr = _type_expr(param_info)

        field_args: list[str] = []
        description = param_info.get("description")
        if isinstance(description, str) and description:
            field_args.append(f"description={description!r}")
        if "minimum" in param_info:
            field_args.append(f"ge={param_info['minimum']!r}")
        if "maximum" in param_info:
            field_args.append(f"le={param_info['maximum']!r}")
        if "minLength" in param_info:
            field_args.append(f"min_length={param_info['minLength']!r}")
        if "maxLength" in param_info:
            field_args.append(f"max_length={param_info['maxLength']!r}")

        field_expr = f"Field({', '.join(field_args)})" if field_args else "Field()"
        annotated_expr = f"Annotated[{type_expr}, {field_expr}]"

        if required:
            required_parts.append(f"{safe_name}: {annotated_expr}")
        else:
            default_value = param_info.get("default", None)
            optional_parts.append(
                f"{safe_name}: Annotated[{type_expr} | None, {field_expr}] = {default_value!r}"
            )

    signature = ", ".join(required_parts + optional_parts)

    src = f"async def _tool({signature}):\n"
    src += "    arguments = {}\n"
    for original, safe in param_map:
        src += f"    if {safe} is not None:\n"
        src += f"        arguments[{original!r}] = {safe}\n"
    src += "    result = await core._handle_declarative_tool(tool_name, arguments)\n"
    src += "    return _extract_result_payload(result)\n"

    namespace = {
        "core": core,
        "tool_name": tool_name,
        "_extract_result_payload": _extract_result_payload,
        "Annotated": Annotated,
        "Literal": Literal,
        "Field": Field,
        "Any": Any,
    }
    exec(src, namespace)
    return namespace["_tool"]


def build_catalyst_center_fastmcp(host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    """Build the Catalyst Center FastMCP application used by stdio/remote wrappers.

    Args:
        host: Listener host used by streamable HTTP transport.
        port: Listener port used by streamable HTTP transport.

    Returns:
        Configured `FastMCP` app with explorer and declarative tools registered.

    Side effects:
        Initializes Catalyst core services, loads resource files, and sets up
        embedding-backed API exploration data during startup.
    """
    core = CatalystCenterMcpServer()
    mcp = FastMCP(name="catalyst-center-mcp", host=host, port=port, streamable_http_path="/mcp")

    @mcp.tool(name="explore_catalyst_api_endpoints", description="Search Catalyst Center API endpoints using natural language queries")
    async def explore_catalyst_api_endpoints(
        query: Annotated[
            str,
            Field(description="Natural language description of what you want to do (e.g., 'get network devices', 'site information', 'client status')"),
        ],
        category: Annotated[
            Literal["inventory", "assurance", "operations", "administration"] | None,
            Field(description="Optional category filter: inventory, assurance, operations, administration"),
        ] = None,
        method: Annotated[
            Literal["GET"] | None,
            Field(description="Optional HTTP method filter (GET only in OSS mode)"),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Maximum number of results (default: 10)", ge=1, le=50),
        ] = 10,
    ):
        result = await core._handle_cosine_search(
            {
                "query": query,
                "category": category,
                "method": method,
                "limit": limit,
            }
        )
        return _extract_result_payload(result)

    @mcp.tool(name="execute_catalyst_api_endpoint", description="Execute any Catalyst Center API endpoint dynamically")
    async def execute_catalyst_api_endpoint(
        path: Annotated[
            str,
            Field(description="API endpoint path (e.g., '/dna/intent/api/v1/network-device')"),
        ],
        method: Annotated[
            Literal["GET"],
            Field(description="HTTP method (GET only in OSS mode)"),
        ] = "GET",
        parameters: Annotated[
            dict[str, Any] | None,
            Field(description="Query parameters, path parameters, or request body"),
        ] = None,
        cluster: Annotated[
            str | None,
            Field(description="Cluster name or 'all' for network-wide results (optional)"),
        ] = None,
    ):
        result = await core._handle_execute_explored_endpoint(
            {
                "path": path,
                "method": method,
                "parameters": parameters or {},
                "cluster": cluster,
            }
        )
        return _extract_result_payload(result)

    @mcp.tool(name="get_catalyst_endpoint_info", description="Get detailed information about a Catalyst endpoint")
    async def get_catalyst_endpoint_info(
        path: Annotated[str, Field(description="API endpoint path")],
        method: Annotated[
            Literal["GET"],
            Field(description="HTTP method (GET only in OSS mode)"),
        ] = "GET",
    ):
        result = await core._handle_get_endpoint_info({"path": path, "method": method})
        return _extract_result_payload(result)

    @mcp.tool(name="get_catalyst_explorer_analytics", description="Get Catalyst explorer analytics data")
    async def get_catalyst_explorer_analytics(
        detailed: Annotated[
            bool,
            Field(description="Include detailed call history (default: false)"),
        ] = False
    ):
        result = await core._handle_get_analytics({"detailed": detailed})
        return _extract_result_payload(result)

    for tool_cfg in core.config.get("tools", []):
        tool_name = tool_cfg.get("name")
        if not tool_name:
            continue
        params = tool_cfg.get("parameters", {})
        fn = _build_declarative_tool_fn(core, tool_name, params)
        mcp.add_tool(fn, name=tool_name, description=tool_cfg.get("description", f"Declarative tool: {tool_name}"))

    logging.getLogger("catalyst_center_fastmcp_adapter").info(
        "FastMCP Catalyst Center initialized with %s tools",
        len(core.config.get("tools", [])) + 4,
    )
    return mcp
