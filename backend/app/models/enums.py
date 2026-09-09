import enum


class AssetType(str, enum.Enum):
    STOCK = "STOCK"
    FUND = "FUND"
    GOLD = "GOLD"
    CASH = "CASH"
    SAVINGS = "SAVINGS"
    ETF = "ETF"
    OTHER = "OTHER"


class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
