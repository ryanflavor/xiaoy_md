"""
Ultra-lightweight NATS IPC SDK - Enterprise-grade Inter-Process Communication

This module provides a minimal yet powerful SDK for building distributed systems
using NATS messaging. It supports RPC calls, broadcast/subscribe patterns, and
handles any Python object through pickle serialization.

Features:
    - Single-file implementation with minimal dependencies
    - Support for any Python object type (via pickle)
    - Async/await support
    - Automatic failover with cluster support
    - Type-safe with full type hints
    - Comprehensive error handling
"""

import asyncio
import pickle
import uuid
import os
from typing import Any, Callable, Optional, List, Union, Dict, TypeVar, Awaitable

import nats
from nats.aio.msg import Msg
from nats.aio.client import Client
from nats.aio.subscription import Subscription

# Type definitions
T = TypeVar("T")
Handler = Callable[..., Any]
AsyncHandler = Callable[..., Awaitable[Any]]
MessageHandler = Callable[[Any], Union[None, Awaitable[None]]]

# Default timeout from environment or 30 seconds
DEFAULT_TIMEOUT = float(os.getenv("NATS_TIMEOUT", "30"))


class IPCNode:
    """
    Enterprise-grade IPC node for NATS-based communication.

    This class provides a high-level interface for inter-process communication
    using NATS messaging. It supports both RPC (request-reply) and pub-sub patterns.

    Attributes:
        node_id: Unique identifier for this node
        nats_url: NATS server URL(s) for connection
        timeout: Default timeout for RPC calls in seconds
        nc: NATS client connection
        methods: Registry of exposed RPC methods
        subscriptions: Active NATS subscriptions

    Example:
        >>> async with IPCNode("my_service") as node:
        ...     await node.register("add", lambda a, b: a + b)
        ...     result = await node.call("other_service", "multiply", 3, 4)
    """

    def __init__(
        self,
        node_id: Optional[str] = None,
        nats_url: Optional[Union[str, List[str]]] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """
        Initialize an IPC node.

        Args:
            node_id: Unique identifier for this node. If None, generates a random ID.
            nats_url: NATS server URL(s). Can be a single URL or list for cluster.
                     If None, uses NATS_SERVERS env var or defaults to localhost.
            timeout: Default timeout for RPC calls in seconds. Defaults to 30s.
        """
        self.node_id = node_id or f"node_{uuid.uuid4().hex[:8]}"
        # Use provided URL or get from environment or default to localhost
        if nats_url is None:
            nats_url = os.getenv("NATS_SERVERS", "nats://localhost:4222")
            if "," in nats_url:
                nats_url = nats_url.split(",")
        self.nats_url = nats_url
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.nc: Optional[Client] = None
        self.methods: Dict[str, Handler] = {}
        self.subscriptions: List[Subscription] = []

    async def connect(self) -> None:
        """
        Establish connection to NATS server(s).

        Connects to the configured NATS server(s) and sets up subscriptions
        for any previously registered methods.

        Raises:
            nats.errors.Error: If connection fails
        """
        if isinstance(self.nats_url, str):
            self.nc = await nats.connect(self.nats_url)
        else:
            self.nc = await nats.connect(servers=self.nats_url)

        # Setup existing method subscriptions
        for method_name in self.methods:
            await self._subscribe_method(method_name)

    async def disconnect(self) -> None:
        """
        Gracefully disconnect from NATS.

        Unsubscribes from all active subscriptions and closes the NATS connection.
        Safe to call multiple times.
        """
        for sub in self.subscriptions:
            await sub.unsubscribe()
        if self.nc:
            await self.nc.close()
        self.subscriptions.clear()
        self.nc = None

    async def register(self, name: str, handler: Handler) -> None:
        """
        Register a method for RPC exposure.

        The registered method can be called remotely by other nodes using the
        `call` method. Supports both sync and async handlers.

        Args:
            name: Method name to expose
            handler: Function to handle RPC calls. Can be sync or async.

        Example:
            >>> await node.register("greet", lambda name: f"Hello {name}!")
        """
        self.methods[name] = handler
        if self.nc and self.nc.is_connected:
            await self._subscribe_method(name)

    async def call(self, target: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """
        Make an RPC call to a remote method.

        Calls a method registered on another node and waits for the response.
        Supports passing any pickle-serializable arguments.

        Args:
            target: Target node ID
            method: Method name to call
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            The return value from the remote method (any pickle-serializable type)

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If the call times out
            Exception: If the remote method raises an exception

        Example:
            >>> result = await node.call("math_service", "add", 10, 20)
            >>> config = await node.call("config_service", "get_config", section="db")
        """
        if not self.nc or not self.nc.is_connected:
            raise RuntimeError("Not connected to NATS")

        subject = f"ipc.{target}.{method}"
        request = pickle.dumps({"args": args, "kwargs": kwargs})

        try:
            response = await self.nc.request(subject, request, timeout=self.timeout)
            result = pickle.loads(response.data)
            if "error" in result:
                raise Exception(f"Remote error in {target}.{method}: {result['error']}")
            return result.get("result")
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Call to {target}.{method} timed out after {self.timeout}s"
            )
        except Exception as e:
            # Re-raise with more context
            if "Remote error" not in str(e):
                raise Exception(f"Error calling {target}.{method}: {e}") from e
            raise

    async def broadcast(self, channel: str, data: Any) -> None:
        """
        Broadcast data to all subscribers of a channel.

        Sends data to all nodes subscribed to the specified channel.
        Fire-and-forget operation with no acknowledgment.

        Args:
            channel: Channel name to broadcast on
            data: Data to broadcast (any pickle-serializable type)

        Raises:
            RuntimeError: If not connected to NATS

        Example:
            >>> await node.broadcast("events", {"type": "user_login", "user_id": 123})
        """
        if not self.nc or not self.nc.is_connected:
            raise RuntimeError("Not connected to NATS")
        await self.nc.publish(f"broadcast.{channel}", pickle.dumps(data))

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        """
        Subscribe to a broadcast channel.

        Registers a handler to be called whenever data is broadcast on the
        specified channel. Handler can be sync or async.

        Args:
            channel: Channel name to subscribe to
            handler: Function to handle received messages.
                    Takes one argument (the broadcast data).

        Raises:
            RuntimeError: If not connected to NATS

        Example:
            >>> async def on_event(data):
            ...     print(f"Received: {data}")
            >>> await node.subscribe("events", on_event)
        """
        if not self.nc or not self.nc.is_connected:
            raise RuntimeError("Not connected to NATS")

        async def wrapper(msg: Msg) -> None:
            try:
                data = pickle.loads(msg.data)
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                # Log error but don't crash the subscription
                print(f"Error in subscription handler for {channel}: {e}")

        sub = await self.nc.subscribe(f"broadcast.{channel}", cb=wrapper)
        self.subscriptions.append(sub)

    async def _subscribe_method(self, method_name: str) -> None:
        """
        Internal method to setup NATS subscription for an RPC method.

        Args:
            method_name: Name of the method to subscribe

        Raises:
            RuntimeError: If not connected to NATS
        """
        if not self.nc or not self.nc.is_connected:
            raise RuntimeError("Not connected to NATS")

        subject = f"ipc.{self.node_id}.{method_name}"

        async def handler(msg: Msg) -> None:
            """Handle incoming RPC requests."""
            try:
                request = pickle.loads(msg.data)
                method = self.methods[method_name]

                # Validate request format
                if (
                    not isinstance(request, dict)
                    or "args" not in request
                    or "kwargs" not in request
                ):
                    raise ValueError("Invalid request format")

                # Execute method
                if asyncio.iscoroutinefunction(method):
                    result = await method(*request["args"], **request["kwargs"])
                else:
                    result = method(*request["args"], **request["kwargs"])

                # Send response
                response = {"result": result}
            except Exception as e:
                # Include full error information for debugging
                response = {"error": f"{type(e).__name__}: {str(e)}"}

            await msg.respond(pickle.dumps(response))

        sub = await self.nc.subscribe(subject, cb=handler)
        self.subscriptions.append(sub)

    async def __aenter__(self) -> "IPCNode":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()
