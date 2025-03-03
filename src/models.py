from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class NewsArticle:
    title: str
    company_name: str
    stock_code: str
    content: str
    price_impact: float
    published_date: datetime
    publisher: str
    daily_occurrence: int
    url: str
    article_id: Optional[str] = None

    def to_dict(self):
        return {
            'title': self.title,
            'company_name': self.company_name,
            'stock_code': self.stock_code,
            'content': self.content,
            'price_impact': self.price_impact,
            'published_date': self.published_date,
            'publisher': self.publisher,
            'daily_occurrence': self.daily_occurrence,
            'url': self.url,
            'article_id': self.article_id
        } 