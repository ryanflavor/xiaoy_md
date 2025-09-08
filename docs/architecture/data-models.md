# **4\. Data Models**

The core data model for the MVP will be based on vnpy.trader.object.TickData and defined using Pydantic to ensure type safety.

## **TickDataModel (Pydantic)**

**Purpose**: Defines the standard market data structure for all inter-service communication (DTO).

Python

\# file: src/domain/models/tick.py
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

class Exchange(str, Enum):
    CFFEX \= "CFFEX"
    SHFE \= "SHFE"
    CZCE \= "CZCE"
    DCE \= "DCE"
    INE \= "INE"
    GFEX \= "GFEX"
    SSE \= "SSE"
    SZSE \= "SZSE"

class DomainTick(BaseModel):
    """
    Internal domain model for a tick, decoupled from vnpy's structure.
    """
    symbol: str \= Field(..., description="Contract symbol")
    exchange: Exchange \= Field(..., description="Exchange")
    datetime: datetime \= Field(..., description="Timestamp (UTC)")
    last\_price: float \= Field(..., description="Last price")
    volume: float \= Field(..., description="Volume")
    \# ... other essential fields

    class Config:
        use\_enum\_values \= True

*Note: We will maintain a clear maintenance process to keep this model in sync with any future changes to vnpy's TickData object and will standardize all timestamps to UTC during translation.*

---
