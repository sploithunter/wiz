"""Content cycle pipeline: blog writer then social manager."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from wiz.agents.blog_writer import BlogWriterAgent
from wiz.agents.social_manager import SocialManagerAgent
from wiz.bridge.client import BridgeClient
from wiz.bridge.monitor import BridgeEventMonitor
from wiz.bridge.runner import SessionRunner
from wiz.config.schema import WizConfig
from wiz.memory.long_term import LongTermMemory
from wiz.orchestrator.state import CycleState

logger = logging.getLogger(__name__)


class ContentCyclePipeline:
    """Runs content cycle: blog writer -> social manager."""

    def __init__(self, config: WizConfig) -> None:
        self.config = config

    def _create_runner(self) -> SessionRunner:
        client = BridgeClient(self.config.global_.coding_agent_bridge_url)
        monitor = BridgeEventMonitor(self.config.global_.coding_agent_bridge_url)
        return SessionRunner(client, monitor)

    def run(self) -> CycleState:
        state = CycleState(repo="content")
        start = time.time()
        memory = LongTermMemory(Path(self.config.memory.long_term_dir))
        memory.load_index()

        # Blog Writer
        try:
            runner = self._create_runner()
            blog = BlogWriterAgent(runner, self.config.agents.blog_writer, memory)
            result = blog.run(".", timeout=self.config.agents.blog_writer.session_timeout)
            state.add_phase("blog_write", result.get("success", False), result)
        except Exception as e:
            state.add_phase("blog_write", False, {"error": str(e)})

        # Social Manager
        try:
            runner = self._create_runner()
            social = SocialManagerAgent(runner, self.config.agents.social_manager, memory)
            result = social.run(".", timeout=self.config.agents.social_manager.session_timeout)
            state.add_phase("social_manage", result.get("success", False), result)
        except Exception as e:
            state.add_phase("social_manage", False, {"error": str(e)})

        state.total_elapsed = time.time() - start
        return state
