from pydantic import BaseModel


class LongbridgeHealthResponse(BaseModel):
    enabled: bool
    configured: bool
    sdk_loaded: bool
    oauth_connected: bool = False
    message: str


class LongbridgeCandleItem(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float


class LongbridgeCandlesResponse(BaseModel):
    symbol: str
    start: str
    end: str
    period: str
    items: list[LongbridgeCandleItem]
    source: str = "longbridge"


class LongbridgeBenchmarkCandlesResponse(BaseModel):
    start: str
    end: str
    period: str
    benchmarks: dict[str, list[LongbridgeCandleItem]]
    source: str = "longbridge"


class LongbridgeNewsItem(BaseModel):
    title: str
    summary: str
    url: str
    published_at: str
    source: str = "longbridge"


class LongbridgeNewsResponse(BaseModel):
    symbol: str
    items: list[LongbridgeNewsItem]


class LongbridgeMacroNewsResponse(BaseModel):
    keyword: str
    items: list[LongbridgeNewsItem]
    source: str = "longbridge"
