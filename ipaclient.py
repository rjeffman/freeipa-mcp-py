"""
Minimal IPA Client - JSON-RPC interface to FreeIPA servers.

This module provides a lightweight client for interacting with FreeIPA
servers via JSON-RPC. It requires Kerberos authentication (existing tickets
via kinit) and returns pure Python dictionaries suitable for MCP integration.

Example:
    >>> from ipaclient import IPAClient
    >>> client = IPAClient("ipa.example.com")
    >>> result = client.ping()
    >>> print(result["summary"])
    IPA server version 4.9.8. API version 2.251

Dependencies:
    - requests: HTTP client
    - requests-gssapi: Kerberos authentication
"""

from typing import Dict, List, Optional, Any
import requests
from requests_gssapi import HTTPSPNEGOAuth


__version__ = "0.1.0"
__all__ = [
    "IPAClient",
    "IPAError",
    "IPAConnectionError",
    "IPAAuthenticationError",
    "IPAServerError",
    "IPASchemaError",
    "IPAValidationError",
]


# ============================================================================
# Exceptions
# ============================================================================


class IPAError(Exception):
    """Base exception for all IPA client errors.

    All IPA exceptions include a `.to_dict()` method for easy serialization
    in MCP server responses.

    Attributes:
        message: Human-readable error message
        code: Error code (defaults to class name)
        data: Additional error context
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        """Initialize IPA error.

        Args:
            message: Human-readable error message
            code: Optional error code (defaults to class name)
            data: Optional additional error context
        """
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.data = data or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dict for MCP integration.

        Returns:
            Dictionary with error details suitable for JSON serialization.
        """
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "data": self.data,
            }
        }


class IPAConnectionError(IPAError):
    """Network or connection failure."""

    pass


class IPAAuthenticationError(IPAError):
    """Kerberos authentication failure."""

    pass


class IPAServerError(IPAError):
    """IPA server returned an error."""

    pass


class IPASchemaError(IPAError):
    """Schema fetch or parse failure."""

    pass


class IPAValidationError(IPAError):
    """Invalid parameters or arguments."""

    pass


# ============================================================================
# Main Client
# ============================================================================


class IPAClient:
    """Minimal IPA JSON-RPC client.

    Provides programmatic access to FreeIPA servers via JSON-RPC protocol.
    Requires Kerberos authentication (existing tickets via kinit).

    All methods return Python dictionaries suitable for JSON serialization
    and MCP integration.

    Example:
        >>> client = IPAClient("ipa.example.com")
        >>> result = client.ping()
        >>> print(result["summary"])
        IPA server version 4.9.8. API version 2.251
    """

    def __init__(self, server: str, verify_ssl: bool = True):
        """Initialize IPA client.

        Args:
            server: IPA server hostname (e.g., 'ipa.example.com')
            verify_ssl: Whether to verify SSL certificates (default: True)
        """
        self._server = server
        self._base_url = f"https://{server}"
        self._json_url = f"{self._base_url}/ipa/json"
        self._verify_ssl = verify_ssl
        self._schema: Optional[Dict[str, Any]] = None

    def _make_request(
        self,
        method: str,
        args: Optional[List[Any]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a JSON-RPC request to the IPA server.

        Args:
            method: IPA command name (e.g., 'user_show', 'ping')
            args: Positional arguments for the command
            options: Keyword arguments/options for the command

        Returns:
            Result dictionary from the server

        Raises:
            IPAConnectionError: Network/connection failure
            IPAAuthenticationError: Kerberos authentication failure
            IPAServerError: Server returned an error
        """
        if args is None:
            args = []
        if options is None:
            options = {}

        # Add API version if not already present
        if "version" not in options:
            options["version"] = "2.251"

        # Build JSON-RPC payload
        payload = {
            "method": method,
            "params": [args, options],
            "id": 0,
        }

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Referer": f"{self._base_url}/ipa",
            "Accept": "application/json",
        }

        # Make request with Kerberos authentication
        try:
            response = requests.post(
                self._json_url,
                json=payload,
                headers=headers,
                auth=HTTPSPNEGOAuth(opportunistic_auth=True),
                verify=self._verify_ssl,
            )
        except requests.exceptions.SSLError as e:
            raise IPAConnectionError(
                f"SSL verification failed for {self._server}: {e}",
                data={"server": self._server},
            )
        except requests.exceptions.ConnectionError as e:
            raise IPAConnectionError(
                f"Failed to connect to {self._server}: {e}",
                data={"server": self._server},
            )
        except requests.exceptions.RequestException as e:
            raise IPAConnectionError(
                f"Request failed: {e}",
                data={"server": self._server},
            )

        # Check HTTP status
        if response.status_code != 200:
            raise IPAServerError(
                f"HTTP {response.status_code}: {response.text}",
                code=f"HTTP{response.status_code}",
                data={"status_code": response.status_code},
            )

        # Parse JSON response
        try:
            result = response.json()
        except ValueError as e:
            raise IPAServerError(
                f"Invalid JSON response: {e}",
                code="InvalidJSON",
            )

        # Check for IPA errors
        if result.get("error") is not None:
            error = result["error"]
            error_msg = error.get("message", str(error))
            error_code = error.get("name", error.get("code", "UnknownError"))

            # Check for authentication errors
            if "Unauthorized" in error_msg or "credentials" in error_msg.lower():
                raise IPAAuthenticationError(
                    f"Authentication failed: {error_msg}",
                    code=str(error_code),
                    data=error,
                )

            raise IPAServerError(
                f"IPA error: {error_msg}",
                code=str(error_code),
                data=error,
            )

        return result.get("result", {})

    def ping(self) -> Dict[str, Any]:
        """Test server connectivity.

        Returns:
            Dictionary with summary of server version and API version.
            Example: {"summary": "IPA server version 4.9.8. API version 2.251"}

        Raises:
            IPAConnectionError: Network/connection failure
            IPAAuthenticationError: Kerberos auth failure
            IPAServerError: Server returned error
        """
        return self._make_request("ping")

    def _get_schema(self) -> Dict[str, Any]:
        """Retrieve and cache IPA schema.

        Fetches the full IPA schema on first call and caches it in memory.
        Subsequent calls return the cached version.

        Returns:
            Full IPA schema dictionary with 'topics' and 'commands' keys

        Raises:
            IPASchemaError: Schema fetch or parse failure
        """
        if self._schema is not None:
            return self._schema

        try:
            result = self._make_request("schema")

            # Unwrap nested result (IPA returns {'result': {'commands': ...}})
            if isinstance(result, dict) and "result" in result:
                result = result["result"]

            # Validate schema structure
            if not isinstance(result, dict):
                raise IPASchemaError(
                    "Invalid schema format: expected dict",
                    data={"type": type(result).__name__},
                )

            if "commands" not in result:
                raise IPASchemaError(
                    "Invalid schema: missing 'commands' key",
                    data={"keys": list(result.keys())},
                )

            # Transform commands list to dict keyed by name for easier access
            if isinstance(result["commands"], list):
                commands_dict = {}
                for cmd in result["commands"]:
                    if "name" in cmd:
                        commands_dict[cmd["name"]] = cmd
                result["commands"] = commands_dict

            # Transform topics list to dict if needed
            if "topics" in result and isinstance(result["topics"], list):
                topics_dict = {}
                for topic in result["topics"]:
                    if "name" in topic:
                        topics_dict[topic["name"]] = topic
                result["topics"] = topics_dict

            self._schema = result
            return self._schema

        except IPAServerError as e:
            raise IPASchemaError(
                f"Schema fetch failed: {e.message}",
                data=e.data,
            )
        except (IPAConnectionError, IPAAuthenticationError):
            # Re-raise connection/auth errors as-is
            raise

    def command(self, name: str, *args, **kwargs) -> Dict[str, Any]:
        """Execute arbitrary IPA command.

        Args:
            name: Command name (e.g., 'user_show', 'group_find')
            *args: Positional arguments for the command
            **kwargs: Keyword arguments/options for the command

        Returns:
            Command-specific result dictionary. Structure varies by command,
            but typically includes:
            - 'result': Main result data (dict, list, or other type)
            - 'summary': Human-readable summary (for some commands)
            - 'count': Number of results (for search commands)
            - 'truncated': Whether results were truncated (for search commands)

        Example:
            >>> client.command("user_show", "admin")
            {'uid': ['admin'], 'cn': ['Administrator'], ...}

            >>> client.command("user_find", uid="admin")
            {'result': [...], 'count': 1, 'truncated': False}

        Raises:
            IPAServerError: Command execution failed
            IPAValidationError: Invalid arguments
            IPAConnectionError: Network failure
        """
        return self._make_request(name, args=list(args), options=kwargs)

    def help(self, topic: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve help information.

        Args:
            topic: Optional topic or command name
                   None or "topics" -> list all topics
                   "commands" -> list all commands
                   "<topic>" -> commands in topic
                   "<command>" -> command details

        Returns:
            Structure varies by topic parameter. See class docstring for details.

        Raises:
            IPASchemaError: Schema fetch/parse failure
            IPAConnectionError: Network failure
        """
        schema = self._get_schema()

        # Default to topics listing
        if topic is None or topic == "topics":
            return self._help_topics(schema)

        # Commands listing
        if topic == "commands":
            return self._help_commands(schema)

        # Check if it's a command
        if topic in schema.get("commands", {}):
            return self._help_command(schema, topic)

        # Check if it's a topic
        if topic in schema.get("topics", {}):
            return self._help_topic(schema, topic)

        # Not found
        raise IPAValidationError(
            f"Unknown command or topic: {topic}",
            code="NotFound",
            data={"topic": topic},
        )

    def _help_topics(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Generate topic listing.

        Args:
            schema: Full IPA schema

        Returns:
            Dictionary with 'topics' key containing list of topic dicts
        """
        topics = []

        for topic_name, topic_data in schema.get("topics", {}).items():
            # Extract summary from first non-empty line of doc
            doc = topic_data.get("doc", "")
            summary = ""
            for line in doc.split("\n"):
                line = line.strip()
                if line:
                    summary = line
                    break

            topics.append({
                "name": topic_name,
                "summary": summary,
            })

        # Sort alphabetically by name
        topics.sort(key=lambda t: t["name"])

        return {"topics": topics}

    def _help_commands(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Generate commands listing.

        Args:
            schema: Full IPA schema

        Returns:
            Dictionary with 'commands' key containing list of command dicts
        """
        commands = []

        for cmd_name, cmd_data in schema.get("commands", {}).items():
            commands.append({
                "name": cmd_name,
                "summary": cmd_data.get("summary", ""),
            })

        # Sort alphabetically by name
        commands.sort(key=lambda c: c["name"])

        return {"commands": commands}

    def _help_topic(self, schema: Dict[str, Any], topic: str) -> Dict[str, Any]:
        """Generate topic details with associated commands.

        Args:
            schema: Full IPA schema
            topic: Topic name (e.g., 'user', 'group')

        Returns:
            Dictionary with topic info and list of commands in the topic
        """
        topic_data = schema["topics"][topic]

        # Find commands belonging to this topic
        commands = []
        for cmd_name, cmd_data in schema.get("commands", {}).items():
            if cmd_data.get("topic") == topic:
                commands.append({
                    "name": cmd_name,
                    "summary": cmd_data.get("summary", ""),
                })

        # Sort commands alphabetically
        commands.sort(key=lambda c: c["name"])

        return {
            "name": topic,
            "doc": topic_data.get("doc", ""),
            "commands": commands,
        }
