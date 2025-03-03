from .models import NewsArticle

class NewsAnalyzer:
    def analyze_price_impact(self, article: NewsArticle) -> float:
        """기사가 주가에 미칠 영향을 분석합니다."""
        # 여기에 감성 분석 또는 다른 분석 로직을 구현
        # 현재는 더미 값을 반환
        return 0.0

    def analyze_similarity(self, article1: NewsArticle, article2: NewsArticle) -> float:
        """두 기사의 유사도를 분석합니다."""
        # 텍스트 유사도 분석 로직 구현
        return 0.0 