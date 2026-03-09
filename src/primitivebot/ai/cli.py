import asyncio
import os
import signal
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class AICLIToolParams:
    """Hyperparameters for starting and running an AI CLI tool."""
    command: List[str]
    timeout: int = 600
    model_version: str = "auto"
    # additional arguments can be added here
    extra_args: List[str] = field(default_factory=list)

class AICLITool:
    """A model/tool agnostic AI CLI tool calling class."""

    def __init__(self, params: AICLIToolParams):
        self.params = params

    async def call(self, prompt: str, cwd: str) -> tuple[str, str, int]:
        """
        Feeds the prompt into the calling function, gets and returns the response.
        Returns: (stdout, stderr, return_code)
        """
        # Construct the full command
        full_command = list(self.params.command)

        try:
            process = await asyncio.create_subprocess_exec(
                *full_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                preexec_fn=os.setsid  # To allow killing the whole process group
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(input=prompt.encode()),
                    timeout=self.params.timeout
                )
                return stdout_data.decode(), stderr_data.decode(), process.returncode
            except asyncio.TimeoutError:
                # Kill the whole process group
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except Exception as e:
                    logger.error(f"Failed to kill process group on timeout: {e}")

                # Try to cleanup, but don't wait forever
                try:
                    await asyncio.wait_for(process.communicate(), timeout=5)
                except:
                    pass
                return "", f"Timeout after {self.params.timeout} seconds", -1
            except asyncio.CancelledError:
                # Kill the whole process group if the task is cancelled
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except Exception as e:
                    logger.error(f"Failed to kill process group on cancellation: {e}")
                
                # Try to cleanup, but don't wait forever
                try:
                    await asyncio.wait_for(process.communicate(), timeout=5)
                except:
                    pass
                raise
            except Exception as e:
                logger.error(f"Error during process communication: {e}")
                return "", str(e), -1
        except FileNotFoundError:
            return "", f"CLI tool not found: {full_command[0]}", -1
        except Exception as e:
            return "", f"Failed to start CLI tool: {str(e)}", -1
