from abc import ABC, abstractmethod
from typing import Any

class Tool(ABC):
    """Base interface for every ECHO tool."""
    
    name:str
    description:str
    
    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Execute the tool."""
        raise NotImplementedError