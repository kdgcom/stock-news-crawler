from typing import List, Optional
import pandas as pd
from pymongo import MongoClient
from .models import NewsArticle
from config import MONGODB_URI, DB_NAME, COLLECTION_NAME

class DataManager:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[DB_NAME]
        self.collection = self.db[COLLECTION_NAME]

    def save_to_csv(self, articles: List[NewsArticle], filename: str):
        """뉴스 기사들을 CSV 파일로 저장합니다."""
        df = pd.DataFrame([article.to_dict() for article in articles])
        df.to_csv(filename, index=False, encoding='utf-8-sig')

    def save_to_mongodb(self, article: NewsArticle):
        """뉴스 기사를 MongoDB에 저장합니다."""
        article_dict = article.to_dict()
        self.collection.insert_one(article_dict)

    def find_by_company(self, company_name: str) -> List[NewsArticle]:
        """회사명으로 기사를 검색합니다."""
        cursor = self.collection.find({'company_name': company_name})
        return [NewsArticle(**doc) for doc in cursor]

    def find_by_date_range(self, start_date, end_date) -> List[NewsArticle]:
        """날짜 범위로 기사를 검색합니다."""
        cursor = self.collection.find({
            'published_date': {
                '$gte': start_date,
                '$lte': end_date
            }
        })
        return [NewsArticle(**doc) for doc in cursor]

    def find_by_impact_range(self, min_impact: float, max_impact: float) -> List[NewsArticle]:
        """주가 영향도 범위로 기사를 검색합니다."""
        cursor = self.collection.find({
            'price_impact': {
                '$gte': min_impact,
                '$lte': max_impact
            }
        })
        return [NewsArticle(**doc) for doc in cursor] 