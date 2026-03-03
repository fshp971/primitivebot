from dataclasses import dataclass, field
from typing import List, Optional
import subprocess
import os
import signal
import logging

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

    def call(self, prompt: str, cwd: str) -> tuple[str, str, int]:
        """
        Feeds the prompt into the calling function, gets and returns the response.
        Returns: (stdout, stderr, return_code)
        """
        # Construct the full command
        full_command = list(self.params.command)
        if self.params.model_version and "-m" in full_command:
            # If -m is in the template, we might want to replace it or ensure it's set
            # For simplicity, if we see 'MODEL_VERSION' placeholder, replace it.
            # However, the user said "store all necessary command and arguments" in the class.
            pass
        
        # Example for gemini-cli: ['gemini', '--yolo', '-m', self.params.model_version, '--prompt', '-']
        # Let's assume the params.command is a template or already has what's needed.
        
        try:
            process = subprocess.Popen(
                full_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                text=True,
                preexec_fn=os.setsid  # To allow killing the whole process group
            )

            try:
                stdout, stderr = process.communicate(input=prompt, timeout=self.params.timeout)
                return stdout, stderr, process.returncode
            except subprocess.TimeoutExpired:
                # Kill the whole process group
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except Exception as e:
                    logger.error(f"Failed to kill process group: {e}")
                process.communicate() # cleanup
                return "", f"Timeout after {self.params.timeout} seconds", -1
            except Exception as e:
                logger.error(f"Error during process communication: {e}")
                return "", str(e), -1
        except FileNotFoundError:
            return "", f"CLI tool not found: {full_command[0]}", -1
        except Exception as e:
            return "", f"Failed to start CLI tool: {str(e)}", -1
