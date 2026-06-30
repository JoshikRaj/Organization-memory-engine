from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Any


class Document(BaseModel):
    source: str
    content: str
    author: str
    timestamp: datetime
    metadata: Dict[str, Any]