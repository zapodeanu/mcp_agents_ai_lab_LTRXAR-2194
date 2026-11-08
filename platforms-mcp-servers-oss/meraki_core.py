#!/usr/bin/env python3
"""
Meraki FastMCP core: self-contained declarative multi-org Meraki logic and FastMCP builder.

Supported wrapper integration path: `build_meraki_fastmcp()` (used by `meraki_stdio.py` and
`meraki_remote.py`).
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

from datetime import datetime, timedelta, timezone
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

# Meraki API configuration.
MERAKI_PROD_API_KEY = os.getenv('MERAKI_PROD_API_KEY')
MERAKI_LAB_API_KEY = os.getenv('MERAKI_LAB_API_KEY')
MERAKI_BASE_URL = os.getenv('MERAKI_BASE_URL', "https://api.meraki.com/api/v1").strip() or "https://api.meraki.com/api/v1"
USER_AGENT = "gz-mcp"

configure_server_logging("meraki", "meraki_core")

logging.info("=" * 80)
logging.info("Meraki MCP Server with Complete API Explorer Started")
logging.info("Process ID: %s", os.getpid())
logging.info("Meraki Base URL: %s", MERAKI_BASE_URL)
logging.info("=" * 80)


class MerakiApiKeyManager:
    """API key manager for multiple Meraki organizations"""

    def __init__(self):
        """Initialize API key storage and load keys from environment variables."""
        self.api_keys = {}
        self._load_api_keys()

    def _load_api_keys(self):
        """Load API keys from environment variables"""
        logging.info("Loading Meraki API keys from environment...")

        # Load all Meraki API keys from environment
        meraki_env_vars = {k: v for k, v in os.environ.items()
                           if k.startswith('MERAKI_') and k.endswith('_API_KEY')}

        for env_var, api_key in meraki_env_vars.items():
            if api_key and api_key.strip():
                self.api_keys[env_var] = api_key.strip()
                logging.info(f"Loaded API key for: {env_var}")
            else:
                logging.warning(f"Empty or invalid API key for {env_var}")

        logging.info(f"Successfully loaded {len(self.api_keys)} Meraki API keys")

    def get_api_key(self, api_key_env: str) -> str:
        """Get API key for specific organization environment variable"""
        if api_key_env in self.api_keys:
            return self.api_keys[api_key_env]

        logging.error(f"API key not found for {api_key_env}")
        raise Exception(f"API key not found for environment variable: {api_key_env}")

    def get_available_keys(self) -> list:
        """Get list of available API key environment variables"""
        return list(self.api_keys.keys())


class MerakiOrganizationManager:
    """Manager for reading Meraki organizations configuration"""

    def __init__(self, organizations_config_path: str, api_key_manager: MerakiApiKeyManager):
        """Initialize organization config paths and load enabled organizations."""
        self.organizations_config_path = organizations_config_path
        self.api_key_manager = api_key_manager
        self.organizations = {}
        self._load_organizations()

    def _load_organizations(self):
        """Load organization configuration from YAML file"""
        logging.info("Loading Meraki organizations configuration...")

        if not os.path.exists(self.organizations_config_path):
            raise FileNotFoundError(f"Organizations config file not found: {self.organizations_config_path}")

        try:
            with open(self.organizations_config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            if 'meraki_organizations' not in config:
                raise ValueError("Organizations config must include 'meraki_organizations' section")

            for org_config in config['meraki_organizations']:
                org_name = org_config.get('name')
                api_key_env = org_config.get('api_key_env')
                org_enabled = org_config.get('enabled', True)
                org_description = org_config.get('description', 'No description')

                if not org_name or not api_key_env:
                    logging.warning(f"Skipping invalid organization config: {org_config}")
                    continue

                if not org_enabled:
                    logging.info(f"Organization '{org_name}' is disabled, skipping")
                    continue

                # Verify API key exists
                try:
                    api_key = self.api_key_manager.get_api_key(api_key_env)
                    logging.info(f"API key found for organization '{org_name}'")
                except Exception as e:
                    logging.error(f"No API key found for organization '{org_name}': {e}")
                    continue

                # Store organization info
                self.organizations[org_name] = {
                    'name': org_name,
                    'api_key_env': api_key_env,
                    'description': org_description,
                    'enabled': org_enabled
                }

                logging.info(f"Loaded organization: {org_name}")

            if not self.organizations:
                raise ValueError("No enabled/valid Meraki organizations found in meraki_organizations.yaml")

            logging.info(f"Successfully loaded {len(self.organizations)} Meraki organizations")

        except Exception as e:
            logging.error(f"Failed to load organizations config: {str(e)}")
            raise

    def _auto_detect_single_org(self):
        """Auto-detect single organization setup from available API keys"""
        logging.info("Attempting to auto-detect single organization setup...")

        available_keys = self.api_key_manager.get_available_keys()

        if not available_keys:
            logging.error("No Meraki API keys found in environment")
            return

        # Use the first available API key
        primary_key_env = available_keys[0]

        try:
            api_key = self.api_key_manager.get_api_key(primary_key_env)

            # Try to determine organization name by making a test API call
            org_name = self._detect_org_name_from_api(api_key)

            if org_name:
                self.organizations[org_name] = {
                    'name': org_name,
                    'api_key_env': primary_key_env,
                    'description': f'Auto-detected organization: {org_name}',
                    'enabled': True
                }
                logging.info(f"Auto-detected single organization: {org_name}")
            else:
                # Fallback to generic name
                self.organizations["Default"] = {
                    'name': "Default",
                    'api_key_env': primary_key_env,
                    'description': 'Auto-detected default organization',
                    'enabled': True
                }
                logging.info("Auto-detected organization with default name")

        except Exception as e:
            logging.error(f"Failed to auto-detect organization: {e}")

    def _detect_org_name_from_api(self, api_key: str) -> str:
        """Try to detect organization name from API call"""
        try:
            import asyncio
            import httpx

            async def get_org_name():
                url = f"{MERAKI_BASE_URL}/organizations"
                headers = {
                    "X-Cisco-Meraki-API-Key": api_key,
                    "User-Agent": USER_AGENT
                }

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        orgs = response.json()
                        if orgs and len(orgs) > 0:
                            return orgs[0].get('name', 'Unknown')
                return None

            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(get_org_name())
            finally:
                loop.close()

        except Exception as e:
            logging.warning(f"Could not detect org name from API: {e}")
            return None

    def get_organizations(self) -> dict:
        """Get all loaded organizations"""
        return self.organizations

    def get_organization_names(self) -> list:
        """Get list of all organization names"""
        return list(self.organizations.keys())

    def get_api_key_for_org(self, org_name: str) -> str:
        """Get API key for specific organization"""
        if org_name not in self.organizations:
            raise Exception(f"Organization '{org_name}' not found")

        api_key_env = self.organizations[org_name]['api_key_env']
        return self.api_key_manager.get_api_key(api_key_env)


class MerakiAPIExplorer:
    """Cosine similarity-based API exploration using sentence transformers for Meraki API"""

    def __init__(self, swagger_file_path: str = None, cache_dir: str = None):
        """Initialize explorer state and warm embeddings from cache or OpenAPI data."""
        self.swagger_file_path = swagger_file_path or f"{PATH}/Resources/meraki_openapi.json"
        self.cache_dir = cache_dir or str(EMBEDDINGS_ASSETS_DIR)
        self.model = None
        self.embeddings_data = []
        self._initialize()

    def _initialize(self):
        """Initialize the sentence transformer model and load/build embeddings"""
        logging.info("Initializing cosine similarity Meraki API explorer...")

        # Load sentence transformer model, from local path
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
            logging.warning(f"Meraki swagger file not found: {self.swagger_file_path}")
            # Build embeddings from known Meraki API structure
            self._build_default_embeddings()
            return

        # Create cache filename based on swagger file modification time
        swagger_mtime = os.path.getmtime(self.swagger_file_path)
        cache_file = f"{self.cache_dir}/meraki_embeddings_{int(swagger_mtime)}.pkl"

        if os.path.exists(cache_file):
            logging.info(f"Loading cached Meraki embeddings from: {cache_file}")
            try:
                with open(cache_file, 'rb') as f:
                    self.embeddings_data = pickle.load(f)
                logging.info(f"Loaded {len(self.embeddings_data)} cached embeddings")
                return
            except Exception as e:
                logging.warning(f"Failed to load cached embeddings: {e}")

        # Build new embeddings
        logging.info("Building new embeddings from Meraki swagger file...")
        self._build_embeddings(cache_file)

    def _build_default_embeddings(self):
        """Build embeddings from known Meraki API structure when swagger is not available"""
        logging.info("Building default Meraki API embeddings...")

        # Common Meraki API endpoints structure
        known_endpoints = [
            # Organizations
            {
                'path': '/organizations',
                'method': 'GET',
                'summary': 'List organizations',
                'description': 'List the organizations that the user has privileges on',
                'tags': ['organizations'],
                'category': 'organizations'
            },
            {
                'path': '/organizations/{organizationId}',
                'method': 'GET',
                'summary': 'Return an organization',
                'description': 'Return an organization',
                'tags': ['organizations'],
                'category': 'organizations'
            },
            # Networks
            {
                'path': '/organizations/{organizationId}/networks',
                'method': 'GET',
                'summary': 'List networks in organization',
                'description': 'List the networks that the user has privileges on in an organization',
                'tags': ['networks'],
                'category': 'networks'
            },
            {
                'path': '/networks/{networkId}',
                'method': 'GET',
                'summary': 'Return a network',
                'description': 'Return a network',
                'tags': ['networks'],
                'category': 'networks'
            },
            # Devices
            {
                'path': '/organizations/{organizationId}/devices',
                'method': 'GET',
                'summary': 'List devices in organization',
                'description': 'List the devices in an organization',
                'tags': ['devices'],
                'category': 'devices'
            },
            {
                'path': '/networks/{networkId}/devices',
                'method': 'GET',
                'summary': 'List devices in network',
                'description': 'List the devices in a network',
                'tags': ['devices'],
                'category': 'devices'
            },
            # Clients
            {
                'path': '/networks/{networkId}/clients',
                'method': 'GET',
                'summary': 'List clients in network',
                'description': 'List the clients that have used this network in the timespan',
                'tags': ['clients'],
                'category': 'clients'
            },
            {
                'path': '/devices/{serial}/clients',
                'method': 'GET',
                'summary': 'List clients of device',
                'description': 'List the clients of a device, up to a maximum of a month ago',
                'tags': ['clients'],
                'category': 'clients'
            },
            # Switch ports
            {
                'path': '/devices/{serial}/switch/ports',
                'method': 'GET',
                'summary': 'List switch ports',
                'description': 'List the switch ports for a switch',
                'tags': ['switch', 'ports'],
                'category': 'switch'
            },
            # Wireless
            {
                'path': '/networks/{networkId}/wireless/ssids',
                'method': 'GET',
                'summary': 'List wireless SSIDs',
                'description': 'List the MR SSIDs in a network',
                'tags': ['wireless', 'ssids'],
                'category': 'wireless'
            },
            # Security events
            {
                'path': '/organizations/{organizationId}/appliance/security/events',
                'method': 'GET',
                'summary': 'List security events',
                'description': 'List the security events for an organization',
                'tags': ['security', 'appliance'],
                'category': 'security'
            },
            # Firmware
            {
                'path': '/networks/{networkId}/firmwareUpgrades',
                'method': 'GET',
                'summary': 'Get firmware upgrade information',
                'description': 'Get firmware upgrade information for a network',
                'tags': ['firmware'],
                'category': 'firmware'
            }
        ]

        self.embeddings_data = []
        for endpoint in known_endpoints:
            # Create rich text for embedding
            embedding_text = f"{endpoint['summary']} {endpoint['description']} {endpoint['path']} {' '.join(endpoint['tags'])}"

            # Generate embedding
            embedding = self.model.encode(embedding_text)

            # Store with metadata
            self.embeddings_data.append({
                'embedding': embedding,
                'metadata': {
                    'path': endpoint['path'],
                    'method': endpoint['method'],
                    'endpoint_id': f"{endpoint['method']}:{endpoint['path']}",
                    'summary': endpoint['summary'],
                    'description': endpoint['description'],
                    'tags': endpoint['tags'],
                    'category': endpoint['category'],
                    'embedding_text': embedding_text
                }
            })

        logging.info(f"Built {len(self.embeddings_data)} default Meraki embeddings")

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
            # Fall back to default embeddings
            self._build_default_embeddings()

    def _categorize_endpoint(self, path: str, operation_spec: dict):
        """Categorize Meraki API endpoint based on path and operation"""
        path_lower = path.lower()

        if any(keyword in path_lower for keyword in ['organization']):
            return 'organizations'
        elif any(keyword in path_lower for keyword in ['network']):
            return 'networks'
        elif any(keyword in path_lower for keyword in ['device', 'switch', 'wireless', 'appliance', 'camera']):
            return 'devices'
        elif any(keyword in path_lower for keyword in ['client']):
            return 'clients'
        elif any(keyword in path_lower for keyword in ['security', 'event']):
            return 'security'
        elif any(keyword in path_lower for keyword in ['firmware', 'upgrade']):
            return 'firmware'
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
    """Analytics manager for Meraki API explorer tracking"""

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
                    f"Loaded existing Meraki explorer analytics: {len(self.explorer_analytics.get('successful_calls', []))} successful calls")
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
            logging.info(f"Meraki explorer analytics: {method} {path} - SUCCESS")
        else:
            call_record.update({
                "status": "failed",
                "error": error_message
            })
            self.explorer_analytics['failed_calls'].append(call_record)
            logging.info(f"Meraki explorer analytics: {method} {path} - FAILED: {error_message}")

        # Save analytics after each call
        self._save_analytics()

    def _get_explorer_analytics(self):
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


class MerakiMcpServer:
    """Meraki MCP server core that loads config, tools, and explorer services."""

    def __init__(
            self,
            server_instance_name: str = "meraki-mcp",
            stdio_server_name: str = "meraki-mcp",
    ):
        """Initialize server dependencies, validate startup config, and register tools."""
        logging.info("Initializing Meraki MCP Server...")

        self.server_instance_name = server_instance_name
        self.stdio_server_name = stdio_server_name
        self.server = Server(self.server_instance_name)
        self.base_url = MERAKI_BASE_URL
        self.organizations_config_path = os.path.join(PATH, "Resources/meraki_organizations.yaml")
        self.tools_config_path = os.path.join(PATH, "Resources/meraki_tools.yaml")
        self.swagger_file_path = os.path.join(PATH, "Resources/meraki_openapi.json")
        self.validate_startup_config()

        # Initialize API key manager
        self.api_key_manager = MerakiApiKeyManager()

        # Initialize organization manager
        self.organization_manager = MerakiOrganizationManager(self.organizations_config_path, self.api_key_manager)

        # Check if we have any organizations configured
        if not self.organization_manager.get_organizations():
            logging.error("No Meraki organizations configured. Please check your API keys and configuration.")
            raise ValueError("No Meraki organizations available. Check API keys and configuration.")

        # Initialize analytics tracking
        self.analytics_file = f"{PATH}/logs/meraki_mcp_explorer_analytics.json"
        self.analytics_manager = ExplorerAnalytics(self.analytics_file)

        # Load configuration
        self.config = self._load_config()

        # Initialize API explorer at startup so failures are visible immediately in logs.
        self.api_explorer = MerakiAPIExplorer(self.swagger_file_path)

        # Build YAML endpoint lookup for filtering
        self.yaml_endpoints = self._build_yaml_endpoint_lookup()

        # Organize tools by category
        self.tool_categories = self._organize_tools_by_category()

        self._setup()
        logging.info("Meraki MCP Server ready!")

    def validate_startup_config(self):
        """Validate startup configuration before initializing server dependencies."""
        errors = []

        if not self.base_url:
            errors.append("MERAKI_BASE_URL is empty")

        # Validate organizations YAML and referenced API key env vars.
        if not os.path.exists(self.organizations_config_path):
            errors.append(f"Missing required file: {self.organizations_config_path}")
        else:
            try:
                with open(self.organizations_config_path, "r", encoding="utf-8") as f:
                    orgs_config = yaml.safe_load(f) or {}
                if not isinstance(orgs_config, dict):
                    errors.append("Organizations config must be a YAML mapping")
                else:
                    organizations = orgs_config.get("meraki_organizations")
                    if not isinstance(organizations, list):
                        errors.append("Organizations config must include 'meraki_organizations' as a list")
                    else:
                        enabled_valid_orgs = [
                            o for o in organizations
                            if isinstance(o, dict)
                            and o.get("enabled", True)
                            and o.get("name")
                            and o.get("api_key_env")
                        ]
                        if not enabled_valid_orgs:
                            errors.append(
                                "Organizations config has no enabled valid entries (each requires name + api_key_env)"
                            )
                        else:
                            for org in enabled_valid_orgs:
                                api_key_env = str(org.get("api_key_env"))
                                if not os.getenv(api_key_env, "").strip():
                                    errors.append(
                                        f"Missing required environment variable for organization '{org.get('name')}': {api_key_env}"
                                    )
            except Exception as exc:
                errors.append(f"Failed to parse organizations config: {exc}")

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
            error_report = "Meraki startup config validation failed:\n- " + "\n- ".join(errors)
            logging.error(error_report)
            raise ValueError(error_report)

        logging.info("Meraki startup config validation passed")

    def _ensure_api_explorer(self):
        """Initialize API explorer on demand and verify readiness."""
        if self.api_explorer is None:
            logging.info("Lazy-initializing Meraki API explorer...")
            self.api_explorer = MerakiAPIExplorer(self.swagger_file_path)

        if not self.api_explorer or not self.api_explorer.model or not self.api_explorer.embeddings_data:
            return False, (
                "Error: Meraki API explorer is unavailable. "
                "Verify embedding model files and OpenAPI resources, then retry."
            )

        return True, None

    def _load_config(self):
        """Load YAML config from your existing working configuration"""
        config_path = self.tools_config_path

        # Use your existing working configuration as default fallback
        default_config = {
            "base_url": "https://api.meraki.com/api/v1",
            "tools": [
                {
                    "name": "get_organizations",
                    "description": "Get information about available Meraki organizations",
                    "endpoint": "not_used",
                    "method": "GET",
                    "parameters": {}
                },
                {
                    "name": "list_organizations",
                    "description": "List all Meraki organizations accessible with API key(s)",
                    "endpoint": "organizations",
                    "method": "GET",
                    "parameters": {
                        "organization": {
                            "type": "string",
                            "description": "Organization name or 'all' for all configured organizations",
                            "required": False,
                            "location": "special"
                        }
                    }
                },
                {
                    "name": "list_networks",
                    "description": "List all networks in Meraki organization(s)",
                    "endpoint": "organizations/{organization_id}/networks",
                    "method": "GET",
                    "parameters": {
                        "organization": {
                            "type": "string",
                            "description": "Organization name or 'all' for all configured organizations",
                            "required": False,
                            "location": "special"
                        },
                        "organization_id": {
                            "type": "string",
                            "description": "Specific organization ID (auto-resolved from organization parameter)",
                            "required": False,
                            "location": "path"
                        }
                    }
                },
                {
                    "name": "get_network",
                    "description": "Get detailed information about a specific network",
                    "endpoint": "networks/{network_id}",
                    "method": "GET",
                    "parameters": {
                        "organization": {
                            "type": "string",
                            "description": "Organization name or 'all' to search all organizations",
                            "required": False,
                            "location": "special"
                        },
                        "network_id": {
                            "type": "string",
                            "description": "Network ID from list_networks (e.g., the 'id' field)",
                            "required": True,
                            "location": "path"
                        }
                    }
                },
                {
                    "name": "list_devices",
                    "description": "List all devices in a network",
                    "endpoint": "networks/{network_id}/devices",
                    "method": "GET",
                    "parameters": {
                        "organization": {
                            "type": "string",
                            "description": "Organization name or 'all' to search all organizations",
                            "required": False,
                            "location": "special"
                        },
                        "network_id": {
                            "type": "string",
                            "description": "Network ID from list_networks",
                            "required": True,
                            "location": "path"
                        }
                    }
                }
            ]
        }

        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            logging.info(f"Loaded your existing config with {len(config.get('tools', []))} declarative tools")
            return config
        else:
            logging.warning("Your meraki_tools.yaml not found, using built-in default")
            return default_config

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
        logging.info("Setting up Meraki MCP server handlers...")

        @self.server.list_tools()
        async def list_tools():
            """Generate tools from YAML config plus explorer tools"""
            tools = []

            # Add declarative tools from YAML config
            for tool_config in self.config.get("tools", []):
                try:
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

                    tool = Tool(
                        name=tool_config["name"],
                        description=tool_config["description"],
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
                    name="explore_meraki_api_endpoints",
                    description="Search Meraki API endpoints using natural language queries",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language description of what you want to do (e.g., 'get network devices', 'wireless settings', 'client information')"
                            },
                            "category": {
                                "type": "string",
                                "description": "Optional category filter: organizations, networks, devices, clients, security, firmware",
                                "enum": ["organizations", "networks", "devices", "clients", "security", "firmware"]
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
                    name="execute_meraki_api_endpoint",
                    description="Execute any Meraki API endpoint dynamically across organizations",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "API endpoint path (e.g., '/organizations' or '/networks/{networkId}/devices')"
                            },
                            "method": {
                                "type": "string",
                                "description": "HTTP method (GET only in OSS mode)",
                                "enum": ["GET"],
                                "default": "GET"
                            },
                            "organization": {
                                "type": "string",
                                "description": "Organization name, or 'all' to execute across all configured organizations (optional)"
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Query parameters, path parameters, or request body",
                                "additionalProperties": True
                            }
                        },
                        "required": ["path"]
                    }
                ),
                Tool(
                    name="get_meraki_endpoint_info",
                    description="Get detailed information about a Meraki API endpoint including parameters and usage",
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
                    name="get_meraki_explorer_analytics",
                    description="Get Meraki explorer analytics data for explored Meraki API endpoints showing usage patterns and success rates",
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
                if name == "explore_meraki_api_endpoints":
                    return await self._handle_cosine_search(arguments)
                elif name == "execute_meraki_api_endpoint":
                    return await self._handle_execute_explored_endpoint(arguments)
                elif name == "get_meraki_endpoint_info":
                    return await self._handle_get_endpoint_info(arguments)
                elif name == "get_meraki_explorer_analytics":
                    return await self._handle_get_analytics(arguments)

                # Handle declarative tools
                return await self._handle_declarative_tool(name, arguments)

            except Exception as e:
                logging.error(f"Error executing {name}: {e}")
                return {'content': [{'type': 'text', 'text': f'Error: {str(e)}'}]}

        logging.info("Meraki MCP server handlers registered")

    async def _handle_cosine_search(self, arguments: dict):
        """Meraki API explorer search for complete API coverage"""
        explorer_ready, explorer_error = self._ensure_api_explorer()
        if not explorer_ready:
            return {'content': [{'type': 'text', 'text': explorer_error}]}

        query = arguments.get('query', '')
        category = arguments.get('category')
        method = arguments.get('method')
        limit = arguments.get('limit', 10)
        min_similarity = arguments.get('min_similarity', 0.45)

        logging.info(f"Multi-org Meraki API explorer search: '{query}' (min_similarity: {min_similarity})")

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
                    "usage": f"execute_meraki_api_endpoint with path: {metadata['path']}"
                })

        # Limit complete endpoints to requested limit
        complete_endpoints = complete_endpoints[:limit]

        search_results = {
            "query": query,
            "search_purpose": "explore_complete_meraki_api_coverage_multi_org",
            "note": "YAML tools are already available and support multi-organization queries",
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
                "description": "These endpoints are already exposed as multi-org YAML tools",
                "count": len(yaml_covered_endpoints),
                "examples": yaml_covered_endpoints[:5]
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
                    "message": f"Found {len(high_value_endpoints)} highly relevant Meraki endpoints for complete coverage",
                    "suggestion": "These might be valuable additions to your YAML tool configuration",
                    "candidates": [ep['path'] for ep in high_value_endpoints[:3]]
                })

            if len(complete_endpoints) > 5:
                recommendations.append({
                    "type": "extensive_exploration",
                    "message": f"Explored {len(complete_endpoints)} endpoints for complete Meraki API coverage",
                    "suggestion": "Consider exploring these with execute_meraki_api_endpoint to evaluate their utility"
                })

        if yaml_covered:
            recommendations.append({
                "type": "existing_coverage",
                "message": f"{len(yaml_covered)} relevant endpoints are already available as multi-org tools",
                "suggestion": "Use the existing YAML tools which have proper parameter validation and multi-org support"
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

        analytics_summary = self.analytics_manager._get_explorer_analytics()

        if detailed:
            # Include full call history
            analytics_summary["recent_successful_calls"] = self.analytics_manager.explorer_analytics.get(
                'successful_calls', [])[-20:]
            analytics_summary["recent_failed_calls"] = self.analytics_manager.explorer_analytics.get('failed_calls',
                                                                                                     [])[-10:]

        return {'content': [{'type': 'text', 'text': json.dumps(analytics_summary, indent=2)}]}

    async def _handle_execute_explored_endpoint(self, arguments: dict):
        """Execute an explored API endpoint with multi-org support and analytics tracking"""
        explorer_ready, explorer_error = self._ensure_api_explorer()
        if not explorer_ready:
            return {'content': [{'type': 'text', 'text': explorer_error}]}

        path = arguments.get('path', '')
        method = arguments.get('method', 'GET').upper()
        if method != "GET":
            return {'content': [{'type': 'text', 'text': "Only GET method is allowed in OSS API explorer mode."}]}
        organization = arguments.get('organization', '')
        parameters = arguments.get('parameters', {})

        logging.info(f"Executing explored Meraki endpoint: {method} {path} on org: {organization}")

        # Check if this endpoint is covered by an existing YAML tool
        yaml_equivalent = self._find_yaml_equivalent(path, method)

        if yaml_equivalent:
            warning_message = {
                "warning": "Endpoint covered by existing multi-org YAML tool",
                "recommendation": f"Use existing tool: {yaml_equivalent['tool_name']}",
                "yaml_tool_info": yaml_equivalent,
                "execution_result": "Proceeding with dynamic execution, but consider using the YAML tool instead"
            }

        # Handle organization selection
        available_orgs = self.organization_manager.get_organizations()
        if not available_orgs:
            return {'content': [{'type': 'text', 'text': 'Error: No organizations configured'}]}

        if not organization:
            # Use first available organization as default
            target_orgs = [list(available_orgs.values())[0]]
            logging.info(f"Using default organization: {target_orgs[0]['name']}")
        elif organization.lower() == "all":
            target_orgs = list(available_orgs.values())
            logging.info(f"Using all organizations: {[org['name'] for org in target_orgs]}")
        elif organization.lower() in [o.lower() for o in available_orgs.keys()]:
            org_name = next(o for o in available_orgs.keys() if o.lower() == organization.lower())
            target_orgs = [available_orgs[org_name]]
            logging.info(f"Using specified organization: {org_name}")
        else:
            org_names = list(available_orgs.keys())
            return {'content': [{'type': 'text',
                                 'text': f'Error: Unknown organization "{organization}". Available organizations: {org_names}'}]}

        # Execute with analytics tracking
        execution_results = []
        for target_org in target_orgs:
            single_result = await self._execute_meraki_endpoint_with_analytics(
                path, method, parameters, target_org
            )
            parsed = _extract_result_payload(single_result)
            execution_results.append(parsed)

        if len(execution_results) == 1:
            final_payload = execution_results[0]
        else:
            final_payload = {
                "multi_organization_query": True,
                "total_organizations_queried": len(target_orgs),
                "organizations_queried": [org["name"] for org in target_orgs],
                "results": execution_results,
            }

        # Add warning if YAML tool exists
        if yaml_equivalent:
            final_payload['yaml_tool_warning'] = warning_message

        return {'content': [{'type': 'text', 'text': json.dumps(final_payload, indent=2)}]}

    async def _execute_meraki_endpoint_with_analytics(self, path: str, method: str, parameters: dict,
                                                      organization: dict):
        """Execute Meraki API call with analytics tracking"""
        analytics_success = False
        analytics_error = None
        analytics_response_data = None
        org_name = organization['name']

        try:
            # Get API key for organization
            api_key = self.organization_manager.get_api_key_for_org(org_name)

            # Build URL
            url = f"{self.base_url}/{path.lstrip('/')}"

            # Handle path parameters
            for param_name, param_value in parameters.items():
                if f"{{{param_name}}}" in url:
                    url = url.replace(f"{{{param_name}}}", str(param_value))

            # Separate query and body parameters
            query_params = {k: v for k, v in parameters.items() if f"{{{k}}}" not in path}

            headers = {
                "X-Cisco-Meraki-API-Key": api_key,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT
            }

            start_time = datetime.now()

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers, params=query_params)

                response_time_ms = (datetime.now() - start_time).total_seconds() * 1000

                if response.status_code in [200, 201, 202]:
                    result = response.json() if response.text else {"status": "success"}

                    # Mark as successful for analytics
                    analytics_success = True
                    analytics_response_data = result

                    final_result = {
                        "organization_info": {
                            "name": org_name,
                            "description": organization.get('description', 'No description')
                        },
                        "meraki_api_response": result,
                        "endpoint_info": {
                            "path": path,
                            "method": method,
                            "url": url,
                            "status_code": response.status_code
                        }
                    }
                else:
                    error_msg = f"Meraki API request failed: {response.status_code} - {response.text}"
                    analytics_error = error_msg
                    final_result = {
                        "organization_info": {
                            "name": org_name,
                            "description": organization.get('description', 'No description')
                        },
                        "error": error_msg
                    }

        except Exception as e:
            response_time_ms = (datetime.now() - start_time).total_seconds() * 1000 if 'start_time' in locals() else 0
            error_msg = f"Execution error: {str(e)}"
            analytics_error = error_msg
            final_result = {
                "organization_info": {
                    "name": org_name,
                    "description": organization.get('description', 'No description')
                },
                "error": error_msg
            }

        # Record analytics for this explorer call
        self.analytics_manager._record_explorer_call(
            path=path,
            method=method,
            parameters=parameters,
            success=analytics_success,
            response_data=analytics_response_data,
            error_message=analytics_error
        )

        return {'content': [{'type': 'text', 'text': json.dumps(final_result, indent=2)}]}

    async def _handle_declarative_tool(self, name: str, arguments: dict):
        """Handle declarative tools from YAML config with multi-org support"""
        logging.info(f"Handling declarative tool: {name} with arguments: {arguments}")

        # Find tool config
        tool_config = None
        for tool in self.config.get("tools", []):
            if tool["name"] == name:
                tool_config = tool
                break

        if not tool_config:
            return {'content': [{'type': 'text', 'text': f'Unknown declarative tool: {name}'}]}

        # SPECIAL HANDLING FOR ORGANIZATION TOOLS (must come BEFORE any other logic)

        if name == "get_configured_organizations":
            """Returns YOUR configured organizations from meraki_organizations.yaml"""
            orgs_info = {
                "configured_organizations": self.organization_manager.get_organizations(),
                "total_organizations": len(self.organization_manager.get_organizations()),
                "organization_names": self.organization_manager.get_organization_names(),
                "IMPORTANT_USAGE_NOTE": {
                    "message": "ALWAYS specify organization='Prod' or organization='Lab' when calling other tools",
                    "example": "list_networks with organization='Lab'",
                    "reason": "Resource IDs (networks, devices, clients) are specific to each organization"
                }
            }
            return {'content': [{'type': 'text', 'text': json.dumps(orgs_info, indent=2)}]}

        if name == "list_organizations_details":
            """Calls Meraki API to get org details and maps them to YOUR configured orgs"""
            available_orgs = self.organization_manager.get_organizations()

            if not available_orgs:
                return {'content': [{'type': 'text', 'text': 'Error: No organizations configured'}]}

            # REQUIRE organization parameter
            org_param = arguments.get('organization', '').lower() if arguments.get('organization') else None

            if not org_param:
                available_orgs_str = ", ".join(f"'{name}'" for name in available_orgs.keys())
                return {'content': [{'type': 'text',
                                     'text': f'❌ ERROR: list_organizations_details requires organization parameter.\n\n'
                                             f'Available organizations: {available_orgs_str}, or use "all"\n\n'
                                             f'Examples:\n'
                                             f'  - list_organizations_details with organization="Prod"\n'
                                             f'  - list_organizations_details with organization="Lab"\n'
                                             f'  - list_organizations_details with organization="all"\n\n'
                                             f'💡 TIP: Use get_configured_organizations first to see configured orgs.'}]}

            if org_param == 'all':
                target_orgs = list(available_orgs.values())
            elif org_param in [o.lower() for o in available_orgs.keys()]:
                org_name = next(o for o in available_orgs.keys() if o.lower() == org_param)
                target_orgs = [available_orgs[org_name]]
            else:
                available_orgs_str = ", ".join(f"'{name}'" for name in available_orgs.keys())
                return {'content': [{'type': 'text',
                                     'text': f'❌ ERROR: Unknown organization "{org_param}".\n\n'
                                             f'Available organizations: {available_orgs_str}\n\n'
                                             f'Use: organization="Prod", organization="Lab", or organization="all"'}]}

            # Query each organization's API
            all_org_results = []

            for org in target_orgs:
                org_name = org['name']
                logging.info(f"Fetching Meraki API organizations for: {org_name}")

                try:
                    api_key = self.organization_manager.get_api_key_for_org(org_name)
                    url = f"{self.config['base_url']}/organizations"
                    headers = {
                        "X-Cisco-Meraki-API-Key": api_key,
                        "Content-Type": "application/json",
                        "User-Agent": USER_AGENT
                    }

                    async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
                        response = await client.get(url, headers=headers)

                        if response.status_code == 200:
                            meraki_orgs = response.json()

                            # Add clear mapping to YOUR configured org
                            org_result = {
                                "configured_org_name": org_name,
                                "configured_org_description": org.get('description', 'No description'),
                                "USE_THIS_PARAMETER": f"organization='{org_name}'",
                                "meraki_api_organizations": meraki_orgs,
                                "organization_count": len(meraki_orgs),
                                "IMPORTANT_NOTE": f"When using networks, devices, or clients from this organization, ALWAYS specify organization='{org_name}' in all tool calls"
                            }
                            all_org_results.append(org_result)

                            logging.info(f"SUCCESS: Retrieved {len(meraki_orgs)} Meraki orgs for {org_name}")
                        else:
                            error_result = {
                                "configured_org_name": org_name,
                                "error": f"Meraki API request failed: {response.status_code}",
                                "error_detail": response.text
                            }
                            all_org_results.append(error_result)
                            logging.error(f"Failed to get Meraki orgs for {org_name}: {response.status_code}")

                except Exception as e:
                    error_result = {
                        "configured_org_name": org_name,
                        "error": f"Error querying Meraki API: {str(e)}"
                    }
                    all_org_results.append(error_result)
                    logging.error(f"Error querying Meraki API for {org_name}: {e}")

            # Format response
            if len(target_orgs) == 1:
                final_result = all_org_results[0] if all_org_results else {"error": "No results"}
            else:
                final_result = {
                    "multi_organization_query": True,
                    "total_configured_orgs_queried": len(target_orgs),
                    "CRITICAL_USAGE_NOTE": "Each organization below has its own networks, devices, and clients. Always specify the organization parameter in subsequent tool calls.",
                    "results": all_org_results
                }

            return {'content': [{'type': 'text', 'text': json.dumps(final_result, indent=2)}]}

        # HANDLE ALL OTHER DECLARATIVE TOOLS

        try:
            org_param = arguments.get('organization', '').lower() if arguments.get('organization') else None
            available_orgs = self.organization_manager.get_organizations()

            if not available_orgs:
                return {'content': [{'type': 'text', 'text': 'Error: No organizations configured'}]}

            # Network/device-specific tools (require specific organization)
            network_specific_tools = ['get_network', 'list_devices', 'get_network_clients',
                                      'get_device_clients', 'get_client_details']

            default_org_used = False
            org_selection_note = ""

            if name in network_specific_tools:
                if org_param == 'all':
                    available_orgs_str = ", ".join(f"'{name}'" for name in available_orgs.keys())
                    return {'content': [{'type': 'text',
                                         'text': f'❌ ERROR: Tool "{name}" requires a SPECIFIC organization.\n\n'
                                                 f'Please specify: organization=<org_name>\n'
                                                 f'Available organizations: {available_orgs_str}\n\n'
                                                 f'Example: {name}(..., organization="Prod")'}]}
                elif org_param and org_param in [o.lower() for o in available_orgs.keys()]:
                    org_name = next(o for o in available_orgs.keys() if o.lower() == org_param)
                    target_orgs = [available_orgs[org_name]]
                    org_selection_note = f"✓ Using organization: {org_name}"
                elif org_param:
                    available_orgs_str = ", ".join(f"'{name}'" for name in available_orgs.keys())
                    return {'content': [{'type': 'text',
                                         'text': f'❌ ERROR: Unknown organization "{org_param}".\n\n'
                                                 f'Available organizations: {available_orgs_str}\n\n'
                                                 f'Please use organization="Prod" or organization="Lab"'}]}
                else:
                    # NO DEFAULT - Require explicit org
                    available_orgs_str = ", ".join(f"'{name}'" for name in available_orgs.keys())
                    return {'content': [{'type': 'text',
                                         'text': f'❌ ERROR: Tool "{name}" requires organization parameter.\n\n'
                                                 f'The resource ID you provided belongs to a specific organization.\n'
                                                 f'Available organizations: {available_orgs_str}\n\n'
                                                 f'Please specify: organization="Prod" or organization="Lab"\n\n'
                                                 f'If you are unsure which organization, check the output from list_networks or list_organizations_details.'}]}
            else:
                # Organization-level tools (can use "all")
                if org_param == 'all':
                    target_orgs = list(available_orgs.values())
                    org_selection_note = f"✓ Querying all {len(target_orgs)} organizations"
                elif org_param and org_param in [o.lower() for o in available_orgs.keys()]:
                    org_name = next(o for o in available_orgs.keys() if o.lower() == org_param)
                    target_orgs = [available_orgs[org_name]]
                    org_selection_note = f"✓ Using organization: {org_name}"
                elif org_param:
                    available_orgs_str = ", ".join(f"'{name}'" for name in available_orgs.keys())
                    return {'content': [{'type': 'text',
                                         'text': f'❌ ERROR: Unknown organization "{org_param}".\n\n'
                                                 f'Available organizations: {available_orgs_str}\n\n'
                                                 f'Use organization="Prod", organization="Lab", or organization="all"'}]}
                else:
                    # For list-type tools, default to first org but warn
                    target_orgs = [list(available_orgs.values())[0]]
                    default_org_used = True
                    org_selection_note = f"⚠️ Using default organization '{target_orgs[0]['name']}' (specify organization='all' to query all orgs)"
                    logging.info(f"Tool {name} using default organization: {target_orgs[0]['name']}")

            # Execute across selected organizations
            all_results = []

            for org in target_orgs:
                org_name = org['name']
                logging.info(f"Executing on organization: {org_name}")

                try:
                    # Get API key for this organization
                    api_key = self.organization_manager.get_api_key_for_org(org_name)

                    # Build URL from endpoint template
                    url = f"{self.config['base_url']}/{tool_config['endpoint']}"

                    # Auto-resolve organization_id for any endpoint/template that needs it.
                    needs_org_id = (
                        "{organization_id}" in url
                        or any(
                            p_name == "organization_id" and p_info.get("location") == "path"
                            for p_name, p_info in tool_config.get("parameters", {}).items()
                        )
                    )

                    if needs_org_id:
                        # Get organization details to find the org ID
                        org_url = f"{self.config['base_url']}/organizations"
                        headers = {
                            "X-Cisco-Meraki-API-Key": api_key,
                            "Content-Type": "application/json",
                            "User-Agent": USER_AGENT
                        }

                        async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
                            org_response = await client.get(org_url, headers=headers)

                            if org_response.status_code == 200:
                                orgs = org_response.json()
                                if orgs:
                                    org_id = orgs[0]['id']
                                    url = url.replace('{organization_id}', str(org_id))
                                    logging.info(f"Resolved organization_id: {org_id} for {org_name}")
                                else:
                                    logging.error(f"No Meraki organizations found for {org_name}")
                                    all_results.append({
                                        "organization_info": {"name": org_name},
                                        "error": "No Meraki organizations found for this configured org"
                                    })
                                    continue
                            else:
                                logging.error(f"Failed to get organizations for {org_name}: {org_response.status_code}")
                                all_results.append({
                                    "organization_info": {"name": org_name},
                                    "error": f"Failed to resolve organization_id: {org_response.status_code}"
                                })
                                continue

                    # Replace path parameters
                    api_arguments = {k: v for k, v in arguments.items()
                                     if k not in ['organization'] and
                                     tool_config.get("parameters", {}).get(k, {}).get("location") != "special"}

                    for param_name, param_info in tool_config.get("parameters", {}).items():
                        if param_info.get("location") == "path" and param_name in api_arguments:
                            url = url.replace(f"{{{param_name}}}", str(api_arguments[param_name]))

                    # Build query parameters
                    query_params = {}
                    body_params = {}

                    for param_name, param_info in tool_config.get("parameters", {}).items():
                        if param_info.get("location") == "query" and param_name in api_arguments:
                            query_params[param_name] = api_arguments[param_name]
                        elif param_info.get("location") == "body" and param_name in api_arguments:
                            body_params[param_name] = api_arguments[param_name]

                    # Make API call
                    headers = {
                        "X-Cisco-Meraki-API-Key": api_key,
                        "Content-Type": "application/json",
                        "User-Agent": USER_AGENT
                    }

                    http_method = tool_config.get("method", "GET").upper()

                    async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
                        try:
                            if http_method == "GET":
                                response = await client.get(url, headers=headers, params=query_params)
                            elif http_method == "POST":
                                response = await client.post(url, headers=headers, json=body_params or query_params)
                            elif http_method == "PUT":
                                response = await client.put(url, headers=headers, json=body_params or query_params)
                            elif http_method == "DELETE":
                                response = await client.delete(url, headers=headers, params=query_params)
                            else:
                                raise Exception(f"Unsupported HTTP method: {http_method}")

                        except Exception as e:
                            logging.error(f"HTTP request failed: {e}")
                            all_results.append({
                                "organization_info": {
                                    "name": org_name,
                                    "description": org.get('description', ''),
                                    "was_default": default_org_used
                                },
                                "org_selection_note": org_selection_note,
                                "error": f"Connection error: {str(e)}"
                            })
                            continue

                        if response.status_code in [200, 201, 202]:
                            result = response.json() if response.text else {"status": "success"}

                            org_result = {
                                "organization_info": {
                                    "name": org_name,
                                    "description": org.get('description', ''),
                                    "was_default": default_org_used,
                                    "remember": f"For resources from this result, use organization='{org_name}' in subsequent calls"
                                },
                                "org_selection_note": org_selection_note,
                                "data": result
                            }
                            all_results.append(org_result)

                            if isinstance(result, list):
                                logging.info(f"SUCCESS: {org_name} returned {len(result)} items")
                            else:
                                logging.info(f"SUCCESS: {org_name} returned data")

                        else:
                            logging.error(f"{org_name} API request failed: {response.status_code}")

                            troubleshooting = ""
                            if response.status_code == 404:
                                troubleshooting = f"❌ Resource not found in organization '{org_name}'. This resource may belong to a different organization. Try organization='Lab' (or 'Prod' if you used Lab)."
                            elif response.status_code == 403:
                                troubleshooting = "Permission denied. API key may not have access to this resource."
                            elif response.status_code == 400:
                                troubleshooting = "Bad request. Check if parameters are valid for this organization."

                            all_results.append({
                                "organization_info": {
                                    "name": org_name,
                                    "was_default": default_org_used
                                },
                                "org_selection_note": org_selection_note,
                                "error": f"HTTP {response.status_code}",
                                "error_detail": response.text[:200],
                                "troubleshooting": troubleshooting
                            })

                except Exception as e:
                    logging.error(f"Error processing organization {org_name}: {e}")
                    all_results.append({
                        "organization_info": {"name": org_name},
                        "error": f"Processing error: {str(e)}"
                    })

            # Format final response
            if len(target_orgs) == 1:
                final_result = all_results[0] if all_results else {"error": "No results"}
            else:
                final_result = {
                    "multi_organization_query": True,
                    "total_organizations_queried": len(target_orgs),
                    "organizations_queried": [org['name'] for org in target_orgs],
                    "results": all_results
                }

            return {'content': [{'type': 'text', 'text': json.dumps(final_result, indent=2)}]}

        except Exception as e:
            logging.error(f"Error executing declarative tool '{name}': {str(e)}")
            return {'content': [{'type': 'text', 'text': f'Error: {str(e)}'}]}

    async def run(self):
        """Run the Meraki MCP server"""
        logging.info("Starting Meraki MCP server...")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name=self.stdio_server_name,
                    server_version="3.0.0",
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


def _build_declarative_tool_fn(core: MerakiMcpServer, tool_name: str, params: dict[str, dict[str, Any]]):
    """Build a FastMCP async tool callable from declarative YAML metadata.

    Args:
        core: Meraki core server instance that executes the underlying tool handler.
        tool_name: Declarative tool name from `Resources/meraki_tools.yaml`.
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


def build_meraki_fastmcp(host: str = "127.0.0.1", port: int = 8001) -> FastMCP:
    """Build the Meraki FastMCP application used by stdio/remote wrappers.

    Args:
        host: Listener host used by streamable HTTP transport.
        port: Listener port used by streamable HTTP transport.

    Returns:
        Configured `FastMCP` app with explorer and declarative tools registered.

    Side effects:
        Initializes Meraki core services, loads resource files, and sets up
        embedding-backed API exploration data during startup.
    """
    core = MerakiMcpServer(server_instance_name="meraki-mcp", stdio_server_name="meraki-mcp")
    mcp = FastMCP(name="meraki-mcp", host=host, port=port, streamable_http_path="/mcp")

    @mcp.tool(name="explore_meraki_api_endpoints", description="Search Meraki API endpoints using natural language queries")
    async def explore_meraki_api_endpoints(
        query: Annotated[
            str,
            Field(description="Natural language description of what you want to do (e.g., 'get network devices', 'wireless settings', 'client information')"),
        ],
        category: Annotated[
            Literal["organizations", "networks", "devices", "clients", "security", "firmware"] | None,
            Field(description="Optional category filter: organizations, networks, devices, clients, security, firmware"),
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

    @mcp.tool(name="execute_meraki_api_endpoint", description="Execute any Meraki API endpoint dynamically across organizations")
    async def execute_meraki_api_endpoint(
        path: Annotated[
            str,
            Field(description="API endpoint path (e.g., '/organizations' or '/networks/{networkId}/devices')"),
        ],
        method: Annotated[
            Literal["GET"],
            Field(description="HTTP method (GET only in OSS mode)"),
        ] = "GET",
        organization: Annotated[
            str | None,
            Field(description="Organization name, or 'all' to execute across all configured organizations (optional)"),
        ] = None,
        parameters: Annotated[
            dict[str, Any] | None,
            Field(description="Query parameters, path parameters, or request body"),
        ] = None,
    ):
        result = await core._handle_execute_explored_endpoint(
            {
                "path": path,
                "method": method,
                "organization": organization,
                "parameters": parameters or {},
            }
        )
        return _extract_result_payload(result)

    @mcp.tool(name="get_meraki_endpoint_info", description="Get detailed information about a Meraki API endpoint including parameters and usage")
    async def get_meraki_endpoint_info(
        path: Annotated[str, Field(description="API endpoint path")],
        method: Annotated[
            Literal["GET"],
            Field(description="HTTP method (GET only in OSS mode)"),
        ] = "GET",
    ):
        result = await core._handle_get_endpoint_info({"path": path, "method": method})
        return _extract_result_payload(result)

    @mcp.tool(name="get_meraki_explorer_analytics", description="Get Meraki explorer analytics data for explored API endpoints")
    async def get_meraki_explorer_analytics(
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

    logging.getLogger("meraki_fastmcp_adapter").info(
        "FastMCP Meraki initialized with %s tools",
        len(core.config.get("tools", [])) + 4,
    )
    return mcp
